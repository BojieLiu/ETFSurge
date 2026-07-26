"""
strategy_design.py — 轻量编排器（v5）

职责：调用数据管道（pool_manager）→ 调用纯策略引擎（engine/）→ 持久化返回。
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
    from ..services.pool_manager import pool_manager
    _t1 = time.monotonic()
    try:
        await pool_manager.refresh()
    except Exception as e:
        logger.warning("[strategy_design] pool_manager.refresh failed — pool may be stale; _by_code=%d: %s",
                       len(pool_manager._by_code), e)
    _t2 = time.monotonic()
    if _t2 - _t1 > 0.1:
        logger.info("[strategy_design] refresh took %.2fs, elapsed_total=%.2fs",
                     _t2 - _t1, time.monotonic() - start_time)

    # 2. 读取管道产出
    factor_matrix = pool_manager.get_factor_matrix() or {}
    candidates = {
        "core": pool_manager.get_pool("core") or [],
        "satellite": pool_manager.get_pool("satellite") or [],
        "defense": pool_manager.get_pool("defense") or [],
    }

    # 2b. 检查候选池是否为空
    total_candidates = sum(len(v) for v in candidates.values())
    if total_candidates == 0:
        logger.warning("[strategy_design] empty candidate pool, returning early error")
        return {
            "strategies": [],
            "market_context": _build_market_context(pool_manager),
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {"version": "v5-engine", "elapsed_seconds": 0, "regime": "unknown"},
            "error": "无候选标的",
            "detail": "数据管道未能生成候选池，请检查数据源连接或稍后重试",
        }

    market_regime = pool_manager.get_market_regime() or "range_bound"
    market_context = _build_market_context(pool_manager)

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

        # 5. 组装返回
        elapsed = time.monotonic() - start_time
        logger.info("[strategy_design] v5 orchestrator generated %d strategies in %.1fs",
                    len(strategies), elapsed)

        return {
            "strategies": strategies,
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {
                "version": "v5-engine",
                "elapsed_seconds": round(elapsed, 1),
                "regime": market_regime,
            },
        }
    except (asyncio.TimeoutError, ValueError, KeyError, ConnectionError, OSError) as e:
        logger.exception("[strategy_design] generate_enhanced_design failed")
        return {
            "strategies": [],
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {"version": "v5-engine", "elapsed_seconds": round(time.monotonic() - start_time, 1), "regime": market_regime},
            "error": "策略生成失败",
            "detail": str(e),
        }


def _compute_fund_flow(pool_manager) -> dict:
    """聚合全市场候选 ETF 资金流向。

    返回:
      {"total_net_inflow": float, "positive_flow_count": int, "negative_flow_count": int, "total_symbols": int}
    """
    result = {
        "total_net_inflow": 0.0,
        "positive_flow_count": 0,
        "negative_flow_count": 0,
        "total_symbols": 0,
    }
    from ..fetchers.fundamental_fetcher import fetch_fund_flow
    from ..utils.sync_helpers import run_sync_in_thread
    pool = pool_manager.get_pool()
    if not isinstance(pool, dict):
        logger.warning("[strategy_design] _compute_fund_flow: pool is not a dict (%s), skipping", type(pool).__name__)
        return result
    for layer, items in pool.items():
        for item in items:
            sym = item.get("symbol", "")
            if not sym:
                continue
            result["total_symbols"] += 1
            flow = run_sync_in_thread(fetch_fund_flow, sym)
            if flow and flow.get("main_net_inflow") is not None:
                inflow = flow["main_net_inflow"]
                result["total_net_inflow"] += inflow
                if inflow >= 0:
                    result["positive_flow_count"] += 1
                else:
                    result["negative_flow_count"] += 1
    return result


def _build_market_context(pool_manager) -> dict:
    """从 pool_manager 构建市场上下文。"""
    fund_flow = _compute_fund_flow(pool_manager)
    return {
        "market_regime": pool_manager.get_market_regime() or "range_bound",
        "market_sentiment": pool_manager.get_market_sentiment() or {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": pool_manager.get_index_realtime() or [],
        "sector_momentum": pool_manager.get_sector_momentum() or [],
        "fund_flow": fund_flow,
        "benchmark_stocks": [],
    }


def _find_candidate_meta(symbol: str, candidates: dict) -> dict | None:
    """在候选池中查找 ETF 元数据。"""
    for layer_list in candidates.values():
        for c in layer_list:
            if c.get("symbol") == symbol:
                return c
    return None
