"""
MarketDataHub: unified market-data entry point for the ETF Surge system.

Replaces the hardcoded CANDIDATE_POOL with a dynamic, 5-layer pool
backed by etf_scanner, ETFClassifier, and FactorRegistry.

Lifecycle:
  1. refresh() called daily (or on-demand)
  2. Scanner fetches all ETFs → filters → ranks into 3 base layers
  3. ETFClassifier adds industry/concept metadata
  4. MarketDataHub assigns 5 layers (core/satellite/defense/opportunistic/research)
  5. MANDATORY_CODES enforced
  6. PoolDiff generated for audit trail
"""
from __future__ import annotations

import asyncio
import ast
import logging
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from ..fetchers import etf_scanner
from ..fetchers import sector_fetcher
from ..factors.factor_registry import registry as factor_registry
from .etf_classifier import classifier as etf_classifier
from .pool_audit import pool_audit

logger = logging.getLogger(__name__)


def _parse_stock_list(s: Any) -> list:
    """安全解析 stock_list 字符串为数组（F2-6 步骤A；§9.8.3 伪代码）。

    数据源以字符串化列表存于行内，前端无解析层 → 在此统一转数组。
    非法字符串返回 []，绝不 eval。
    """
    if isinstance(s, list):
        return s
    if not s:
        return []
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_concept_tags(tag: Any) -> list[str]:
    """解析热门个股 tag 为 concept_tags 数组（F2-6 步骤A）。

    O9 (round8 §7 P9-新): 数据源 tag 是嵌套 dict {"concept_tag": [...],
    "popularity_tag": "..."}——旧实现对 dict 输入直接返回 [] → concept_tags
    50/50 全空。统一平铺：dict 取 concept_tag 键，list 元素若是 dict 取内层
    concept_tag，str dict 字面量走 ast.literal_eval。
    """
    def _flatten(value) -> list[str]:
        out: list[str] = []
        if isinstance(value, dict):
            # 嵌套 dict：优先取 concept_tag 键（可再嵌套 list）
            inner = value.get("concept_tag") or value.get("tags") or []
            out.extend(_flatten(inner))
        elif isinstance(value, list):
            for t in value:
                out.extend(_flatten(t))
        elif isinstance(value, str):
            s = value.strip()
            if s:
                out.append(s)
        return out

    if isinstance(tag, str):
        # 字符串可能是 dict/list 字面量（历史缓存格式）
        try:
            parsed = ast.literal_eval(tag)
            if isinstance(parsed, (dict, list)):
                return _flatten(parsed)[:6]
        except Exception:
            pass
        # 朴素逗号分隔兜底
        if "," in tag:
            return [t.strip() for t in tag.split(",") if t.strip()][:6]
        # O9: 无法解析的字符串不产出 tag（坏 tag 不落 concept_tags，保持旧行为）
        return []
    return _flatten(tag)[:6]


def _normalize_hot_plate(r: dict) -> dict:
    """热点板块行字段归一化（F2-6 步骤A，保持前端契约稳定）。

    secu_name→name、up_reason→reason、plate_stock_up_num→stock_count、
    stock_list(字符串)→lead_stocks(数组)。
    """
    item = dict(r)
    if "secu_name" in item and "name" not in item:
        item["name"] = item.pop("secu_name")
    if "up_reason" in item and "reason" not in item:
        item["reason"] = item.pop("up_reason")
    if "plate_stock_up_num" in item and "stock_count" not in item:
        item["stock_count"] = item.pop("plate_stock_up_num")
    if "stock_list" in item:
        item["lead_stocks"] = _parse_stock_list(item.pop("stock_list"))
    return item

# 强制保留标的（池刷新时永不出池）
# round9 P0-8: 560600（幽灵锚，实为医药白酒ETF/零成交）→ 159338（真实中证A500ETF）
MANDATORY_CODES = {"510300", "159338", "518880", "511090"}

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


class MarketDataHub:
    """候选池管理器。

    Usage:
        pm = MarketDataHub()
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
        # S5: MarketDataHub K 线缓存（统一数据管道，R3: 单行式缓存 + 锁）
        self._kline_cache_rows: dict[str, list[dict]] = {}  # 行式: {symbol: [{date,open,...}]}
        self._kline_cache_ts: float = 0.0
        self._kline_cache_symbols: list[str] = []
        self._kline_cache_lock: asyncio.Lock = asyncio.Lock()  # R3: 单锁保护

        # 兼容旧字段名（get_kline 仍可读）
        self._kline_cache: dict[str, dict[str, Any]] = {}
        # 60s TTL 缓存（Solution Design S1-A）
        self._cached_pool: dict | None = None
        self._cached_ts: float = 0.0
        self._cache_ttl: float = 60.0
        self._test_mode: bool = False  # #6: 测试模式下禁止 teardown HTTP 泄漏
        # 7.1: consecutive refresh failure counter for observability
        self._consecutive_failures: int = 0

    @staticmethod
    def _rows_to_columns(rows: list[dict], days: int = 60) -> dict[str, list[float]]:
        """R3: 将行式 K 线数据转为列式（懒转换）。

        Input:  [{date, open, high, low, close, volume}, ...]
        Output: {close: [3.45, ...], high: [3.5, ...], low: [3.3, ...], volume: [1e7, ...],
                 change_pct: [0.5, ...]}
        """
        if not rows:
            return {"close": [], "high": [], "low": [], "volume": [], "change_pct": []}
        tail = rows[-days:]
        closes = [r.get("close", r.get("close", 0)) for r in tail]
        highs = [r.get("high", r.get("high", r.get("close", 0))) for r in tail]
        lows = [r.get("low", r.get("low", r.get("close", 0))) for r in tail]
        vols = [r.get("volume", r.get("volume", 0)) for r in tail]

        change_pct = [0.0]
        for i in range(1, len(closes)):
            if closes[i - 1]:
                change_pct.append(round((closes[i] - closes[i - 1]) / closes[i - 1] * 100, 2))
            else:
                change_pct.append(0.0)

        return {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": vols,
            "change_pct": change_pct,
        }

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
        try:
            from ..core.async_utils import run_sync_long, run_sync
            raw_layers = await asyncio.wait_for(
                run_sync_long(self.scanner.full_pipeline, timeout=60),
                timeout=90,
            )
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
            # R5-0-1: 截断时保护强制标的——截断前剔除 MANDATORY_CODES，截断后再补回
            #（P1-1 A500 缺失根因：_ensure_mandatory 在截断前执行，截断把 560600 挤出后无二次校验）
            new_pool[layer] = self._truncate_with_mandatory_protection(balanced, max_n=max_n)

        # 6b. R5-0-1: 截断后强制标的二次校验（对齐 etf_scanner._log_missing_required 口径）
        # 失败仅 WARNING + 从 flat 找回注入，不抛异常；与 _ensure_mandatory 语义一致。
        self._recheck_mandatory_after_truncate(new_pool, flat)

        # 7. 空池保护：如果刷新结果为空且存在上次成功数据，保留上次 pool 而非清空
        total_new = sum(len(v) for v in new_pool.values())
        if total_new == 0:
            if _last_good is not None:
                logger.warning("[market_data_hub] refresh produced empty pool — keeping last good pool (v%d, %d total)",
                               self._version, sum(len(v) for v in _last_good.values()))
                # 不改变 self._pool 和 self._version，返回一个空 diff
                _elapsed = _time.time() - _start_ts
                pool_audit.log_refresh(PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                                 timestamp=datetime.now().isoformat()))
                logger.info("MarketDataHub: refresh skipped (empty result) in %.1fs", _elapsed)
                return PoolDiff(added=[], removed=[], changed=[], version=self._version,
                                timestamp=datetime.now().isoformat())
            else:
                # 7.1: 首次刷新生效 — 无上次成功数据可回退，记录 CRITICAL
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
        logger.info("MarketDataHub: set %d opportunistic signals", len(signals))

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
                logger.warning("[market_data_hub] get_pool('%s') returned empty — main pool may be stale", layer)
            return pool

        total = sum(len(v) for v in self._pool.values())
        if total == 0:
            logger.warning("[market_data_hub] get_pool() called but main pool is empty — data source unavailable")
        return self._pool

    def get_by_code(self, symbol: str) -> dict[str, Any] | None:
        """按代码查询单个 ETF。"""
        return self._by_code.get(symbol)

    # ── S5: MarketDataHub K 线缓存 ────────────────────────────────────

    def get_kline(self, symbol: str, max_age: int = 300) -> dict[str, Any] | None:
        """R3: 从行式缓存懒转换返回列式 K 线数据。

        Args:
            symbol: ETF 代码。
            max_age: 缓存最大时效（秒），默认 300s（5 分钟）。

        Returns:
            列式 K 线数据 {close:[], high:[], ...}，或 None。
        """
        rows = self.get_kline_rows(symbol, max_age=max_age)
        if rows is None or not rows:
            return None
        return self._rows_to_columns(rows)

    def get_kline_symbols(self) -> list[str]:
        """返回缓存中有 K 线数据的 ETF 代码列表。"""
        return list(self._kline_cache_rows.keys())

    def get_history(self, symbol: str, market: str = "A", period: str = "daily") -> list[dict] | None:
        """实时取历史 K 线（委托 china_market.fetch_history，含 fallback 链）。"""
        try:
            from ..fetchers.china_market import fetch_history
            return fetch_history(symbol, market, period) or []
        except Exception as e:
            logger.warning("[hub] get_history(%s) failed: %s", symbol, e)
            return None

    def get_kline_rows(self, symbol: str, max_age: int = 300) -> list[dict] | None:
        """R3: 获取行式 K 线数据（直接读缓存，无转换）。

        Args:
            symbol: ETF 代码。
            max_age: 缓存最大时效（秒）。

        Returns:
            行式 K 线 [{date, open, high, low, close, volume}, ...]，或 None。
        """
        import time
        rows = self._kline_cache_rows.get(symbol)
        if rows and (time.time() - self._kline_cache_ts) < max_age:
            return rows
        return None

    # F0-4: 过期 K 线缓存兜底（akshare 熔断 / 全源失败时仍有数据）
    _kline_stale_flags: dict[str, bool] = {}

    def get_kline_rows_any(self, symbol: str) -> list[dict] | None:
        """F0-4: 返回任意年龄的 K 线缓存（不检查新鲜度）。"""
        return self._kline_cache_rows.get(symbol) or None

    def get_kline_age_seconds(self, symbol: str) -> float | None:
        """F0-4: 缓存数据龄（秒），无缓存返回 None。"""
        import time
        if symbol in self._kline_cache_rows:
            return max(0.0, time.time() - self._kline_cache_ts)
        return None

    def mark_kline_stale(self, symbol: str, stale: bool = True) -> None:
        """F0-4: 记录该 symbol 最近一次 history 是否走了 stale 兜底。"""
        self._kline_stale_flags[symbol] = stale

    def is_kline_stale(self, symbol: str) -> bool:
        """F0-4: 查询该 symbol 是否最近一次 history 走了 stale 兜底。"""
        return self._kline_stale_flags.get(symbol, False)

    async def refresh_kline(self, symbols: list[str]) -> None:
        """S5: 增量刷新 K 线缓存（R3: 直接 fetch_history + Semaphore 并发）。

        不再经过 factor_registry._fetch_market_data（消除循环依赖）。
        统一存储行式格式，get_kline() 时懒转换为列式。

        Args:
            symbols: 需要刷新的 ETF 代码列表。
        """
        if not symbols:
            return
        from ..fetchers.china_market import fetch_history
        from ..core.async_utils import run_sync

        sem = asyncio.Semaphore(5)  # R3: 并发控制

        async def _fetch_one(sym: str) -> tuple[str, list[dict] | None]:
            async with sem:
                try:
                    rows = await run_sync(fetch_history, sym, "A", "daily", timeout=20)
                    return sym, rows
                except Exception as e:
                    logger.debug("[pool] refresh_kline fetch_history(%s) failed: %s", sym, e)
                    return sym, None

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        async with self._kline_cache_lock:
            updated = 0
            for r in results:
                if isinstance(r, tuple) and len(r) == 2:
                    sym, rows = r
                    if isinstance(rows, list) and rows:
                        self._kline_cache_rows[sym] = rows
                        updated += 1
            if updated > 0:
                self._kline_cache_ts = __import__('time').time()
                self._kline_cache_symbols = list(set(self._kline_cache_symbols + symbols))
                # 同步更新列式缓存（向后兼容 get_kline 旧调用方）
                self._sync_columnar_cache()
                logger.debug("[pool] refresh_kline updated %d/%d symbols", updated, len(symbols))

    def _sync_columnar_cache(self):
        """R3: 从行式缓存重建列式缓存（兼容旧 get_kline 调用方）。"""
        self._kline_cache = {}
        for sym, rows in self._kline_cache_rows.items():
            cols = self._rows_to_columns(rows)
            if cols and cols.get("close"):
                self._kline_cache[sym] = cols

    def _build_symbol_extra(self, symbols: list[str]) -> dict[str, dict]:
        """构建 symbol_extra 字典，供 factor_registry 使用。"""
        result = {}
        for sym in symbols:
            entry = self._by_code.get(sym, {})
            result[sym] = {
                "fund_scale": entry.get("fund_scale", 0),
                "fund_shares": entry.get("fund_shares", 0),
                # F19: carry industry/concepts for china_specific factors
                "industry": entry.get("industry", "unknown"),
                "concepts": entry.get("concepts", []),
            }
        return result

    # F3-4 步骤B: 宽基 ETF → 指数代码（东财指数，benchmark_close 注入用）。
    # §9.10.7-4 已确认「宽基先行」：行业指数随 mapping 补全后跟进。
    # O19 (round7 §7 P20-②): 补新宽基映射——A500/A50/A100/红利低波/公共底仓锚。
    _WIDE_BASIS_INDEX_CODES = {
        "510300": "sh000300",  # 沪深300
        "159919": "sh000300",  # 沪深300（深市嘉实）
        "510500": "sh000905",  # 中证500
        "159922": "sh000905",  # 中证500（深市）
        "510050": "sh000016",  # 上证50
        "588000": "sh000688",  # 科创50
        "159915": "sz399006",  # 创业板指
        "510880": "sh000015",  # 上证红利
        "159338": "sh000510",  # 中证A500（O19；round9 P0-8: 560600 → 159338）
        "563080": "sh932000",  # 中证A50（O19）
        "562000": "sh000903",  # 中证A100（O19）
        "563020": "sh000922",  # 红利低波（O19，中证红利低波动指数）
        "512890": "sh000922",  # 红利低波ETF（O19，同指数）
        "510180": "sh000010",  # 上证180（O19）
        "159901": "sz399001",  # 深证100（O19）
        "159800": "sh000906",  # 中证800（O19）
        "159845": "sh000852",  # 中证1000（O19）
        "159601": "sh932000",  # 中国A50ETF（O19，同 A50 指数）
        # P1-8 (round9 §6.5.1-B): 主题 ETF 基准映射扩展——行业/主题 ETF 此前无基准映射
        # → benchmark_close 全缺 → tracking_error no_data。仅收录实测（2026-08-07 腾讯行情
        # 200 且名称非空）确认的指数代码；未确认的（半导体/新能源车等）宁缺毋滥
        # （错误基准比缺失更误导，见 P2-10 幽灵锚教训）。
        "512880": "sz399975",  # 证券ETF → 中证全指证券公司（实测）
        "512010": "sh000933",  # 医药ETF → 中证医药（实测）
        # P1-J (round10 §5.5/§10): benchmark_close 映射扩到候选池主要行业/主题
        # ETF（东财/腾讯行情实测 2026-08-09 名称匹配 + 指数对应，消除 tracking_error
        # 0 命中）。未收录仍保持「宁缺毋滥」——只加能确认对应的。
        "512690": "sh000932",  # 酒ETF → 中证白酒
        "512170": "sh000933",  # 医疗ETF → 中证医疗（同医药基准）
        "512760": "sh000733",  # 芯片ETF → 中华半导体芯片
        "159995": "sz399812",  # 芯片ETF → 国证半导体芯片
        "512480": "sh931071",  # 半导体ETF → 中证全指半导体
        "515790": "sh930997",  # 光伏ETF → 中证光伏产业
        "515030": "sh930714",  # 新能源汽车ETF → 中证新能源汽车
        "516160": "sh931151",  # 新能源ETF → 中证新能源
        "512400": "sh000819",  # 有色金属ETF → 中证有色金属
        "512800": "sh000806",  # 银行ETF → 中证银行
        "512000": "sh930791",  # 券商ETF → 中证全指证券公司（沪市）
        "159920": "sz399933",  # 恒生ETF（港）→ 恒生指数
        "513050": "sh000856",  # 中概互联ETF → 中证海外中国互联网
    }
    # F3-4 步骤C: 份额数据 24h 缓存（fund_fund_shares_em 日更/周更）
    _FUND_SHARES_CACHE: dict[str, tuple[float, dict]] = {}
    _FUND_SHARES_TTL = 86400.0
    # P2-1 延伸 (R4-16): symbol_extra enrich 总超时（数据源慢时降级部分数据，不阻塞刷新）
    _ENRICH_TOTAL_TIMEOUT = 60.0

    async def _enrich_symbol_extra(
        self,
        symbols: list[str],
        base_extra: dict[str, dict],
    ) -> dict[str, dict]:
        """F3-4 步骤B/C: 注入 benchmark_close（宽基指数历史 close）与 shares_change_20d（份额变化）。

        - benchmark_close → tracking_error（§9.5.4 步骤B，宽基先行）
        - shares_change_20d → shares_change 直接生效 + institutional_holdings_change ×0.5 折扣代理
        - 任一失败静默（不阻塞主流程），份额数据 24h 缓存
        """
        import time
        from ..fetchers.china_market import fetch_etf_shares_outstanding

        out = {s: dict(base_extra.get(s) or {}) for s in symbols}

        # P2-1 延伸 (R4-16): 并发限制 + 总超时——66 只 × 2 个任务无限制并发
        # 会在 NAV/份额数据源慢时打满线程池（POOL SATURATION，get_fund_nav 6s 超时
        # × 大量堆积）→ 候选池刷新永远失败 → verify_e2e 候选池类检查全 FAIL。
        # Semaphore(8) 控制并发 + wait_for 总超时（超时降级为部分数据，不阻塞刷新）。
        _sem = asyncio.Semaphore(8)

        async def _bench(sym: str):
            async with _sem:
                idx_code = self._WIDE_BASIS_INDEX_CODES.get(sym)
                if not idx_code:
                    return
                try:
                    hist = await self.get_market_history(idx_code, "index", "daily")
                    closes = [float(r.get("close", 0)) for r in (hist or []) if r.get("close")]
                    if len(closes) >= 5:
                        out.setdefault(sym, {})["benchmark_close"] = closes[-20:]
                except Exception as e:
                    logger.debug("[hub] benchmark_close for %s failed: %s", sym, e)

        async def _shares(sym: str):
            async with _sem:
                try:
                    cached = self._FUND_SHARES_CACHE.get(sym)
                    if cached and (time.time() - cached[0]) < self._FUND_SHARES_TTL:
                        shares_data = cached[1]
                    else:
                        from ..core.async_utils import run_sync
                        shares_data = await run_sync(fetch_etf_shares_outstanding, sym, timeout=10)
                        # F19 R71: 失败/空结果不写 24h 成功缓存——旧代码 `or {}` 把失败变成
                        # {} 写进缓存 → 后续 24h 命中 {} → gap 持续；akshare 恢复后还要再等
                        # 24h 才重试（熔断恢复后自动补齐被缓存破绽阻断）
                        if not shares_data or shares_data.get("shares_change_20d") is None:
                            return
                        self._FUND_SHARES_CACHE[sym] = (time.time(), shares_data)
                    if shares_data.get("shares_change_20d") is not None:
                        out.setdefault(sym, {})["shares_change_20d"] = shares_data["shares_change_20d"]
                        # §9.10.7-5 确认: institutional_holdings_change 用 ×0.5 折扣代理
                        out[sym]["institutional_holdings_change"] = float(shares_data["shares_change_20d"]) * 0.5
                except Exception as e:
                    logger.debug("[hub] shares_change_20d for %s failed: %s", sym, e)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_bench(s) for s in symbols),
                    *(_shares(s) for s in symbols),
                ),
                timeout=self._ENRICH_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[hub] symbol_extra enrich timed out after %ss (partial: %d/%d symbols)",
                self._ENRICH_TOTAL_TIMEOUT, len(out), len(symbols),
            )
        return out

    def get_sector_momentum(self) -> list[dict]:
        """获取板块动量，120s 缓存 TTL。"""
        import time
        now = time.time()
        if self._sector_momentum_cache and (now - self._sector_momentum_cache_ts) < 120:
            return self._sector_momentum_cache
        return self._sector_momentum_cache or []

    def get_hot_plates(self, limit: int | None = None, market: str = "A") -> list[dict]:
        """热点板块。默认返回缓存；传 limit 时实时取数（保持路由语义）。

        F2-6 步骤A: 输出统一归一化（secu_name→name / up_reason→reason /
        plate_stock_up_num→stock_count / stock_list→lead_stocks 数组）。
        F16 (round6 §16.4): market=HK 走港股 push2delay 行业聚合；
        market=US 返回「暂不支持」（不返回 A 股数据）。
        """
        if market and market.upper() != "A":
            from ..fetchers.hk_hot_fetcher import get_hk_hot_plates
            if market.upper() == "HK":
                return get_hk_hot_plates(limit or 15)
            return []  # US 暂不支持（结构化提示由路由层处理）
        if limit is not None:
            try:
                rows = sector_fetcher.fetch_hot_plates(limit) or []
            except Exception as e:
                logger.warning("[hub] get_hot_plates(limit) failed: %s", e)
                return []
        else:
            rows = self._hot_plates_cache or []
        return [_normalize_hot_plate(r) for r in rows]

    def get_sector_heat(self, limit: int | None = None, market: str = "A") -> list[dict]:
        """获取板块热度排行（Phase 6.1.6）。

        F2-3: limit 传值时实时取数（与 get_hot_plates 语义一致），否则返回缓存。
        F16: market=HK 走港股行业聚合；market=US 暂不支持。
        """
        if market and market.upper() != "A":
            from ..fetchers.hk_hot_fetcher import get_hk_hot_plates
            if market.upper() == "HK":
                plates = get_hk_hot_plates(limit or 20)
                return [{"rank": i + 1, "name": p["name"], "heat_index": round(p["amount"] / 1e6, 1),
                         "change_pct": p["change_pct"], "plate_code": "HK"} 
                        for i, p in enumerate(plates)]
            return []
        if limit is not None:
            try:
                return sector_fetcher.fetch_sector_heat(limit) or []
            except Exception as e:
                logger.warning("[hub] get_sector_heat(%s) failed: %s", limit, e)
                return []
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
        import json
        import os
        try:
            from ..fetchers.fundamentals_fetcher import fetch_market_sentiment
            sentiment = await fetch_market_sentiment()
            if sentiment:
                self._sentiment_cache = sentiment
                self._sentiment_cache_ts = time.time()
                # A02: Persist sentiment cache to file for crash recovery
                _cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
                os.makedirs(_cache_dir, exist_ok=True)
                _cache_file = os.path.join(_cache_dir, "sentiment_cache.json")
                with open(_cache_file, "w", encoding="utf-8") as f:
                    json.dump({"sentiment": sentiment, "ts": time.time()}, f, ensure_ascii=False)
                logger.info("[pool] sentiment cache refreshed and persisted")
        except Exception as e:
            logger.warning("[pool] refresh_sentiment_cache failed: %s", e)
            # A02: On failure, try to restore from persisted file
            try:
                _cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
                _cache_file = os.path.join(_cache_dir, "sentiment_cache.json")
                if os.path.exists(_cache_file):
                    with open(_cache_file, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    if isinstance(cached, dict) and "sentiment" in cached:
                        self._sentiment_cache = cached["sentiment"]
                        self._sentiment_cache_ts = cached.get("ts", 0)
                        logger.info("[pool] restored sentiment from persisted cache file")
            except Exception as restore_e:
                logger.warning("[pool] failed to restore sentiment from cache file: %s", restore_e)

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
    def _normalize_matrix(
        matrix: dict[str, dict[str, float]],
        raw_codes: set[str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """对因子矩阵做截面 z-score 归一化，消除量纲差异。

        排除 ln_mcap/ln_float_mcap（截面内无意义，所有大盘 ETF 都 ~25），
        排除仅有一两个非零值的因子（归一化会放大噪声）。
        O4 (round7 §7 P6): `standardization=raw` 的因子（rsi_14/rsi_24 等，
        factor_definitions.yaml 声明）跳过截面 z-score，保留真实 0-100 值——
        rationale「RSI<30 超卖」等判断需要真实值而非相对分。
        """
        import statistics
        symbols = list(matrix.keys())
        if not symbols:
            return matrix

        raw = raw_codes or set()

        # 收集所有因子键
        factor_keys: set[str] = set()
        for scores in matrix.values():
            factor_keys.update(k for k, v in scores.items())

        EXCLUDE = {"style.size.ln_mcap", "style.size.ln_float_mcap"}

        for key in factor_keys:
            if key in EXCLUDE:
                # Z09: size 因子做 min-max 归一化（保留截面相对排序、消除量纲），
                # 而非完全跳过——否则原始 ln(mcap)≈25 会作为“25σ”离群值进入 factor_breakdown
                values = [matrix[s].get(key, 0.0) for s in symbols]
                vmin, vmax = min(values), max(values)
                if vmax - vmin < 1e-10:
                    # 截面无区分度（如 total_mv 未注入导致全同）时置中性 0，不泄漏原始量纲值
                    for s in symbols:
                        matrix[s][key] = 0.0
                    continue
                for s in symbols:
                    matrix[s][key] = (matrix[s].get(key, 0.0) - vmin) / (vmax - vmin) * 2.0 - 1.0
                continue
            if key in raw:
                # O4: raw 因子（RSI 0-100 等）跳过截面 z-score——保留真实量纲
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

    def _raw_factor_codes(self) -> set[str]:
        """O4: factor_definitions.yaml 中 standardization=raw 的因子 code 集合。"""
        raw = set()
        try:
            for code, definition in factor_registry._factors.items():
                if definition.standardization == "raw":
                    raw.add(code)
        except Exception:
            pass
        return raw

    def get_factor_matrix(self) -> dict[str, dict[str, float]]:
        """从候选池提取因子分矩阵，并做 z-score 归一化（raw 因子除外）。"""
        result: dict[str, dict[str, float]] = {}
        for layer_items in self._pool.values():
            for item in layer_items:
                sym = item.get("symbol", "")
                if not sym:
                    continue
                fs = item.get("factor_scores", {})
                result[sym] = {k: v for k, v in fs.items() if isinstance(v, (int, float))}
        if not result:
            logger.warning("[market_data_hub] get_factor_matrix() returned empty — pool may be empty or missing factor_scores")
            return result
        return self._normalize_matrix(result, raw_codes=self._raw_factor_codes())

    # ── 新闻缓存 ──────────────────────────────────────────
    _news_cache: list[dict] | None = None
    _news_buckets: dict | None = None
    _news_cache_ts: float = 0
    NEWS_TTL = 120

    def get_news(self) -> list[dict]:
        """获取缓存新闻（合并视图），120s TTL。"""
        import time
        now = time.time()
        if self._news_cache is not None and (now - self._news_cache_ts) < self.NEWS_TTL:
            return self._news_cache
        return []

    def _news_bucket(self, key: str) -> list[dict]:
        """按分类返回新闻桶；缓存过期或未初始化时懒刷新一次。"""
        import time
        now = time.time()
        if self._news_buckets is None or (now - self._news_cache_ts) > self.NEWS_TTL:
            self.refresh_news()
        return (self._news_buckets or {}).get(key, [])

    def get_news_headlines(self) -> list[dict]:
        """财联社头条（分类缓存）。"""
        return self._news_bucket("headlines")

    async def enrich_news_summaries(self) -> int:
        """Z18: 为重要新闻(level>=3 或 stars>=4)生成 AI 摘要并写回缓存。

        LLM 失败静默保留 None；单轮最多 5 条控制成本；改的是缓存内 dict 引用，
        因此 write-back 对 get_news_headlines 立即可见。
        """
        try:
            from ..analysis.llm import generate_news_summary
        except Exception:
            return 0
        items = self._news_bucket("headlines")
        targets = [
            n for n in items
            if not n.get("ai_summary")
            and (int(n.get("stars", 0) or 0) >= 4 or str(n.get("level", "")) in ("重大", "利好"))
        ]
        enriched = 0
        for n in targets[:5]:
            try:
                summary = await generate_news_summary(n.get("title", ""), n.get("content", ""))
                if summary:
                    n["ai_summary"] = summary
                    enriched += 1
            except Exception:
                continue
        return enriched

    def get_news_macro(self) -> list[dict]:
        """宏观政策新闻（分类缓存）。"""
        return self._news_bucket("macro")

    def get_news_global(self) -> list[dict]:
        """国际宏观新闻（分类缓存）。"""
        return self._news_bucket("global")

    def get_news_stock(self, symbol: str) -> list[dict]:
        """个股新闻（实时取数，无缓存）。"""
        try:
            from ..fetchers.news_fetcher import fetch_stock_news
            return fetch_stock_news(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_news_stock(%s) failed: %s", symbol, e)
            return []

    def get_akshare_pool_stats(self) -> dict:
        """akshare 池统计（直接委托）。"""
        try:
            from ..fetchers.news_fetcher import get_akshare_pool_stats
            return get_akshare_pool_stats()
        except Exception as e:
            logger.warning("[hub] get_akshare_pool_stats failed: %s", e)
            return {}

    def refresh_news(self) -> None:
        """同步刷新新闻分类缓存（headlines/macro/global 分别入桶）。"""
        import time
        try:
            from ..fetchers.news_fetcher import (
                fetch_news_headlines,
                fetch_macro_news,
                fetch_global_news,
            )
            headlines = fetch_news_headlines() or []
            macro = fetch_macro_news() or []
            global_news = fetch_global_news() or []
            self._news_buckets = {
                "headlines": headlines,
                "macro": macro,
                "global": global_news,
            }
            self._news_cache = headlines + macro + global_news  # 合并视图兼容
            self._news_cache_ts = time.time()
            logger.info("[hub] refreshed %d news items", len(self._news_cache))
        except Exception as e:
            logger.exception("[hub] refresh_news failed: %s", e)

    # ── Phase 2: sector / fundamental / history aggregation ──

    def get_sector_industry(self, limit: int = 80) -> list[dict]:
        """行业板块列表（实时取数）。"""
        try:
            from ..fetchers.sector_fetcher import fetch_industry_sectors
            return fetch_industry_sectors(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_industry failed: %s", e)
            return []

    def get_sector_concept(self, limit: int = 150) -> list[dict]:
        """概念板块列表（实时取数）。"""
        try:
            from ..fetchers.sector_fetcher import fetch_concept_sectors
            return fetch_concept_sectors(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_concept failed: %s", e)
            return []

    def get_sector_stocks(self, sector_code: str) -> list[dict]:
        """板块成分股（实时取数）。"""
        try:
            from ..fetchers.sector_fetcher import fetch_sector_stocks
            return fetch_sector_stocks(sector_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_stocks(%s) failed: %s", sector_code, e)
            return []

    def get_fund_flow(self, symbol: str) -> dict | None:
        """个股资金流。"""
        try:
            from ..fetchers.fundamentals_fetcher import fetch_fund_flow
            return fetch_fund_flow(symbol)
        except Exception as e:
            logger.warning("[hub] get_fund_flow(%s) failed: %s", symbol, e)
            return None

    def get_hist_avg_volume(self, symbol: str, days: int = 20) -> dict | None:
        """历史平均成交量。"""
        try:
            from ..fetchers.fundamentals_fetcher import fetch_hist_avg_volume
            return fetch_hist_avg_volume(symbol, days)
        except Exception as e:
            logger.warning("[hub] get_hist_avg_volume(%s) failed: %s", symbol, e)
            return None

    def get_fundamentals(self, symbol: str) -> dict:
        """基本面数据（Tushare）。"""
        try:
            from ..fetchers.fundamentals_fetcher import fetch_fundamentals
            return fetch_fundamentals(symbol) or {}
        except Exception as e:
            logger.warning("[hub] get_fundamentals(%s) failed: %s", symbol, e)
            return {}

    def get_advance_decline(self) -> float:
        """涨跌家数比（因子用）。"""
        try:
            from ..fetchers.fundamentals_fetcher import fetch_advance_decline_ratio
            return fetch_advance_decline_ratio()
        except Exception as e:
            logger.warning("[hub] get_advance_decline failed: %s", e)
            return 0.0


    # ── Phase 3: realtime / indices / commodities (delegate market_service) ──

    async def get_realtime(self, symbols: list[str], asset_type: str = "A") -> list[dict]:
        """批量实时行情（委托 market_service.get_realtime_batch）。"""
        from ..services.market_service import get_realtime_batch
        return await get_realtime_batch(symbols, asset_type)

    async def get_all_realtime(self) -> list[dict]:
        """全量实时行情（委托 market_service.get_all_realtime）。"""
        from ..services.market_service import get_all_realtime
        return await get_all_realtime()

    async def get_asset_realtime(self, symbol: str, asset_type: str) -> dict | None:
        """单标的实时行情（委托 market_service.get_asset_realtime）。"""
        from ..services.market_service import get_asset_realtime
        return await get_asset_realtime(symbol, asset_type)

    async def get_portfolio_realtime(self) -> list[dict]:
        """组合实时行情（委托 market_service.get_portfolio_realtime）。"""
        from ..services.market_service import get_portfolio_realtime
        return await get_portfolio_realtime()

    async def get_indices(self) -> list[dict]:
        """全球指数（委托 market_service.get_indices）。"""
        from ..services.market_service import get_indices
        return await get_indices()

    async def get_global_indices(self) -> dict[str, list[dict]]:
        """全球指数分组（委托 market_service.get_global_indices）。"""
        from ..services.market_service import get_global_indices
        return await get_global_indices()

    async def get_commodities(self) -> list[dict]:
        """商品行情（委托 market_service.get_commodities）。"""
        from ..services.market_service import get_commodities
        return await get_commodities()


    # ── Phase 3b: search / meta / history (delegate market_service) ──

    async def get_market_history(self, symbol: str, asset_type: str = "A", period: str = "daily") -> list[dict]:
        """历史 K 线（完整 fallback 链，委托 market_service.get_history）。"""
        from ..services.market_service import get_history as _get_history
        return await _get_history(symbol, asset_type, period)

    async def search_etf(self, keyword: str) -> list[dict]:
        """ETF 搜索（委托 market_service.search_etf）。"""
        from ..services.market_service import search_etf as _search_etf
        return await _search_etf(keyword)

    async def get_sectors_local(self, sector_type: str) -> list[dict]:
        """本地板块列表（委托 market_service.get_sectors_local）。"""
        from ..services.market_service import get_sectors_local as _get
        return await _get(sector_type)

    async def get_indices_meta(self) -> list[dict]:
        """指数元数据（委托 market_service.get_indices_meta）。"""
        from ..services.market_service import get_indices_meta as _get
        return await _get()

    async def search_indices(self, keyword: str) -> list[dict]:
        """指数搜索（委托 market_service.search_indices）。"""
        from ..services.market_service import search_indices as _search
        return await _search(keyword)


    async def get_market_fundamentals(self, symbol: str) -> dict | None:
        """基本面（market_service 版：返回 {symbol, daily} 结构）。"""
        from ..services.market_service import get_fundamentals as _get
        return await _get(symbol)


    # ── Phase 5a: remaining fetcher delegates (DoD single-source) ──

    def get_market_emotion(self) -> dict:
        """市场情绪（levistock）。"""
        try:
            from ..fetchers.levistock_fetcher import fetch_market_emotion
            return fetch_market_emotion() or {}
        except Exception as e:
            logger.warning("[hub] get_market_emotion failed: %s", e)
            return {}

    def get_market_wind(self) -> list[dict]:
        """市场风控（levistock）。"""
        try:
            from ..fetchers.levistock_fetcher import fetch_market_wind
            return fetch_market_wind() or []
        except Exception as e:
            logger.warning("[hub] get_market_wind failed: %s", e)
            return []

    def get_stock_hot_rank(self, limit: int = 50, market: str = "A") -> list[dict]:
        """热门个股排行（Z25: 补全 volume/turnover/sector）。

        F16→P2-R (round10 §5.6): market=HK 走港股成交额榜；market=US 走东财
        spot_em 成交额降序 TOP N（美股无涨跌停，成交额榜即"热度"）。
        """
        if market and market.upper() == "HK":
            from ..fetchers.hk_hot_fetcher import get_hk_hot_stocks
            return get_hk_hot_stocks(limit)
        if market and market.upper() == "US":
            try:
                from ..fetchers.china_market import _fetch_us_spot
                us_rows = _fetch_us_spot() or []
                # 按成交额降序（amount 缺失的排到尾），取 TOP N
                ranked = sorted(
                    [r for r in us_rows if r.get("amount") is not None],
                    key=lambda r: -(r.get("amount") or 0),
                )
                head = ranked[:limit]
                if not head:
                    head = us_rows[:limit]
                return [
                    {
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "price": r.get("price"),
                        "change_pct": r.get("change_pct"),
                        "amount": r.get("amount"),
                        "mcap": r.get("mcap"),
                        "market": "US",
                    }
                    for r in head
                ]
            except Exception as e:
                logger.warning("[hub] get_stock_hot_rank US failed: %s", e)
                return []
        try:
            from ..fetchers.sector_fetcher import fetch_stock_hot_rank
            rows = fetch_stock_hot_rank(limit) or []
        except Exception as e:
            logger.warning("[hub] get_stock_hot_rank failed: %s", e)
            return []
        if not rows:
            return []
        try:
            return self._enrich_stock_hot_rank(rows)
        except Exception as e:
            logger.warning("[hub] stock_hot_rank enrich failed: %s", e)
            return rows

    def _enrich_stock_hot_rank(self, rows: list[dict]) -> list[dict]:
        """Z25: 热门个股补全 volume/turnover（批量行情）+ sector（行业映射）。

        任一补全步骤失败不阻塞主流程，缺失字段留默认值。
        """
        codes = [str(r.get("code") or r.get("symbol") or "").strip() for r in rows]
        codes = [c for c in codes if c]
        if not codes:
            return rows

        # 1) volume/turnover via batch realtime
        batch_map: dict[str, dict] = {}
        try:
            from ..fetchers.china_market import fetch_a_stock_batch
            batch = fetch_a_stock_batch(codes) or []
            for b in batch:
                sym = str(b.get("symbol", "")).strip()
                if sym:
                    batch_map[sym] = b
        except Exception as e:
            logger.warning("[hub] stock_hot_rank batch realtime failed: %s", e)

        # 2) sector via industry map
        sector_map: dict[str, str] = {}
        try:
            from ..fetchers.sector_fetcher import get_stock_industry_map
            sector_map = get_stock_industry_map(codes) or {}
        except Exception as e:
            logger.warning("[hub] stock_hot_rank industry map failed: %s", e)

        out: list[dict] = []
        for rank, row in enumerate(rows, start=1):
            code = str(row.get("code") or row.get("symbol") or "").strip()
            b = batch_map.get(code) or {}
            item = dict(row)
            item["rank"] = rank
            item["symbol"] = code
            item["volume"] = b.get("volume", item.get("volume", 0))
            item["turnover"] = b.get("turnover", item.get("turnover", 0))
            if b:
                if b.get("price") is not None:
                    item["price"] = b["price"]
                if b.get("change_pct") is not None:
                    item["change_pct"] = b["change_pct"]
                if b.get("change_amount") is not None:
                    item["change_amount"] = b["change_amount"]
            # 批量行情自带 sector 优先，其次行业映射，最后空串
            item["sector"] = b.get("sector") or sector_map.get(code) or ""
            item["asset_type"] = "A"
            # F2-6 步骤A: tag 字符串解析为 concept_tags 数组（前端 chip 展示）
            item["concept_tags"] = _parse_concept_tags(row.get("tag"))
            out.append(item)
        return out

    def get_sector_popular_stocks(self, plate_code: str) -> list[dict]:
        """板块热门个股。"""
        try:
            from ..fetchers.sector_fetcher import fetch_sector_popular_stocks
            return fetch_sector_popular_stocks(plate_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_popular_stocks(%s) failed: %s", plate_code, e)
            return []

    def get_all_stocks(self) -> list[dict]:
        """全市场股票列表。"""
        try:
            from ..fetchers.sector_fetcher import fetch_all_stocks
            return fetch_all_stocks() or []
        except Exception as e:
            logger.warning("[hub] get_all_stocks failed: %s", e)
            return []

    def get_sector_history(self, sector_code: str) -> list[dict]:
        """板块历史行情。"""
        try:
            from ..fetchers.sector_fetcher import fetch_sector_history
            return fetch_sector_history(sector_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_history(%s) failed: %s", sector_code, e)
            return []

    def get_sector_industry_cls(self, limit: int = 80) -> list[dict]:
        """行业板块分类（轮动）。"""
        try:
            from ..fetchers.sector_fetcher import fetch_sector_industry_cls
            return fetch_sector_industry_cls(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_industry_cls failed: %s", e)
            return []

    def get_a_stock_batch(self, symbols: list[str]) -> list[dict]:
        """A 股批量实时行情。"""
        try:
            from ..fetchers.china_market import fetch_a_stock_batch
            return fetch_a_stock_batch(symbols) or []
        except Exception as e:
            logger.warning("[hub] get_a_stock_batch failed: %s", e)
            return []

    def get_fund_nav(self, symbol: str):
        """基金净值。"""
        try:
            from ..fetchers.china_market import fetch_fund_nav
            return fetch_fund_nav(symbol)
        except Exception as e:
            logger.warning("[hub] get_fund_nav(%s) failed: %s", symbol, e)
            return None

    def get_hk_stock_realtime(self, symbol: str | None = None) -> list[dict]:
        """港股实时行情。"""
        try:
            from ..fetchers.china_market import fetch_hk_stock_realtime
            return fetch_hk_stock_realtime(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_hk_stock_realtime failed: %s", e)
            return []

    def get_us_etf_realtime(self, symbol: str):
        """美股 ETF 实时行情。"""
        try:
            from ..fetchers.global_markets_fetcher import fetch_us_etf_realtime
            return fetch_us_etf_realtime(symbol)
        except Exception as e:
            logger.warning("[hub] get_us_etf_realtime(%s) failed: %s", symbol, e)
            return None

    def get_research_reports(self, symbol: str) -> list[dict]:
        """个股研报。"""
        try:
            from ..fetchers.news_fetcher import fetch_research_reports
            return fetch_research_reports(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_research_reports(%s) failed: %s", symbol, e)
            return []


    # ── Phase 5c: US realtime / history (global_markets_fetcher) ──

    def get_us_stock_realtime(self, symbol: str):
        """美股个股实时（TwelveData 降级链）。"""
        try:
            from ..fetchers.global_markets_fetcher import fetch_realtime
            return fetch_realtime(symbol)
        except Exception as e:
            logger.warning("[hub] get_us_stock_realtime(%s) failed: %s", symbol, e)
            return None

    def get_us_history(self, symbol: str, days: int = 60) -> list[dict]:
        """美股历史 K 线（TwelveData）。"""
        try:
            from ..fetchers.global_markets_fetcher import fetch_history
            return fetch_history(symbol, days) or []
        except Exception as e:
            logger.warning("[hub] get_us_history(%s) failed: %s", symbol, e)
            return []

    def get_us_candles(self, symbol: str, resolution: str = "D") -> list[dict]:
        """美股蜡烛图（Finnhub）。"""
        try:
            from ..fetchers.global_markets_fetcher import fetch_candles
            return fetch_candles(symbol, resolution) or []
        except Exception as e:
            logger.warning("[hub] get_us_candles(%s) failed: %s", symbol, e)
            return []



# Global singleton
market_data_hub = MarketDataHub()
