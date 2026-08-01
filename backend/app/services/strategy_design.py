"""
strategy_design.py — 轻量编排器（v5）

职责：调用数据管道（market_data_hub）→ 调用纯策略引擎（engine/）→ 持久化返回。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..engine.allocation_engine import allocate as engine_allocate
from ..engine.budgets import STRATEGY_META
from ..engine.rationale import build_rationale
from ..engine.risk_controls import apply_risk_controls

logger = logging.getLogger(__name__)

# Z11: 静态兜底核心池（非交易时段 / 数据管道断裂时使用）
STATIC_CORE_POOL = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "510050", "name": "上证50ETF", "layer": "core",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "511010", "name": "国债ETF", "layer": "defense",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "159915", "name": "创业板ETF", "layer": "satellite",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "588000", "name": "科创50ETF", "layer": "satellite",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
]

# Z11: 静态政策标识因子之外，静态池每层内等权分配
def _build_static_pool_strategies(capital: float) -> list[dict]:
    """基于 STRATEGY_META.layer_budget 等权分配静态核心池，生成 3 套方案。

    Z11: 不再硬编码权重（0.4/0.35/0.25），统一引用 STRATEGY_META。
    """
    strategies: list[dict] = []
    for profile in ("defensive", "balanced", "aggressive"):
        meta = STRATEGY_META.get(profile, STRATEGY_META["balanced"])
        budget = meta.get("layer_budget", {"core": 0.40, "satellite": 0.30, "defense": 0.10})

        layer_groups: dict[str, list[dict]] = {"core": [], "satellite": [], "defense": []}
        for e in STATIC_CORE_POOL:
            layer = e.get("layer")
            if isinstance(layer, str) and layer in layer_groups:
                layer_groups[layer].append(e)

        allocs: list[dict] = []
        for layer, items in layer_groups.items():
            if not items:
                continue
            layer_weight = budget.get(layer, 0.0)
            per_item = round(layer_weight / len(items), 4)
            for it in items:
                allocs.append({
                    "symbol": it["symbol"],
                    "name": it["name"],
                    "layer": layer,
                    "weight": per_item,
                    "target_amount": round(capital * per_item, 2),
                    "selection_rationale": "静态核心池兜底（非交易时段/数据受限）",
                })

        used = sum(a["weight"] for a in allocs)
        cash = round(1.0 - used, 4)
        if cash > 0:
            allocs.append({
                "symbol": "CASH", "name": "现金", "layer": "cash",
                "weight": cash, "target_amount": round(capital * cash, 2),
                "selection_rationale": "流动性管理",
            })

        strategies.append({
            "id": profile,
            "name": meta.get("label", profile),
            "description": f"{meta.get('positioning', '')}（静态池兜底方案）",
            "risk_profile": profile,
            "expected_return": f"{meta.get('expected_return', 0.1)*100:.0f}-{meta.get('expected_return', 0.1)*100+4:.0f}%",
            "expected_volatility": "12-20%",
            "etfs": allocs,
        })
    return strategies


async def generate_enhanced_design(
    capital: float = 500000,
    constraints: dict | None = None,
    market: str = "A",
) -> dict:
    """
    v5 编排器：数据管道 → 策略引擎 → 持久化返回。

    Phase 5.1: 增加 market 参数入口，当前仅 A 股有候选池。
    """
    import time
    start_time = time.monotonic()
    constraints = constraints or {}
    _elapsed_logged = False

    # 1. 刷新数据管道（pipeline Stage 1 负责超时保护）
    from ..services.market_data_hub import market_data_hub
    _t1 = time.monotonic()
    try:
        await market_data_hub.refresh()
    except Exception as e:
        logger.warning("[strategy_design] market_data_hub.refresh failed — pool may be stale; _by_code=%d: %s",
                       len(market_data_hub._by_code), e)
    _t2 = time.monotonic()
    if _t2 - _t1 > 0.1:
        logger.info("[strategy_design] refresh took %.2fs, elapsed_total=%.2fs",
                     _t2 - _t1, time.monotonic() - start_time)

    # 2. 读取管道产出
    try:
        factor_matrix = market_data_hub.get_factor_matrix() or {}
    except Exception as e:
        logger.warning("[strategy_design] get_factor_matrix failed: %s", e)
        factor_matrix = {}
    candidates = {
        "core": market_data_hub.get_pool("core") or [],
        "satellite": market_data_hub.get_pool("satellite") or [],
        "defense": market_data_hub.get_pool("defense") or [],
    }

    # 2b. 检查候选池是否为空（Z11: 空池 → 静态池兜底 + degradation 标记）
    total_candidates = sum(len(v) for v in candidates.values())
    factor_matrix_empty = not bool(factor_matrix)
    pool_empty = total_candidates == 0
    static_pool_used: list[str] = []
    if total_candidates == 0:
        logger.warning("[strategy_design] empty candidate pool, falling back to static pool")
        pool_attr = getattr(market_data_hub, 'etf_pool', None)
        static_etfs: list[dict] = pool_attr if isinstance(pool_attr, list) else STATIC_CORE_POOL
        candidates = {
            "core": [e for e in static_etfs if e.get("layer") == "core"],
            "satellite": [e for e in static_etfs if e.get("layer") == "satellite"],
            "defense": [e for e in static_etfs if e.get("layer") == "defense"],
        }
        total_candidates = sum(len(v) for v in candidates.values())
        static_pool_used = [str(e.get("symbol", "")) for e in static_etfs if e.get("symbol")]

    market_regime = market_data_hub.get_market_regime() or "range_bound"
    market_context = await _build_market_context(market_data_hub)

    # Z11: 降级模式判定（normal / static_pool / partial_data）
    _now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _degradation(mode: str, reason: str) -> dict:
        return {
            "mode": mode,
            "reason": reason,
            "factor_matrix_empty": factor_matrix_empty,
            "pool_empty": pool_empty,
            "static_pool_used": static_pool_used if mode == "static_pool" else [],
            "timestamp": _now_iso,
        }

    # 静态池兜底：直接生成 3 套方案（不进 allocate，避免二次降级）
    if pool_empty:
        strategies = _build_static_pool_strategies(capital)
        elapsed = time.monotonic() - start_time
        logger.info("[strategy_design] static pool fallback generated %d strategies in %.1fs",
                    len(strategies), elapsed)
        return {
            "strategies": strategies,
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {
                "version": "v5-engine-static-pool",
                "elapsed_seconds": round(elapsed, 1),
                "regime": market_regime,
                "fallback": True,
            },
            "degradation": _degradation(
                "static_pool",
                "非交易时段/数据管道为空：候选池为空，使用静态核心池兜底",
            ),
        }

    try:
        # 3. 策略引擎：一次调用生成所有方案
        _t3 = time.monotonic()
        # 扁平化候选池：allocate() 预期 list[dict]，每项含 layer 字段
        flat_candidates: list = []
        for layer_list in candidates.values():
            flat_candidates.extend(layer_list)
        if _t3 - start_time > 0.2:
            logger.info("[strategy_design] pre-allocate %.2fs candidates=%d",
                         _t3 - start_time, len(flat_candidates))
        strategies_raw = engine_allocate(
            risk_profile="balanced",
            factor_matrix=factor_matrix,
            candidates=flat_candidates,
            regime=market_regime,
        )

        _t4 = time.monotonic()
        if _t4 - _t3 > 0.1:
            logger.info("[strategy_design] allocate took %.2fs", _t4 - _t3)

        # 4. 转换为前端期望的 etfs 字段名
        strategies = []
        for s in strategies_raw:
            allocs = s.pop("allocations", [])
            # Apply risk controls before assembling
            risk_allocations = apply_risk_controls([{"allocations": allocs}], factor_matrix)
            allocs = risk_allocations[0]["allocations"] if risk_allocations else allocs

            # enrich rationale using engine/rationale.py
            for a in allocs:
                if a.get("symbol") == "CASH":
                    continue
                code = a["symbol"]
                sym_meta = _find_candidate_meta(code, candidates)
                a["selection_rationale"] = build_rationale(
                    code=code,
                    layer=a.get("layer", "satellite"),
                    strategy=s.get("id", "balanced"),
                    meta=sym_meta,
                    factor_scores=a.get("factor_breakdown", {}),
                    regime=market_regime,
                    industry=sym_meta.get("industry", "") if sym_meta else None,
                )

            # S6: Inject daily_change_pct and price from market_data_hub market data
            for a in allocs:
                if a.get("symbol") == "CASH":
                    continue
                code = a["symbol"]
                pool_entry = market_data_hub.get_by_code(code) if hasattr(market_data_hub, 'get_by_code') else {}
                if pool_entry:
                    dcp = pool_entry.get("change_pct") or pool_entry.get("daily_change_pct")
                    if dcp is not None:
                        a["daily_change_pct"] = dcp
                    price = pool_entry.get("price") or pool_entry.get("last_price")
                    if price is not None:
                        a["price"] = price
                    fs = pool_entry.get("factor_score")
                    if fs is not None:
                        a["factor_score"] = fs
                # Fallback to factor_matrix
                if a.get("daily_change_pct") is None:
                    fm = factor_matrix.get(code, {}) if isinstance(factor_matrix, dict) else {}
                    if fm:
                        dcp = fm.get("change_pct") or fm.get("daily_change_pct")
                        if dcp is not None:
                            a["daily_change_pct"] = dcp

            # Calculate cash
            total_weight = sum(a.get("weight", 0) for a in allocs if a.get("symbol") != "CASH")
            cash_weight = round(1.0 - total_weight, 4)
            if cash_weight > 0:
                allocs.append({
                    "symbol": "CASH", "name": "现金", "layer": "cash",
                    "weight": cash_weight, "selection_rationale": "流动性管理",
                })

            s["etfs"] = allocs
            # Add target_amount for each allocation
            for a in s["etfs"]:
                a["target_amount"] = round(capital * a.get("weight", 0), 2)
            strategies.append(s)

        # 5. target_amount 一致性校验
        _validate_target_amount_consistency(strategies, capital)

        # 6. 组装返回
        elapsed = time.monotonic() - start_time
        logger.info("[strategy_design] v5 orchestrator generated %d strategies in %.1fs",
                    len(strategies), elapsed)

        # Z11: 部分候选缺因子分 → partial_data 模式
        missing_symbols: list[str] = []
        for layer_list in candidates.values():
            for c in layer_list:
                if not isinstance(c, dict):
                    continue
                sym = c.get("symbol")
                if sym and sym not in (factor_matrix or {}):
                    missing_symbols.append(str(sym))
        partial_data = bool(missing_symbols) and not pool_empty
        return {
            "strategies": strategies,
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {
                "version": "v5-engine",
                "elapsed_seconds": round(elapsed, 1),
                "regime": market_regime,
            },
            # Z11: 正常路径也暴露 degradation（mode=normal / partial_data）
            "degradation": _degradation(
                "partial_data" if partial_data else "normal",
                "部分候选标的缺因子分：缺失因子按 0 填充"
                if partial_data else "正常数据管道",
            ),
        }
    except (asyncio.TimeoutError, ValueError, KeyError, ConnectionError, OSError, RuntimeError) as e:
        logger.exception("[strategy_design] generate_enhanced_design failed — attempting static pool fallback")
        # Z11: Fallback to static ETF pool when design pipeline fails
        try:
            fallback_strategies = _build_static_pool_strategies(capital)
            elapsed = time.monotonic() - start_time
            logger.info("[strategy_design] fallback generated %d strategies in %.1fs",
                        len(fallback_strategies), elapsed)
            return {
                "strategies": fallback_strategies,
                "market_context": market_context,
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "design_metadata": {
                    "version": "v5-engine-static-pool",
                    "elapsed_seconds": round(elapsed, 1),
                    "regime": market_regime,
                    "fallback": True,
                },
                "warning": "使用静态池兜底，因子数据不可用",
                "degradation": _degradation(
                    "static_pool",
                    f"设计管线异常（{type(e).__name__}），使用静态核心池兜底",
                ),
            }
        except Exception as fallback_e:
            logger.exception("[strategy_design] fallback also failed")
            return {
                "strategies": [],
                "market_context": market_context,
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "design_metadata": {"version": "v5-engine", "elapsed_seconds": round(time.monotonic() - start_time, 1), "regime": market_regime},
                "error": "策略生成失败",
                "detail": str(e),
            }


# OPT-04: 资金流向并发限流，最多 8 个并发请求
_fund_flow_sem = asyncio.Semaphore(8)


async def _compute_fund_flow(market_data_hub) -> dict:
    """聚合全市场候选 ETF 资金流向（带并发限流 + 熔断器保护）。

    OPT-02: push2 熔断时快速返回空数据（不等 8s 超时）。
    OPT-04: Semaphore(8) 限制并发，防止线程池耗尽。

    返回:
      {"total_net_inflow": float, "positive_flow_count": int,
       "negative_flow_count": int, "total_symbols": int}
    """
    # OPT-02: 熔断器检查，push2 不可用时直接返回空数据
    from ..services.source_registry import registry as _source_registry
    import time
    push2_h = _source_registry._health("push2delay.eastmoney.com")
    if not push2_h.available(time.time()):
        logger.info("[strategy_design] _compute_fund_flow: push2 circuit open, returning empty")
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    from ..core.async_utils import run_sync

    pool = market_data_hub.get_pool()
    if not isinstance(pool, dict):
        logger.warning(
            "[strategy_design] _compute_fund_flow: pool is not a dict (%s), skipping",
            type(pool).__name__,
        )
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    # 收集所有 symbol
    all_symbols = []
    for layer, items in pool.items():
        for item in items:
            sym = item.get("symbol", "")
            if sym:
                all_symbols.append(sym)

    if not all_symbols:
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    # 并发获取所有 fund flow（Semaphore 限流）
    from ..services.market_data_hub import market_data_hub

    async def _fetch_one(sym: str) -> dict | None:
        async with _fund_flow_sem:  # OPT-04: 最多 8 个并发
            try:
                return await run_sync(market_data_hub.get_fund_flow, sym, timeout=8)
            except Exception:
                return None

    results = await asyncio.gather(*[_fetch_one(s) for s in all_symbols],
                                  return_exceptions=True)

    total_net_inflow = 0.0
    positive_count = 0
    negative_count = 0

    for flow in results:
        if isinstance(flow, dict) and flow.get("main_net_inflow") is not None:
            inflow = flow["main_net_inflow"]
            total_net_inflow += inflow
            if inflow >= 0:
                positive_count += 1
            else:
                negative_count += 1

    return {
        "total_net_inflow": total_net_inflow,
        "positive_flow_count": positive_count,
        "negative_flow_count": negative_count,
        "total_symbols": len(all_symbols),
    }


async def _build_market_context(market_data_hub) -> dict:
    """从 market_data_hub 构建市场上下文（真异步）。

    F1-3: ①index_realtime 为空时从全球指数分组兜底（缓存未刷新场景）；
    ②benchmark_stocks 填充领涨/领跌指数成分（此前恒为空数组，LLM 无大盘龙头信号）。
    """
    fund_flow = await _compute_fund_flow(market_data_hub)

    index_realtime = market_data_hub.get_index_realtime() or []
    # F1-3: 缓存未刷新/为空时从全球指数分组兜底（A 股区域）
    if not index_realtime:
        try:
            global_idx = await asyncio.wait_for(market_data_hub.get_global_indices(), timeout=15) or {}
            index_realtime = global_idx.get("A股", []) or []
        except Exception as e:
            logger.debug("[strategy_design] global indices fallback failed: %s", e)

    # F1-3: 领涨/领跌板块头部成分作为 benchmark_stocks（龙头股信号）
    benchmark_stocks: list[dict] = []
    try:
        sector_momentum = market_data_hub.get_sector_momentum() or []
        top_sectors = sorted(
            [s for s in sector_momentum if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: -s["change_pct"],
        )[:2] + sorted(
            [s for s in sector_momentum if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: s["change_pct"],
        )[:1]
        for sec in top_sectors:
            code = sec.get("sector_code") or sec.get("code") or ""
            if not code:
                continue
            try:
                stocks = market_data_hub.get_sector_stocks(code) or []
                for st in stocks[:3]:
                    benchmark_stocks.append({
                        "symbol": st.get("stock_code") or st.get("code", ""),
                        "name": st.get("stock_name") or st.get("name", ""),
                        "sector": sec.get("sector_name") or sec.get("name", ""),
                    })
            except Exception:
                continue
    except Exception as e:
        logger.debug("[strategy_design] benchmark_stocks build failed: %s", e)

    return {
        "market_regime": market_data_hub.get_market_regime() or "range_bound",
        "market_sentiment": market_data_hub.get_market_sentiment() or {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": index_realtime,
        "sector_momentum": market_data_hub.get_sector_momentum() or [],
        "fund_flow": fund_flow,
        "benchmark_stocks": benchmark_stocks[:9],
    }


def _validate_target_amount_consistency(strategies: list[dict], capital: float) -> list[str]:
    """验证所有策略的 target_amount = capital * weight，返回不一致的警告列表。"""
    warnings: list[str] = []
    for s in strategies:
        sid = s.get("id", "unknown")
        for a in s.get("etfs", []):
            if a.get("symbol") == "CASH":
                continue
            w = a.get("weight", 0)
            expected = round(capital * w, 2)
            actual = a.get("target_amount", 0)
            if abs(actual - expected) > 0.01:
                msg = (
                    f"[target_amount] {sid}/{a.get('symbol')}: "
                    f"expected {expected} (capital={capital} * weight={w}), "
                    f"got {actual}"
                )
                warnings.append(msg)
                logger.warning(msg)
    return warnings


def _find_candidate_meta(symbol: str, candidates: dict) -> dict | None:
    """在候选池中查找 ETF 元数据。"""
    for layer_list in candidates.values():
        for c in layer_list:
            if c.get("symbol") == symbol:
                return c
    return None
