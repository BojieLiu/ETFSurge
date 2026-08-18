"""MarketDataHub facade — split implementations into app/services/hub/ (Batch 3).

The facade keeps the singleton, shared-state initialization and orchestration
methods (``refresh`` / ``_refresh_impl`` / snapshot warmers / sector cache) plus
the pure-strategy helpers (moved to ``engine/`` in Batch 4). Cluster methods are
inherited from the mixin classes defined in ``app/services/hub/``.

Public API and the ``market_data_hub`` singleton are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from ..fetchers import etf_scanner
from ..fetchers import sector_fetcher
from ..factors.factor_registry import registry as factor_registry
from .etf_classifier import classifier as etf_classifier
from .pool_audit import pool_audit
from ..core.market_calendar import market_session

from app.services.hub._common import (
    MANDATORY_CODES,
    SECTOR_ETF_MAP,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    ALL_LAYERS,
    _LAYER_WEIGHTS,
    _BASE_WEIGHTS,
    MAX_PER_LAYER,
    _snapshot_db_path,
    _snapshot_as_of_for,
    _persist_snapshot_sync,
    _load_latest_snapshot_sync,
    _parse_stock_list,
    _parse_concept_tags,
    _normalize_hot_plate,
    _strong_sector_etfs,
    _rule_news_summary,
    PoolDiff,
)
from app.services.hub._snapshot import SnapshotMixin
from app.services.hub._kline import KlineMixin
from app.services.hub._realtime import RealtimeMixin
from app.services.hub._sector import SectorMixin
from app.services.hub._news import NewsMixin
from app.services.hub._regime_sentiment import RegimeSentimentMixin
from app.services.hub._pool import PoolMixin
from app.services.hub._fundamentals import FundamentalsMixin

logger = logging.getLogger(__name__)


class MarketDataHub(
    KlineMixin,
    RealtimeMixin,
    SectorMixin,
    NewsMixin,
    RegimeSentimentMixin,
    PoolMixin,
    FundamentalsMixin,
    SnapshotMixin,
):
    _last_refresh_ts: float = 0.0


    _refresh_lock: asyncio.Lock | None = None


    def __init__(self):
        self._pool: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}
        self._by_code: dict[str, dict[str, Any]] = {}
        self._version: int = 0
        self.scanner = etf_scanner
        self.classifier = etf_classifier
        self.factor_registry = factor_registry
        self._opportunistic_signals: dict[str, dict] = {}
        self.current_regime: str = "neutral"
        # P0-13② (round16 3.14): 候选池冷却期/受限 refresh 时置 True，供设计链路消费
        self._degraded: bool = False
        # 外部缓存（由 scheduler 或 refresh() 更新）
        self._sector_momentum_cache: list[dict] | None = None
        self._sector_momentum_cache_ts: float = 0
        self._hot_plates_cache: list[dict] | None = None       # Phase 2: 热点板块
        self._sector_heat_cache: list[dict] | None = None      # Phase 2: 板块热度排行
        self._index_realtime_cache: list[dict] | None = None
        # S5: MarketDataHub K 线缓存（统一数据管道，R3: 单行式缓存 + 锁）
        self._kline_cache_rows: dict[str, list[dict]] = {}  # 行式: {symbol: [{date,open,...}]}
        self._kline_cache_ts: float = 0.0
        self._kline_cache_symbols: list[str] = []
        self._kline_cache_lock: asyncio.Lock = asyncio.Lock()  # R3: 单锁保护

        # R59③ (round28): K 线缓存持久化——重启后首呼 design 不再全量冷建库
        # （refresh_kline 42-75s，round28 §14.4 冷启动超时根因之一）。与
        # indices_cache.json / pool 快照同模式：24h 内磁盘缓存启动即加载复用；
        # 过期诚实重建（不复用过期数据）。加载失败静默（缓存缺失正常）。
        self._load_kline_cache_sync()

        # 兼容旧字段名（get_kline 仍可读）
        self._kline_cache: dict[str, dict[str, Any]] = {}
        # 60s TTL 缓存（Solution Design S1-A）
        self._cached_pool: dict | None = None
        self._cached_ts: float = 0.0
        self._cache_ttl: float = 60.0
        self._test_mode: bool = False  # #6: 测试模式下禁止 teardown HTTP 泄漏
        # 7.1: consecutive refresh failure counter for observability
        self._consecutive_failures: int = 0


    async def refresh(self) -> PoolDiff:
        """全量刷新候选池。

        有 TTL 缓存 + 冷却期 + 并发锁保护：
          - 60s TTL：缓存有效期内直接返回缓存（第二次点击 <1s）
          - 30s 冷却期：上次刷新距今 < 30s 时跳过刷新
          - 有正在运行的刷新则等待其完成，不启动第二个
        Returns:
            PoolDiff 差异报告。
        """
        import time as _time
        now = _time.time()
        # 60s TTL 缓存（S1-A）：缓存有效期内直接返回，不触发任何 I/O
        # 当 _last_refresh_ts 被置 0 时（测试强制刷新），TTL 也被跳过
        if self._cached_pool and (now - self._cached_ts) < self._cache_ttl:
            if getattr(self, '_last_refresh_ts', None):
                logger.debug("MarketDataHub: TTL cache hit (%.1fs old)", now - self._cached_ts)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
        # 30s 冷却期：上次刷新距今 < 30s 时跳过
        if hasattr(self, '_last_refresh_ts') and self._last_refresh_ts:
            if now - self._last_refresh_ts < 30:
                logger.info("MarketDataHub: refresh skipped (cooldown, %.1fs left)",
                            30 - (now - self._last_refresh_ts))
                return PoolDiff(changed=[], added=[], removed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
        import asyncio as _asyncio
        # 并发锁：已有刷新在进行中则等待（最长等 120s，防止死锁）
        if self._refresh_lock is not None and self._refresh_lock.locked():
            logger.info("MarketDataHub: refresh already in progress, waiting (max 120s)...")
            try:
                await _asyncio.wait_for(self._refresh_lock.acquire(), timeout=120)
                self._refresh_lock.release()
                logger.info("MarketDataHub: waited for lock, returning stale pool")
                return PoolDiff(changed=[], added=[], removed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
            except _asyncio.TimeoutError:
                logger.warning("MarketDataHub: lock wait timed out after 120s, creating new lock")
                self._refresh_lock = _asyncio.Lock()
        if self._refresh_lock is None:
            import asyncio as _asyncio
            self._refresh_lock = _asyncio.Lock()

        async with self._refresh_lock:
            self._last_refresh_ts = now
            try:
                diff = await self._refresh_impl()
                # 更新 TTL 缓存
                self._cached_pool = dict(self._pool)
                self._cached_ts = _time.time()
                return diff
            except Exception:
                self._last_refresh_ts = 0.0
                raise


    async def _refresh_impl(self) -> PoolDiff:
        """实际刷新逻辑（被 refresh() 的锁保护）。"""
        import time as _time
        import asyncio
        _start_ts = _time.time()
        old_by_code = dict(self._by_code)
        # 缓存上次成功刷新的 pool，供 refresh 失败时兜底
        _last_good = dict(self._pool) if self._pool and any(v for v in self._pool.values()) else None

        # 1. 扫描全市场 → 3 层基础池（走长任务线程池，不与 API 请求争抢）
        # R59① (round28): 采集并发化——K 线缓存预热（冷启动 42-75s 建库）与全市场扫描
        # 相互独立，串行执行使总耗时 = 两者之和（round28 §14.4：scanner 90s + kline 75s
        # 叠加吃光 DESIGN_DATA_TIMEOUT）。改为 asyncio.gather 并发：扫描跑线程池的同时
        # 后台预热 last-good 池的 K 线（扫描完成时缓存已就绪，factor compute 不再触发
        # 42-75s 冷建库）。单源失败立即降级（return_exceptions + 各自短超时）。
        try:
            from ..core.async_utils import run_sync_long, run_sync

            async def _scan_pipeline():
                return await asyncio.wait_for(
                    run_sync_long(self.scanner.full_pipeline, timeout=60),
                    timeout=90,
                )

            async def _warm_kline_concurrent():
                # 用 last-good 池 symbol 预热 K 线（与扫描无依赖）；无 last-good 或
                # 缓存已就绪则空转。短预算 45s（Semaphore(5)×20s 内部并发），超时
                # 静默（扫描完成后 factor compute 会按需补齐缺失标的）。
                try:
                    _known = list(self._by_code.keys())
                    if not _known:
                        # R59① fix: 冷启动/重启时扫描尚未完成，_by_code 为空——
                        # 回退到 last-good 池（_pool，重启后由 T-1 快照/前轮成功刷新
                        # 填充），否则预热线恒空转、冷建库仍打在 factor compute 上。
                        _last_pool = getattr(self, "_pool", None) or {}
                        if isinstance(_last_pool, dict):
                            for _lst in _last_pool.values():
                                if not isinstance(_lst, list):
                                    continue
                                _known.extend(
                                    str(it.get("symbol")) for it in _lst
                                    if it.get("symbol") not in ("CASH",)
                                )
                        _known = list(dict.fromkeys(_known))
                    if not _known:
                        return
                    await asyncio.wait_for(self.refresh_kline(_known[:40]), timeout=45)
                    logger.info("[pool] kline pre-warm finished concurrently (%d symbols, R59①)",
                                len(_known))
                except (Exception, asyncio.CancelledError) as _e:
                    logger.debug("[pool] kline pre-warm skipped/failed (non-fatal): %s", _e)

            # 并发执行：扫描（主） + K 线预热（副）——互不阻塞，各自短超时快速失败
            _scan_task = asyncio.create_task(_scan_pipeline())
            _kline_task = asyncio.create_task(_warm_kline_concurrent())
            _scan_result: Any
            _kline_result: Any
            _scan_result, _kline_result = await asyncio.gather(
                _scan_task, _kline_task, return_exceptions=True
            )
            raw_layers: dict[str, list[dict[str, Any]]]
            if isinstance(_scan_result, BaseException):
                raw_layers = {"core": [], "satellite": [], "defense": []}
                logger.warning(
                    "[market_data_hub] scanner.full_pipeline failed or timed out; raw_count=0, exception: %s",
                    _scan_result,
                )
            else:
                raw_layers = _scan_result
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning("[market_data_hub] scanner.full_pipeline failed or timed out")
            raw_layers = {"core": [], "satellite": [], "defense": []}
            logger.warning("[market_data_hub] scanner.full_pipeline returned empty — data source chain failed; raw_count=%d, exception: %s", 0, e)
        raw_count = sum(len(v) for v in raw_layers.values())
        logger.info("MarketDataHub: scanned %d ETFs (%d core, %d sat, %d def)",
                     raw_count,
                     len(raw_layers.get("core", [])),
                     len(raw_layers.get("satellite", [])),
                     len(raw_layers.get("defense", [])))

        # 2. 展平为列表做分类
        flat = []
        for layer_name, items in raw_layers.items():
            for item in items:
                flat.append({
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "amount": item.get("amount", 0),
                    "fund_scale": item.get("fund_scale", 0),
                    "fund_shares": item.get("fund_shares", 0),  # S2: 基金份额
                    "layer": layer_name,
                    "tracked_index": item.get("tracked_index", ""),
                })

        # 2.5 F10 tracked_index 补充（仅补充 scanner 未填充的项，使用本地缓存+渐进式请求）
        if flat:
            try:
                from ..fetchers.etf_scanner import enrich_tracked_indices as _enrich
                await run_sync(_enrich, flat)
            except Exception:
                logger.warning("[market_data_hub] F10 tracked_index enrichment failed", exc_info=True)

        # 2.6 round24 R1: 强板块动量注入候选池——避免强板块未进池、方案与市场热点脱节。
        # 读板块动量缓存（交易时段由 _refresh_market_snapshot 填充；盘后为空 → R26 快照兜底），
        # 取 TopN 经 SECTOR_ETF_MAP 映射代表 ETF 追加进 flat（hot_sector 标记 + composite_score 保底）。
        try:
            _sectors = self.get_sector_momentum()
            _existing = {f.get("symbol") for f in flat if f.get("symbol")}
            _injected = _strong_sector_etfs(_sectors, _existing, top_n=8)
            if _injected:
                flat.extend(_injected)
                logger.info("[pool] R1 injected %d strong-sector ETFs into candidate pool", len(_injected))
        except Exception as _e:
            logger.warning("[market_data_hub] R1 strong-sector injection failed: %s", _e)

        # 3. ETFClassifier 添加行业/概念
        if flat:
            class_results = await run_sync(self.classifier.batch_classify, flat)
            for item in flat:
                sym = item["symbol"]
                info = class_results.get(sym, {})
                item["industry"] = info.get("industry", "unknown")
                item["concepts"] = info.get("concepts", [])
                item["classify_confidence"] = info.get("confidence", 0.0)

        # 3a. Segment 字段注入（系统化去重的基石）
        if flat:
            from ..engine.allocation_engine import _extract_index_concept, _normalize_segment
            for item in flat:
                tidx = item.get("tracked_index", "") or ""
                name = item.get("name", "")
                concept = tidx or _extract_index_concept(name) or name
                item["segment"] = _normalize_segment(concept) or concept

        # 3b. FactorRegistry 计算因子得分（传入 fund_scale 以支持 valuation 因子）
        if flat:
            symbols = [e["symbol"] for e in flat if e.get("symbol")]
            symbol_extra = {e["symbol"]: {
                "fund_scale": e.get("fund_scale", 0),
                "fund_shares": e.get("fund_shares", 0),  # S2: 基金份额
                # F19: inject industry so china_specific factors
                # (five_year_plan / strategic_emerging / dual_circulation)
                # receive real classification instead of empty string.
                "industry": e.get("industry", "unknown"),
                "concepts": e.get("concepts", []),
            } for e in flat if e.get("symbol")}
            try:
                # F3-4 步骤B/C: 注入 benchmark_close（宽基）+ shares_change_20d（份额）
                symbol_extra = await self._enrich_symbol_extra(symbols, symbol_extra)
            except Exception as e:
                logger.warning("[hub] symbol_extra enrich failed (non-fatal): %s", e)
            try:
                # S5: 使用缓存 K 线作为 market_data（R3: 从行式缓存懒转换）
                cached_kline = self._kline_cache if self._kline_cache_ts > 0 else None
                factor_scores = await self.factor_registry.compute(
                    symbols, symbol_extra=symbol_extra,
                    market_data=cached_kline,
                )
                # 如果 compute 返回空数据（缓存过期），刷新后重试
                if not any(factor_scores.get(s) for s in symbols[:5]):
                    await self.refresh_kline(symbols)
                    factor_scores = await self.factor_registry.compute(
                        symbols, symbol_extra=symbol_extra,
                        market_data=self._kline_cache,
                    )
                for item in flat:
                    sym = item["symbol"]
                    raw_scores = factor_scores.get(sym, {})
                    # B1: 聚合点分键为顶层分类键
                    # round15 方案一/三: 传 definitions（yaml 方向单一来源）+ IC 序列缓存
                    item["factor_scores"] = self.factor_registry.aggregate_factor_scores(
                        raw_scores,
                        definitions=self.factor_registry._factors,
                        ic_series=getattr(self.factor_registry, "_ic_series_cache", None),
                    )
            except Exception as e:
                logger.exception("FactorRegistry compute failed: %s", e)
                for item in flat:
                    item["factor_scores"] = {}

        # 3c. 注入新闻情感因子到 factor_scores（已有的 sentiment 因子依赖外部数据）
        if flat:
            news_items = self._news_cache or []
            if not news_items:
                # 新闻缓存为空时主动刷新一次（确保设计请求首次就有情感数据）
                try:
                    from ..core.async_utils import run_sync
                    await run_sync(self.refresh_news)
                    news_items = self._news_cache or []
                except Exception:
                    pass
            if news_items:
                total_news = len(news_items)
                # 新闻热度：过去 120s 内的加权星数
                news_heat_raw = sum(float(n.get("stars", 0) or 0) for n in news_items)
                # 新闻方向：利好占比
                positive_count = sum(1 for n in news_items if n.get("level") in ("利好", "重大"))
                news_dir = positive_count / max(total_news, 1)
                # 归一化热度（基线 50 条 = 1.0）
                heat_normalized = min(news_heat_raw / 50.0, 5.0)
                for item in flat:
                    fs = item.get("factor_scores", {})
                    if fs is not None:
                        fs["sentiment.news_heat"] = heat_normalized
                        fs["sentiment.news_direction"] = news_dir
                        # panic_greed_diff 用新闻方向代理 sentiment_index
                        fs["sentiment.panic_greed_diff"] = (news_dir - 0.5) * 2

        # 4. 分配到 5 层（含 opportunistic 信号注入）
        new_pool: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}

        # 4a. 注入 opportunistic 信号
        if self._opportunistic_signals:
            for sym, signal in self._opportunistic_signals.items():
                new_pool[LAYER_OPPORTUNISTIC].append({
                    "symbol": sym,
                    "name": signal.get("name", sym),
                    "layer": LAYER_OPPORTUNISTIC,
                    "industry": signal.get("industry", "unknown"),
                    "concepts": signal.get("concepts", []),
                    "factor_scores": {},
                    "composite_score": signal.get("heat_score", 0.5),
                    "opp_signal": signal.get("signal", ""),
                    "opp_reason": signal.get("reason", ""),
                })

        for item in flat:
            item["layer"] = self._assign_layer(
                item.get("layer", LAYER_SATELLITE),
                item.get("industry", "unknown"),
            )
            item["composite_score"] = 0.0
            new_pool[item["layer"]].append(item)

        # 4c. B2: 同层同指数去重（依赖 tracked_index 字段）
        new_pool = self._deduplicate_by_index(new_pool)

        # 5. 强制保底
        self._ensure_mandatory(new_pool, flat)

        # 6. 层内复合评分 + 行业均衡化 + 截断
        for layer in ALL_LAYERS:
            layer_items = new_pool[layer]
            # round15 方案二: core/satellite/defense 层内先收集截面向量（amount/scale），
            # 供 _compute_composite 的 _pct_rank 使用（量纲统一，消除 *1e-9 魔法数）
            layer_amounts: list[float] | None = None
            layer_scales: list[float] | None = None
            if layer in ("core", "satellite", "defense") and layer_items:
                layer_amounts = [float(it.get("amount", 0) or 0) for it in layer_items]
                layer_scales = [float(it.get("fund_scale", 0) or 0) for it in layer_items]
            for item in layer_items:
                item["composite_score"] = self._compute_composite(
                    item, layer, regime=self.current_regime,
                    layer_amounts=layer_amounts, layer_scales=layer_scales,
                )
            max_n = MAX_PER_LAYER.get(layer, 10)
            # P4 fix-plan-pool: 行业均衡化后再截断
            balanced = self._balance_by_industry(new_pool[layer], max_n=max_n)
            # R5-0-1: 截断时保护强制标的——截断前剔除 MANDATORY_CODES，截断后再补回
            #（P1-1 A500 缺失根因：_ensure_mandatory 在截断前执行，截断把 560600 挤出后无二次校验）
            new_pool[layer] = self._truncate_with_mandatory_protection(balanced, max_n=max_n)

        # 6b. R5-0-1: 截断后强制标的二次校验（对齐 etf_scanner._log_missing_required 口径）
        # 失败仅 WARNING + 从 flat 找回注入，不抛异常；与 _ensure_mandatory 语义一致。
        self._recheck_mandatory_after_truncate(new_pool, flat)

        # 7. 空池保护：如果刷新结果为空且存在上次成功数据，保留上次 pool 而非清空
        total_new = sum(len(v) for v in new_pool.values())
        _last_good_total = sum(len(v) for v in _last_good.values()) if _last_good else 0
        # P0-13① (round16 3.14 R1): 冷却期 last-good 保护扩展——refresh 产出显著
        # 低于上次成功 pool（<50%）且上次非空时，保留 last-good 而非覆盖，
        # 避免「候选池昙花一现」依赖数据源冷却状态（mootdx/akshare 冷却时受限产出）。
        _shrink_protected = bool(
            _last_good is not None
            and _last_good_total > 0
            and total_new > 0
            and total_new < _last_good_total * 0.5
        )
        if total_new == 0 or _shrink_protected:
            if _last_good is not None:
                logger.warning(
                    "[market_data_hub] refresh produced %s pool (%d total vs last-good %d) — keeping last good pool (v%d, %d total)%s",
                    "empty" if total_new == 0 else "severely-shrunk",
                    total_new, _last_good_total, self._version,
                    _last_good_total, " [P0-13 degrade]" if _shrink_protected else "",
                )
                # P0-13②: 冷却期/受限 refresh 打 degraded 标记供设计降级链路消费
                self._degraded = True
                # 不改变 self._pool 和 self._version，返回一个空 diff
                _elapsed = _time.time() - _start_ts
                pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                 timestamp=datetime.now().isoformat()))
                logger.info("MarketDataHub: refresh skipped (%s) in %.1fs",
                            "empty" if total_new == 0 else "shrunk<50%", _elapsed)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
            else:
                # 7.1: 首次刷新生效 — 无 last-good 内存可回退 → 尝试盘后 T-1 快照兜底
                # （round24 R26：last-good 内存重启即丢，盘后重启必须能读 T-1 快照）。
                _snap_pool = self._load_pool_snapshot()
                if _snap_pool:
                    self._pool = _snap_pool
                    self._rebuild_index()
                    self._degraded = True
                    self._consecutive_failures = 0
                    _elapsed = _time.time() - _start_ts
                    logger.warning(
                        "MarketDataHub: first-run refresh empty — loaded T-1 snapshot pool (%d total) as fallback",
                        sum(len(v) for v in _snap_pool.values()),
                    )
                    pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                     timestamp=datetime.now().isoformat()))
                    return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                    timestamp=datetime.now().isoformat())
                self._consecutive_failures += 1
                logger.critical(
                    "[market_data_hub] FIRST-RUN refresh produced empty pool — "
                    "data sources unavailable or timed out. "
                    "consecutive_failures=%d. Pool will remain empty until a successful refresh.",
                    self._consecutive_failures
                )
                # Don't overwrite self._pool (already empty), just return empty diff
                _elapsed = _time.time() - _start_ts
                pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                 timestamp=datetime.now().isoformat()))
                logger.info("MarketDataHub: first-run refresh failed in %.1fs (no fallback available)", _elapsed)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())

        # 7b. 重建索引
        self._pool = new_pool
        self._rebuild_index()
        self._version += 1
        # 7.1: 重置连续失败计数（本次刷新成功）
        self._consecutive_failures = 0
        # P0-13②: 本次刷新成功 → 清除 cooling 降级标记
        self._degraded = False
        # round24 R26②: 刷新成功（盘后/熔断也会成功写 last-good）→ 落盘快照，
        # 使「盘后重启」能读 T-1 快照兜底（last-good 内存重启即丢）。
        await self._persist_snapshot_after_refresh(new_pool)

        # 8. 计算 diff
        diff = self._compute_diff(old_by_code)
        diff.version = self._version
        diff.timestamp = datetime.now().isoformat()

        # 9. 审计日志
        pool_audit.log_refresh(diff)

        # 9b. A3: 写入市场快照缓存（fire-and-forget 不阻塞主流程）
        import asyncio as _asyncio2
        _asyncio2.create_task(self._refresh_market_snapshot())

        _elapsed = _time.time() - _start_ts
        logger.info("MarketDataHub: refresh complete (v%d, %d total) in %.1fs",
                     self._version,
                     sum(len(v) for v in self._pool.values()),
                     _elapsed)
        return diff


    def set_opportunistic_signals(self, signals: dict[str, dict]) -> None:
        """设置外部机会信号（用于 Layer 4）。

        Args:
            signals: {symbol: {"signal": str, "heat_score": float, ...}}
        """
        self._opportunistic_signals = signals
        logger.info("MarketDataHub: set %d opportunistic signals", len(signals))


    async def update_sector_cache(self) -> None:
        """刷新行业+概念板块动量缓存（Phase 2 新增，60s 定时任务专用）。

        与 _refresh_market_snapshot 中的 sector 刷新分离，独立定时刷新。
        同时刷新热点板块和板块热度排行。
        """
        import asyncio
        import time
        from .market_trends import compute_sector_momentum

        try:
            # 1. 行业+概念动量
            momentum = await asyncio.wait_for(compute_sector_momentum(top_n=30), timeout=15)
            if momentum:
                self._sector_momentum_cache = momentum
                self._sector_momentum_cache_ts = time.time()
                logger.info("[pool] update_sector_cache: %d momentum rows", len(momentum))

            # 2. 热点板块（异步，失败不影响主流程）
            try:
                from ..fetchers.sector_fetcher import fetch_hot_plates
                from ..core.async_utils import run_sync
                hot = await run_sync(fetch_hot_plates, 15, timeout=20)
                if hot:
                    self._hot_plates_cache = hot
                    logger.info("[pool] update_sector_cache: %d hot plates", len(hot))
            except Exception as e:
                logger.debug("[pool] update_sector_cache hot_plates skipped: %s", e)

            # 3. 板块热度排行
            try:
                from ..fetchers.sector_fetcher import fetch_sector_heat
                from ..core.async_utils import run_sync
                heat = await run_sync(fetch_sector_heat, timeout=20)
                if heat:
                    self._sector_heat_cache = heat
            except Exception as e:
                logger.debug("[pool] update_sector_cache sector_heat skipped: %s", e)

        except Exception as e:
            logger.warning("[pool] update_sector_cache failed: %s", e)


    async def _refresh_market_snapshot(self) -> None:
        """A3: 写入市场快照缓存（指数 + 板块动量）。

        调用外部 API 刷新 _index_realtime_cache 和 _sector_momentum_cache，
        供 LLM 报告等消费方使用。
        """
        import asyncio
        import time
        async def _fetch_indices():
            try:
                from ..services.market_service import get_global_indices
                indices = await asyncio.wait_for(get_global_indices(), timeout=15)
                flat = []
                for region, items in indices.items():
                    for item in items:
                        item["region"] = region
                        flat.append(item)
                # F8 (round6 §14.5): 指数实时多源降级——get_global_indices 空时
                # 用东财 push2delay 直连拉 A 股主要指数兜底，使设计报告"今日涨跌"
                # 列不再全"数据源不可用"（东财 push2 限流 RemoteDisconnected 场景）。
                if not flat:
                    flat = self._fetch_a_index_rows()
                    for item in flat:
                        item["region"] = "A"
                self._index_realtime_cache = flat
                logger.info("[pool] refreshed %d index realtime entries", len(flat))
            except Exception as e:
                logger.warning("[pool] _refresh_market_snapshot indices failed: %s", e)
                if self._index_realtime_cache is None:
                    self._index_realtime_cache = []

        async def _fetch_sector():
            try:
                from ..services.market_trends import compute_sector_momentum
                sector_data = await asyncio.wait_for(compute_sector_momentum(top_n=10), timeout=15)
                self._sector_momentum_cache = sector_data
                self._sector_momentum_cache_ts = time.time()
                logger.info("[pool] refreshed %d sector momentum entries", len(sector_data))
            except Exception as e:
                logger.warning("[pool] _refresh_market_snapshot sector failed: %s", e)
                if self._sector_momentum_cache is None:
                    self._sector_momentum_cache = []

        # 并发获取指数行情和板块动量（FIX-04）
        await asyncio.gather(_fetch_indices(), _fetch_sector())


    async def _refresh_market_snapshot_indices_only(self) -> None:
        """仅刷新指数缓存（F8 单测入口，逻辑与 _fetch_indices 一致）。"""
        import asyncio
        try:
            from ..services.market_service import get_global_indices
            indices = await asyncio.wait_for(get_global_indices(), timeout=15)
            flat = []
            for region, items in indices.items():
                for item in items:
                    item["region"] = region
                    flat.append(item)
            if not flat:
                flat = self._fetch_a_index_rows()
                for item in flat:
                    item["region"] = "A"
            self._index_realtime_cache = flat
            logger.info("[pool] refreshed %d index realtime entries", len(flat))
        except Exception as e:
            logger.warning("[pool] indices refresh failed: %s", e)
            if self._index_realtime_cache is None:
                self._index_realtime_cache = []


    def _fetch_a_index_rows(self) -> list[dict]:
        """F8: 东财 push2delay 直连拉 A 股主要指数（沪深300/上证50/中证500/科创50/创业板）。

        get_global_indices 空（东财 push2 限流）时的兜底源。push2delay 实测稳定。
        """
        from ..core.market_context import EM_PUSH_HOST
        from ..utils.proxy import no_proxy
        import requests as _req
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        fields = "f12,f14,f2,f3,f6"
        # m:1+s:2=上证指数段, m:0+s:399=深证段（含创业板指）；一次拉取主要宽基
        try:
            with no_proxy():
                r = _req.get(
                    "http://%s/api/qt/clist/get"
                    "?pn=1&pz=100&po=1&np=1&fs=m:1+s:2,m:0+s:399&fields=%s&fid=f6" % (EM_PUSH_HOST, fields),
                    timeout=6, headers=headers,
                )
            rows = (r.json().get("data") or {}).get("diff") or []
            out = []
            for row in rows:
                code = row.get("f12", "")
                name = row.get("f14", "")
                if not code or not name:
                    continue
                def _num(v: Any) -> float:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return 0.0
                out.append({
                    "symbol": f"{'sh' if code.startswith('0') or code.startswith('1') else 'sz'}{code}",
                    "code": code,
                    "name": name,
                    "price": _num(row.get("f2")),
                    "change_pct": _num(row.get("f3")),
                    "amount": _num(row.get("f6")),
                })
            logger.info("[pool] F8 fallback: fetched %d A-share indices via push2delay", len(out))
            return out
        except Exception as e:
            logger.warning("[pool] F8 fallback index fetch failed: %s", e)
            return []


    def _assign_layer(self, base_layer: str, industry: str) -> str:
        """行业→层映射（P1-2 防御层分类修复，R5 pool 归层）。

        从 _refresh_impl 提取的纯函数，供单测直测（消除测试复制实现）：
        - core（宽基指数）→ LAYER_CORE
        - defense（商品/固收）→ LAYER_DEFENSE（跨境不落防御，P1-2）
        - 跨境 → LAYER_SATELLITE
        - unknown → LAYER_RESEARCH
        - 其余 → LAYER_SATELLITE
        """
        base_layer = base_layer or LAYER_SATELLITE
        industry = industry or "unknown"
        # Core: 宽基指数
        if base_layer == "core" or industry == "宽基指数":
            return LAYER_CORE
        # Defense: 商品/固收（注意：跨境归卫星层，P1-2 修复）
        if base_layer == "defense" or industry in ("商品", "固收"):
            return LAYER_DEFENSE
        # 跨境 → 卫星层（非防御资产）
        if industry == "跨境":
            return LAYER_SATELLITE
        # Research: unknown industry
        if industry == "unknown":
            return LAYER_RESEARCH
        return LAYER_SATELLITE


    @staticmethod
    def _normalize_tracked_index(tidx: str) -> str:
        """M3: tracked_index 家族归一化——同一指数的风格/增强切片合并为基准指数。

        中证500价值/成长/增强 与 中证500 高度相关（同一指数的不同切片），
        精确字符串去重把它们当 3 个独立指数 → 家族霸榜。此处归一化后只保留
        fund_scale 最大者（复用 _deduplicate_by_index 的既有保留逻辑）。

        Examples:
            "中证500价值" → "中证500"
            "中证500成长" → "中证500"
            "中证500增强" → "中证500"
            "沪深300增强" → "沪深300"
            "沪深300价值" → "沪深300"
        """
        if not tidx:
            return tidx
        for base in ("中证500", "沪深300"):
            if tidx.startswith(base) and tidx != base:
                return base
        return tidx


    @staticmethod
    def _deduplicate_by_index(
        pool: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """B2: 候选池去重——同层同 tracked_index 的 ETF 只保留 fund_scale 最大的。

        当 tracked_index 为空时（Sina 源无此字段），使用名称推断去重（ETF + 联接C 合并）。
        """
        # 名称中常见的"联接"类后缀
        _LINK_FUND_SUFFIXES = ("联接", "联", "LOF", "C")

        def _extract_index_concept(name: str) -> str:
            """从 ETF 名提取指数概念（去除基金公司名和联接/ETF 后缀）。"""
            # 去除基金公司名
            _COMPANY_NAMES = [
                "华夏", "易方达", "汇添富", "嘉实", "富国", "招商", "博时", "南方",
                "广发", "华安", "国泰", "鹏华", "天弘", "工银", "建信", "中欧",
                "景顺", "长城", "泰康", "海富通", "光大", "兴全", "东证", "华宝",
                "银华", "大成", "长信", "国联", "申万", "上投", "中信", "华泰",
                "万家", "兴业", "民生", "浦银", "方正", "太平", "前海", "创金",
                "银河", "诺安", "交银", "融通", "泓德", "中加", "永赢", "西部",
                "浙商", "新华", "红土", "安信", "国寿", "英大", "汇丰", "恒生",
                "中银", "国投", "德邦", "华富", "金元", "国金", "九泰", "东方",
                "中泰", "湘财", "国融", "江信", "蜂巢", "东海", "中邮", "华融",
                "金鹰", "长城", "同泰", "红塔", "华润", "格林", "瑞达", "明亚",
                "惠升", "华宸", "富荣", "易米", "长江", "渤海",
            ]
            for company in sorted(_COMPANY_NAMES, key=len, reverse=True):
                name = name.replace(company, "")
            # 去除常见后缀
            for suffix in ("ETF", "联接", "联", "LOF"):
                name = name.replace(suffix, "")
            return name.strip()

        result: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}
        for layer, items in pool.items():
            seen_indices: dict[str, dict[str, Any]] = {}
            # 记录已按名称去重的 code，避免 name-based 重复
            name_seen: dict[str, dict[str, Any]] = {}
            for item in items:
                tidx = item.get("tracked_index", "") or ""
                if tidx:
                    # M3: 先做家族归一化再精确去重（中证500价值/成长/增强 → 中证500）
                    tidx = MarketDataHub._normalize_tracked_index(tidx)
                    item["tracked_index"] = tidx
                    # tracked_index 精确去重
                    existing = seen_indices.get(tidx)
                    if existing is None:
                        seen_indices[tidx] = item
                    else:
                        existing_scale = float(existing.get("fund_scale", 0) or 0)
                        new_scale = float(item.get("fund_scale", 0) or 0)
                        if new_scale > existing_scale:
                            seen_indices[tidx] = item
                else:
                    # 无 tracked_index → 按名称推断的概念去重（联接C 合并）
                    raw_name = item.get("name", item.get("symbol", ""))
                    concept = _extract_index_concept(raw_name)
                    if not concept:
                        # 完全无法推断概念，直接保留
                        result[layer].append(item)
                        continue
                    existing = name_seen.get(concept)
                    if existing is None:
                        name_seen[concept] = item
                    else:
                        existing_scale = float(existing.get("fund_scale", 0) or 0)
                        new_scale = float(item.get("fund_scale", 0) or 0)
                        # 没有联接后缀的优先（即 ETF 优先于联接C）
                        existing_is_etf = not any(s in existing.get("name", "") for s in _LINK_FUND_SUFFIXES)
                        new_is_etf = not any(s in item.get("name", "") for s in _LINK_FUND_SUFFIXES)
                        if new_is_etf and not existing_is_etf:
                            name_seen[concept] = item
                        elif existing_is_etf and not new_is_etf:
                            pass  # keep existing
                        elif new_scale > existing_scale:
                            name_seen[concept] = item

            # 合并：tracked_index 精确去重 + name-based 去重
            result[layer].extend(seen_indices.values())
            # name_seen 中那些没有 tracked_index 的也要加入
            for concept, item in name_seen.items():
                code = item.get("symbol", item.get("code", ""))
                # 检查是否已经被 tracked_index 去重包含了
                already_in = any(
                    e.get("symbol") == code or e.get("code") == code
                    for e in result[layer]
                )
                if not already_in:
                    result[layer].append(item)

        return result


    def _ensure_mandatory(
        self,
        pool: dict[str, list[dict[str, Any]]],
        flat: list[dict[str, Any]],
    ) -> None:
        """确保 MANDATORY_CODES 在池中（如果全市场扫描有结果）。"""
        if not flat:
            return  # 扫描失败，不强行注入（直接报错）
        for code in MANDATORY_CODES:
            in_pool = any(
                e["symbol"] == code for layer in pool.values() for e in layer
            )
            if not in_pool:
                # 从 flat 中找回
                found = next((e for e in flat if e["symbol"] == code), None)
                if found:
                    # 按代码推断层
                    # round9 P0-8: 定层分支 560600 → 159338（真实中证A500ETF 归核心层）
                    if code in ("510300", "159338"):
                        target = LAYER_CORE
                    elif code in ("518880",):
                        target = LAYER_DEFENSE
                    elif code == "511090":
                        target = LAYER_DEFENSE
                    else:
                        target = LAYER_SATELLITE
                    found["layer"] = target
                    pool[target].append(found)
                    logger.info("MarketDataHub: enforced mandatory %s -> %s", code, target)


    @staticmethod
    def _truncate_with_mandatory_protection(
        balanced: list[dict[str, Any]], max_n: int
    ) -> list[dict[str, Any]]:
        """R5-0-1: MAX_PER_LAYER 截断时保护强制标的。

        截断前剔除 MANDATORY_CODES，截断后再补回——避免强制标的（510300/159338
        等）因排名靠后被行业均衡/截断挤出（P1-1 A500 缺失根因之一）。
        """
        mandatory = [e for e in balanced if e.get("symbol") in MANDATORY_CODES]
        rest = [e for e in balanced if e.get("symbol") not in MANDATORY_CODES]
        return mandatory + rest[:max_n]


    def _recheck_mandatory_after_truncate(
        self,
        pool: dict[str, list[dict[str, Any]]],
        flat: list[dict[str, Any]],
    ) -> None:
        """R5-0-1: 截断后强制标的二次校验。

        对齐 etf_scanner._log_missing_required 口径：截断后再次校验
        MANDATORY_CODES ∪ CORE_REQUIRED 是否在池中，缺失时从 flat 找回注入。
        失败仅 WARNING + 注入，不抛异常；revert 只需删除步骤 6b 的调用。
        """
        if not flat:
            return  # 扫描失败，不强行注入（与 _ensure_mandatory 语义一致）
        required = MANDATORY_CODES | set(getattr(etf_scanner, "CORE_REQUIRED", []))
        for code in sorted(required):
            in_pool = any(
                e["symbol"] == code for layer in pool.values() for e in layer
            )
            if in_pool:
                continue
            found = next((e for e in flat if e.get("symbol") == code), None)
            if not found:
                continue
            # 与 _ensure_mandatory 相同的定层逻辑
            if code in ("510300", "159338"):
                target = LAYER_CORE
            elif code in ("518880", "511090"):
                target = LAYER_DEFENSE
            else:
                target = LAYER_SATELLITE
            found["layer"] = target
            pool.setdefault(target, []).append(found)
            logger.warning("MarketDataHub: re-injected mandatory %s -> %s after truncate", code, target)


    @staticmethod
    def _pct_rank(value: float, series: list[float]) -> float:
        """层内截面百分位 [0,1]（含并列按半计）。

        round15 方案二: 对绝对量级不敏感——同列同单位即可（amount 万元/元、
        fund_scale 亿/元混用时百分位仍可比），彻底消除 composite 的量纲魔法数。
        """
        if not series:
            return 0.0
        n = len(series)
        below = sum(1 for v in series if v < value)
        equal = sum(1 for v in series if v == value)
        return (below + 0.5 * equal) / n


    def _compute_composite(
        self,
        item: dict[str, Any],
        layer: str,
        regime: str = "neutral",
        layer_amounts: list[float] | None = None,
        layer_scales: list[float] | None = None,
    ) -> float:
        """按层+市况计算综合得分。

        非交易时段（P6 fix-plan-pool）: 流动性数据可能为昨日值，
        降低流动性权重，以规模排序为主。

        round15 方案二（docs §5.2）: 分量统一量纲——core/satellite/defense 三层
        传层内截面向量（layer_amounts/layer_scales）时用：
            factor 项 = w.factor × tanh(factor_sum/6)      [-1,1]（防极端 z 支配）
            liquidity = w.liquidity × _pct_rank(amount)    [0,1]
            scale     = w.scale × _pct_rank(fund_scale)    [0,1]
        向后兼容：layer_amounts=None 时回退旧 `*1e-9` 路径（research/opportunistic
        与外部直接调用行为不变）。
        """
        factor_scores = item.get("factor_scores", {})
        # P0-4: 仅聚合顶层键求和（避免原始点分键双倍计数 + RSI=50 主导排序）
        AGGREGATE_KEYS = {"technical", "momentum", "valuation", "sentiment"}
        factor_sum = sum(v for k, v in factor_scores.items() if k in AGGREGATE_KEYS) if factor_scores else 0
        amount = float(item.get("amount", 0) or 0)
        scale = float(item.get("fund_scale", 0) or 0)
        opp_score = float(item.get("composite_score", 0.5))

        layer_weights = _LAYER_WEIGHTS.get(layer, {})
        regime_key = self._normalize_regime(regime)
        w = layer_weights.get(regime_key, layer_weights.get("neutral", _BASE_WEIGHTS))

        # P6: 非交易时段，流动性权重减半（数据可能为昨日值）
        is_market_open = self._is_market_hours()
        liquidity_weight = w.get("liquidity", 0)
        if not is_market_open:
            liquidity_weight *= 0.5
            scale_weight = w.get("scale", 0) + w.get("liquidity", 0) * 0.5
        else:
            scale_weight = w.get("scale", 0)

        if layer in ("core", "satellite", "defense", "opportunistic"):
            # round15 方案二: 层内百分位量纲（仅 core/satellite/defense 三层启用）
            if layer in ("core", "satellite", "defense") and layer_amounts is not None:
                import math as _math
                score = w["factor"] * _math.tanh(factor_sum / 6.0)
                score += liquidity_weight * self._pct_rank(amount, layer_amounts)
                score += scale_weight * self._pct_rank(scale, layer_scales or [])
            else:
                score = w["factor"] * factor_sum
                score += liquidity_weight * amount * 1e-9
                score += scale_weight * scale * 1e-9
            if layer != "core":
                score += w.get("opp", 0) * opp_score
        else:
            score = amount * 1e-9  # research: liquidity only

        return score


    @staticmethod
    def _balance_by_industry(
        items: list[dict[str, Any]],
        max_n: int = 10,
    ) -> list[dict[str, Any]]:
        """P4 fix-plan-pool: 按行业/segment 均衡化候选池。

        确保同一层内覆盖多个行业，避免某行业一家独大。
        策略：
          1. 按 segment 分组
          2. 每个 segment 取 composite_score 最高的 1 只
          3. 若还有余量，从剩余高分中补齐
        """
        if not items:
            return []
        if len(items) <= max_n:
            return items

        from collections import defaultdict
        # 按 segment 分组
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            seg = item.get("segment", "") or item.get("industry", "unknown")
            groups[seg].append(item)

        # 每个 segment 排序，取 top 1
        selected: list[dict] = []
        selected_codes: set[str] = set()
        for seg, group in groups.items():
            group_sorted = sorted(group, key=lambda x: x.get("composite_score", 0), reverse=True)
            top = group_sorted[0]
            selected.append(top)
            selected_codes.add(top.get("symbol", ""))

        # 如果还不够，从剩余中按得分补齐
        if len(selected) < max_n:
            remaining = []
            for item in items:
                if item.get("symbol", "") not in selected_codes:
                    remaining.append(item)
            remaining.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
            selected.extend(remaining[:max_n - len(selected)])

        return selected[:max_n]


# Global singleton
market_data_hub = MarketDataHub()
