"""
PoolManager: unified candidate pool management for the ETF Surge system.

Replaces the hardcoded CANDIDATE_POOL with a dynamic, 5-layer pool
backed by etf_scanner, ETFClassifier, and FactorRegistry.

Lifecycle:
  1. refresh() called daily (or on-demand)
  2. Scanner fetches all ETFs → filters → ranks into 3 base layers
  3. ETFClassifier adds industry/concept metadata
  4. PoolManager assigns 5 layers (core/satellite/defense/opportunistic/research)
  5. MANDATORY_CODES enforced
  6. PoolDiff generated for audit trail
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from ..fetchers import etf_scanner
from ..factors.factor_registry import registry as factor_registry
from .etf_classifier import classifier as etf_classifier
from .pool_audit import pool_audit

logger = logging.getLogger(__name__)

# 强制保留标的（池刷新时永不出池）
MANDATORY_CODES = {"510300", "560600", "518880", "511090"}

# 层名
LAYER_CORE = "core"
LAYER_SATELLITE = "satellite"
LAYER_DEFENSE = "defense"
LAYER_OPPORTUNISTIC = "opportunistic"
LAYER_RESEARCH = "research"
ALL_LAYERS = [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE, LAYER_OPPORTUNISTIC, LAYER_RESEARCH]

# Regime-based weights for each layer
_LAYER_WEIGHTS = {
    "satellite": {
        "bull":       {"factor": 0.55, "liquidity": 0.10, "scale": 0.05, "opp": 0.30},
        "bear":       {"factor": 0.25, "liquidity": 0.10, "scale": 0.05, "opp": 0.60},
        "correction": {"factor": 0.35, "liquidity": 0.15, "scale": 0.10, "opp": 0.40},
        "neutral":    {"factor": 0.40, "liquidity": 0.15, "scale": 0.10, "opp": 0.35},
    },
    "core": {
        "bull":       {"factor": 0.55, "liquidity": 0.20, "scale": 0.25},
        "bear":       {"factor": 0.40, "liquidity": 0.30, "scale": 0.30},
        "correction": {"factor": 0.45, "liquidity": 0.25, "scale": 0.30},
        "neutral":    {"factor": 0.50, "liquidity": 0.25, "scale": 0.25},
    },
    "defense": {
        "bull":       {"factor": 0.35, "liquidity": 0.25, "scale": 0.15, "opp": 0.25},
        "bear":       {"factor": 0.25, "liquidity": 0.20, "scale": 0.15, "opp": 0.40},
        "correction": {"factor": 0.30, "liquidity": 0.25, "scale": 0.20, "opp": 0.25},
        "neutral":    {"factor": 0.30, "liquidity": 0.20, "scale": 0.20, "opp": 0.30},
    },
}
_BASE_WEIGHTS = {"factor": 0.40, "liquidity": 0.15, "scale": 0.10, "opp": 0.35}

# 层内最大数量
MAX_PER_LAYER = {
    LAYER_CORE: 8,
    LAYER_SATELLITE: 20,
    LAYER_DEFENSE: 10,
    LAYER_OPPORTUNISTIC: 8,
    LAYER_RESEARCH: 10,
}


@dataclass
class PoolDiff:
    """差异报告：跟踪两次 refresh 之间的变化。"""

    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    timestamp: str = ""


class PoolManager:
    """候选池管理器。

    Usage:
        pm = PoolManager()
        await pm.refresh()           # 日频刷新
        pool = pm.get_pool()         # 获取全池
        entry = pm.get_by_code("510300")  # 按 code 查询
    """

    # Dynamic attributes set via setattr/hasattr in _refresh — declare here for mypy
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
        # 外部缓存（由 scheduler 或 refresh() 更新）
        self._sector_momentum_cache: list[dict] | None = None
        self._sector_momentum_cache_ts: float = 0
        self._hot_plates_cache: list[dict] | None = None       # Phase 2: 热点板块
        self._sector_heat_cache: list[dict] | None = None      # Phase 2: 板块热度排行
        self._index_realtime_cache: list[dict] | None = None
        # 60s TTL 缓存（Solution Design S1-A）
        self._cached_pool: dict | None = None
        self._cached_ts: float = 0.0
        self._cache_ttl: float = 60.0
        self._test_mode: bool = False  # #6: 测试模式下禁止 teardown HTTP 泄漏
        # 7.1: consecutive refresh failure counter for observability
        self._consecutive_failures: int = 0

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
                logger.debug("PoolManager: TTL cache hit (%.1fs old)", now - self._cached_ts)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
        # 30s 冷却期：上次刷新距今 < 30s 时跳过
        if hasattr(self, '_last_refresh_ts') and self._last_refresh_ts:
            if now - self._last_refresh_ts < 30:
                logger.info("PoolManager: refresh skipped (cooldown, %.1fs left)",
                            30 - (now - self._last_refresh_ts))
                return PoolDiff(changed=[], added=[], removed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
        import asyncio as _asyncio
        # 并发锁：已有刷新在进行中则等待（最长等 120s，防止死锁）
        if self._refresh_lock is not None and self._refresh_lock.locked():
            logger.info("PoolManager: refresh already in progress, waiting (max 120s)...")
            try:
                await _asyncio.wait_for(self._refresh_lock.acquire(), timeout=120)
                self._refresh_lock.release()
                logger.info("PoolManager: waited for lock, returning stale pool")
                return PoolDiff(changed=[], added=[], removed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
            except _asyncio.TimeoutError:
                logger.warning("PoolManager: lock wait timed out after 120s, creating new lock")
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
        try:
            from ..core.async_utils import run_sync_long, run_sync
            raw_layers = await asyncio.wait_for(
                run_sync_long(self.scanner.full_pipeline, timeout=60),
                timeout=90,
            )
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning("[pool_manager] scanner.full_pipeline failed or timed out")
            raw_layers = {"core": [], "satellite": [], "defense": []}
            logger.warning("[pool_manager] scanner.full_pipeline returned empty — data source chain failed; raw_count=%d, exception: %s", 0, e)
        raw_count = sum(len(v) for v in raw_layers.values())
        logger.info("PoolManager: scanned %d ETFs (%d core, %d sat, %d def)",
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
                    "layer": layer_name,
                    "tracked_index": item.get("tracked_index", ""),
                })

        # 2.5 F10 tracked_index 补充（仅补充 scanner 未填充的项，使用本地缓存+渐进式请求）
        if flat:
            try:
                from ..fetchers.etf_scanner import enrich_tracked_indices as _enrich
                await run_sync(_enrich, flat)
            except Exception:
                logger.warning("[pool_manager] F10 tracked_index enrichment failed", exc_info=True)

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
            symbol_extra = {e["symbol"]: {"fund_scale": e.get("fund_scale", 0)} for e in flat if e.get("symbol")}
            try:
                factor_scores = await self.factor_registry.compute(symbols, symbol_extra=symbol_extra)
                for item in flat:
                    sym = item["symbol"]
                    raw_scores = factor_scores.get(sym, {})
                    # B1: 聚合点分键为顶层分类键
                    item["factor_scores"] = self.factor_registry.aggregate_factor_scores(raw_scores)
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
            base_layer = item.get("layer", LAYER_SATELLITE)
            industry = item.get("industry", "unknown")

            # Core: 宽基指数
            if base_layer == "core" or industry == "宽基指数":
                target = LAYER_CORE
            # Defense: 商品/固收（注意：跨境归卫星层，P1-2 修复）
            elif base_layer == "defense" or industry in ("商品", "固收"):
                target = LAYER_DEFENSE
            # 跨境 → 卫星层（非防御资产）
            elif industry == "跨境":
                target = LAYER_SATELLITE
            # Research: unknown industry
            elif industry == "unknown":
                target = LAYER_RESEARCH
            else:
                target = LAYER_SATELLITE

            item["layer"] = target
            item["composite_score"] = 0.0
            new_pool[target].append(item)

        # 4c. B2: 同层同指数去重（依赖 tracked_index 字段）
        new_pool = self._deduplicate_by_index(new_pool)

        # 5. 强制保底
        self._ensure_mandatory(new_pool, flat)

        # 6. 层内复合评分 + 行业均衡化 + 截断
        for layer in ALL_LAYERS:
            for item in new_pool[layer]:
                item["composite_score"] = self._compute_composite(item, layer, regime=self.current_regime)
            max_n = MAX_PER_LAYER.get(layer, 10)
            # P4 fix-plan-pool: 行业均衡化后再截断
            balanced = self._balance_by_industry(new_pool[layer], max_n=max_n)
            new_pool[layer] = balanced[:max_n]

        # 7. 空池保护：如果刷新结果为空且存在上次成功数据，保留上次 pool 而非清空
        total_new = sum(len(v) for v in new_pool.values())
        if total_new == 0:
            if _last_good is not None:
                logger.warning("[pool_manager] refresh produced empty pool — keeping last good pool (v%d, %d total)",
                               self._version, sum(len(v) for v in _last_good.values()))
                # 不改变 self._pool 和 self._version，返回一个空 diff
                _elapsed = _time.time() - _start_ts
                pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                 timestamp=datetime.now().isoformat()))
                logger.info("PoolManager: refresh skipped (empty result) in %.1fs", _elapsed)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
            else:
                # 7.1: 首次刷新生效 — 无上次成功数据可回退，记录 CRITICAL
                self._consecutive_failures += 1
                logger.critical(
                    "[pool_manager] FIRST-RUN refresh produced empty pool — "
                    "data sources unavailable or timed out. "
                    "consecutive_failures=%d. Pool will remain empty until a successful refresh.",
                    self._consecutive_failures
                )
                # Don't overwrite self._pool (already empty), just return empty diff
                _elapsed = _time.time() - _start_ts
                pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                 timestamp=datetime.now().isoformat()))
                logger.info("PoolManager: first-run refresh failed in %.1fs (no fallback available)", _elapsed)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())

        # 7b. 重建索引
        self._pool = new_pool
        self._rebuild_index()
        self._version += 1
        # 7.1: 重置连续失败计数（本次刷新成功）
        self._consecutive_failures = 0

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
        logger.info("PoolManager: refresh complete (v%d, %d total) in %.1fs",
                     self._version,
                     sum(len(v) for v in self._pool.values()),
                     _elapsed)
        return diff

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
                    if code in ("510300", "560600"):
                        target = LAYER_CORE
                    elif code in ("518880",):
                        target = LAYER_DEFENSE
                    elif code == "511090":
                        target = LAYER_DEFENSE
                    else:
                        target = LAYER_SATELLITE
                    found["layer"] = target
                    pool[target].append(found)
                    logger.info("PoolManager: enforced mandatory %s -> %s", code, target)

    @staticmethod
    def _is_market_hours() -> bool:
        """检查当前是否为A股交易时段。

        非交易时段：成交额数据可能为昨日值，应降低流动性权重。
        """
        from datetime import datetime as _dt
        now = _dt.now()
        if now.weekday() >= 5:  # 周末
            return False
        t = now.strftime("%H:%M")
        return "09:30" <= t <= "11:30" or "13:00" <= t <= "15:00"

    @staticmethod
    def _normalize_regime(regime: str) -> str:
        """C2: 将市场状态值映射到 _LAYER_WEIGHTS 表的 key。

        外部 detect_market_regime() 返回的值可能包含 `bull_strong`、`range_bound` 等，
        但 _LAYER_WEIGHTS 表使用 `bull`、`neutral` 等简化 key。
        """
        mapping = {
            "bull_strong": "bull",
            "bull_weakening": "bull",
            "range_bound": "neutral",
            "neutral": "neutral",
            "correction": "correction",
            "bear": "bear",
            "defensive_rotate": "neutral",
            "panic": "bear",
        }
        return mapping.get(regime, "neutral")

    def _compute_composite(self, item: dict[str, Any], layer: str, regime: str = "neutral") -> float:
        """按层+市况计算综合得分。

        非交易时段（P6 fix-plan-pool）: 流动性数据可能为昨日值，
        降低流动性权重，以规模排序为主。
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

    def set_opportunistic_signals(self, signals: dict[str, dict]) -> None:
        """设置外部机会信号（用于 Layer 4）。

        Args:
            signals: {symbol: {"signal": str, "heat_score": float, ...}}
        """
        self._opportunistic_signals = signals
        logger.info("PoolManager: set %d opportunistic signals", len(signals))

    def _rebuild_index(self) -> None:
        """重建 symbol → entry 索引。"""
        self._by_code = {}
        for layer_items in self._pool.values():
            for item in layer_items:
                sym = item.get("symbol", "")
                if sym:
                    self._by_code[sym] = item

    def _compute_diff(
        self,
        old_by_code: dict[str, dict[str, Any]],
    ) -> PoolDiff:
        """计算新旧池之间的差异。"""
        new_by_code = self._by_code
        added = []
        removed = []
        changed = []

        for sym, entry in new_by_code.items():
            if sym not in old_by_code:
                added.append(entry)
            elif entry.get("layer") != old_by_code[sym].get("layer"):
                changed.append(entry)

        for sym, entry in old_by_code.items():
            if sym not in new_by_code:
                removed.append(entry)

        return PoolDiff(added=added, removed=removed, changed=changed)

    # 应急池已移除 — 数据源不可用时应报错而非用硬编码数据

    def get_pool(self, layer: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
        """获取候选池。

        Args:
            layer: 指定层名。None 返回全池。
        """
        # Check if main pool is empty → try emergency fallback
        if layer:
            pool = self._pool.get(layer, [])
            if not pool:
                logger.warning("[pool_manager] get_pool('%s') returned empty — main pool may be stale", layer)
            return pool

        total = sum(len(v) for v in self._pool.values())
        if total == 0:
            logger.warning("[pool_manager] get_pool() called but main pool is empty — data source unavailable")
        return self._pool

    def get_by_code(self, symbol: str) -> dict[str, Any] | None:
        """按代码查询单个 ETF。"""
        return self._by_code.get(symbol)

    def get_sector_momentum(self) -> list[dict]:
        """获取板块动量，120s 缓存 TTL。"""
        import time
        now = time.time()
        if self._sector_momentum_cache and (now - self._sector_momentum_cache_ts) < 120:
            return self._sector_momentum_cache
        return self._sector_momentum_cache or []

    def get_hot_plates(self) -> list[dict]:
        """获取热点板块缓存（Phase 6.1.6）。"""
        return self._hot_plates_cache or []

    def get_sector_heat(self) -> list[dict]:
        """获取板块热度排行缓存（Phase 6.1.6）。"""
        return self._sector_heat_cache or []

    def get_index_realtime(self) -> list[dict]:
        """获取 A 股大盘实时行情缓存。"""
        return self._index_realtime_cache or []

    # ── 市场状态缓存（Phase 5.1: dict[str,str] 支持多市场） ──
    _regime_cache: dict[str, str] = {}
    _regime_cache_ts: float = 0
    REGIME_TTL = 60

    def get_market_regime(self, market: str = "A") -> str:
        """获取市场状态，60s 缓存。支持多市场（Phase 5.1）。"""
        import time
        now = time.time()
        cached = self._regime_cache.get(market)
        if cached and (now - self._regime_cache_ts) < self.REGIME_TTL:
            return cached
        # Cache miss — regime 由外部定时刷新，返回旧值或默认
        return self._regime_cache.get(market, "range_bound")

    async def update_market_regime(self, market: str = "A") -> None:
        """异步刷新市场状态（由 refresh() 或外部调度器调用）。
        
        Phase 5.1: 支持按市场刷新。
        C2: 同步更新 self.current_regime 以便 _compute_composite 使用最新市态。
        """
        import time
        try:
            from .market_trends import detect_market_regime
            broad_index = {"A": "000001", "HK": "^HSI", "US": "^GSPC"}.get(market, "000001")
            regime = detect_market_regime(broad_index_code=broad_index)
            if regime:
                self._regime_cache[market] = regime
                self._regime_cache_ts = time.time()
                if market == "A":
                    self.current_regime = regime  # C2: 同步更新
                logger.info("[pool] regime updated for %s: %s", market, regime)
        except Exception as e:
            logger.exception("[pool] update_market_regime failed for %s: %s", market, e)

    # ── 情绪缓存 ──────────────────────────────────────────
    _sentiment_cache: dict | None = None
    _sentiment_cache_ts: float = 0
    SENTIMENT_TTL = 120

    async def refresh_sentiment_cache(self) -> None:
        """异步刷新市场情绪缓存（2.7.9）。"""
        import time
        try:
            from ..fetchers.fundamentals_fetcher import fetch_market_sentiment
            sentiment = await fetch_market_sentiment()
            if sentiment:
                self._sentiment_cache = sentiment
                self._sentiment_cache_ts = time.time()
                logger.info("[pool] sentiment cache refreshed")
        except Exception as e:
            logger.warning("[pool] refresh_sentiment_cache failed: %s", e)

    def get_market_sentiment(self) -> dict:
        """获取市场情绪，120s 缓存。"""
        import time
        now = time.time()
        if self._sentiment_cache and (now - self._sentiment_cache_ts) < self.SENTIMENT_TTL:
            return self._sentiment_cache
        try:
            from ..fetchers.fundamentals_fetcher import fetch_market_sentiment
            # Can't directly await here — cache miss just returns default
            pass
        except Exception:
            pass
        return self._sentiment_cache or {"sentiment_index": 50, "sentiment_label": "中性"}

    # ── 因子矩阵 ──────────────────────────────────────────
    @staticmethod
    def _normalize_matrix(matrix: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        """对因子矩阵做截面 z-score 归一化，消除量纲差异。

        排除 ln_mcap/ln_float_mcap（截面内无意义，所有大盘 ETF 都 ~25），
        排除仅有一两个非零值的因子（归一化会放大噪声）。
        """
        import statistics
        symbols = list(matrix.keys())
        if not symbols:
            return matrix

        # 收集所有因子键
        factor_keys: set[str] = set()
        for scores in matrix.values():
            factor_keys.update(k for k, v in scores.items())

        EXCLUDE = {"style.size.ln_mcap", "style.size.ln_float_mcap"}

        for key in factor_keys:
            if key in EXCLUDE:
                continue
            values = [matrix[s].get(key, 0.0) for s in symbols]
            # 跳过所有值相同的因子（无截面区分度）
            if max(values) - min(values) < 0.001:
                continue
            # 跳过只有一两个非零值的因子（归一化后噪声膨胀）
            non_zero = sum(1 for v in values if abs(v) > 0.001)
            if non_zero < 3:
                continue
            mean = statistics.mean(values)
            std = statistics.stdev(values) or 1.0
            for s in symbols:
                matrix[s][key] = (matrix[s].get(key, 0.0) - mean) / std

        return matrix

    def get_factor_matrix(self) -> dict[str, dict[str, float]]:
        """从候选池提取因子分矩阵，并做 z-score 归一化。"""
        result: dict[str, dict[str, float]] = {}
        for layer_items in self._pool.values():
            for item in layer_items:
                sym = item.get("symbol", "")
                if not sym:
                    continue
                fs = item.get("factor_scores", {})
                result[sym] = {k: v for k, v in fs.items() if isinstance(v, (int, float))}
        if not result:
            logger.warning("[pool_manager] get_factor_matrix() returned empty — pool may be empty or missing factor_scores")
            return result
        return self._normalize_matrix(result)

    # ── 新闻缓存 ──────────────────────────────────────────
    _news_cache: list[dict] | None = None
    _news_cache_ts: float = 0
    NEWS_TTL = 120

    def get_news(self) -> list[dict]:
        """获取缓存新闻，120s TTL。"""
        import time
        now = time.time()
        if self._news_cache is not None and (now - self._news_cache_ts) < self.NEWS_TTL:
            return self._news_cache
        return []

    def refresh_news(self) -> None:
        """同步刷新新闻缓存。"""
        import time
        try:
            from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
            news = fetch_news_headlines() or []
            macro = fetch_macro_news() or []
            all_news = news + macro
            self._news_cache = all_news
            self._news_cache_ts = time.time()
            logger.info("[pool] refreshed %d news items", len(all_news))
        except Exception as e:
            logger.exception("[pool] refresh_news failed: %s", e)


# Global singleton
pool_manager = PoolManager()
