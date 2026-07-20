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
) -> dict:
    """
    v5 编排器：数据管道 → 策略引擎 → 持久化返回。
    """
    import time
    start_time = time.monotonic()
    constraints = constraints or {}

    # 1. 刷新数据管道
    from ..services.pool_manager import pool_manager
    try:
        await asyncio.wait_for(pool_manager.refresh(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("[strategy_design] pool_manager.refresh timed out, using cached")
    except Exception as e:
        logger.error("[strategy_design] pool_manager.refresh failed: %s", e)

    # 2. 读取管道产出
    factor_matrix = pool_manager.get_factor_matrix() or {}
    candidates = {
        "core": pool_manager.get_pool("core") or [],
        "satellite": pool_manager.get_pool("satellite") or [],
        "defense": pool_manager.get_pool("defense") or [],
    }
    market_regime = pool_manager.get_market_regime() or "range_bound"
    market_context = _build_market_context(pool_manager)

    # 3. 策略引擎：一次调用生成所有方案
    strategies_raw = engine_allocate(
        factor_matrix=factor_matrix,
        candidates=candidates,
        regime=market_regime,
    )

    # 4. 转换为前端期望的 etfs 字段名
    strategies = []
    for s in strategies_raw:
        allocs = s.pop("allocations", [])
        # Apply risk controls before assembling
        risk_allocations = apply_risk_controls([{"etfs": allocs}], factor_matrix, candidates)
        allocs = risk_allocations[0]["etfs"] if risk_allocations else allocs

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


def _build_market_context(pool_manager) -> dict:
    """从 pool_manager 构建市场上下文。"""
    return {
        "market_regime": pool_manager.get_market_regime() or "range_bound",
        "market_sentiment": pool_manager.get_market_sentiment() or {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": pool_manager.get_index_realtime() or [],
        "sector_momentum": pool_manager.get_sector_momentum() or [],
        "benchmark_stocks": [],
    }


def _find_candidate_meta(symbol: str, candidates: dict) -> dict | None:
    """在候选池中查找 ETF 元数据。"""
    for layer_list in candidates.values():
        for c in layer_list:
            if c.get("symbol") == symbol:
                return c
    return None
