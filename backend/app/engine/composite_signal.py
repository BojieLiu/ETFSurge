"""Pure composite-signal helpers — extracted from MarketDataHub (Batch 4).

Zero-I/O functions moved out of ``app/services/market_data_hub.py`` (plan A
Step 2). ``compute_composite`` accepts injectable helper callables so the facade
can pass its instance methods (preserving mock.patch semantics on the facade),
while direct callers get the built-in pure implementations.

Dependency direction: ``engine/`` (pure) <- ``hub/*`` <- facade.
"""

import math
from typing import Any, Callable

# Layer-regime weight tables (single source of truth; hub/_common re-exports)
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


def _normalize_regime(regime: str) -> str:
    """C2: 将市场状态值映射到 _LAYER_WEIGHTS 表的 key（委托 core/regime）。"""
    from app.core.regime import normalize_regime as _nr
    return _nr(regime)


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


def _pct_rank(value: float, series: list[float]) -> float:
    """层内截面百分位 [0,1]（含并列按半计）。"""
    if not series:
        return 0.0
    n = len(series)
    below = sum(1 for v in series if v < value)
    equal = sum(1 for v in series if v == value)
    return (below + 0.5 * equal) / n


# Public aliases (external callers use the plain names; compute_composite keeps
# the underscore names as fallback defaults without parameter shadowing).
normalize_regime = _normalize_regime
is_market_hours = _is_market_hours
pct_rank = _pct_rank


def compute_composite(
    item: dict[str, Any],
    layer: str,
    regime: str = "neutral",
    layer_amounts: list[float] | None = None,
    layer_scales: list[float] | None = None,
    *,
    is_market_hours: Callable[[], bool] | None = None,
    normalize_regime: Callable[[str], str] | None = None,
    pct_rank: Callable[[float, list[float]], float] | None = None,
) -> float:
    """按层+市况计算综合得分。

    非交易时段（P6 fix-plan-pool）: 流动性数据可能为昨日值，降低流动性权重，
    以规模排序为主。core/satellite/defense 三层传层内截面向量
    （layer_amounts/layer_scales）时用百分位量纲；否则回退旧 ``*1e-9`` 路径。

    ``is_market_hours`` / ``normalize_regime`` / ``pct_rank`` 可注入（门面传实例方法，
    保持 mock.patch 语义）；缺省用本模块纯实现。
    """
    is_market_hours = is_market_hours or _is_market_hours
    normalize_regime = normalize_regime or _normalize_regime
    pct_rank = pct_rank or _pct_rank

    factor_scores = item.get("factor_scores", {})
    # P0-4: 仅聚合顶层键求和（避免原始点分键双倍计数 + RSI=50 主导排序）
    AGGREGATE_KEYS = {"technical", "momentum", "valuation", "sentiment"}
    factor_sum = sum(v for k, v in factor_scores.items() if k in AGGREGATE_KEYS) if factor_scores else 0
    amount = float(item.get("amount", 0) or 0)
    scale = float(item.get("fund_scale", 0) or 0)
    opp_score = float(item.get("composite_score", 0.5))

    layer_weights = _LAYER_WEIGHTS.get(layer, {})
    regime_key = normalize_regime(regime)
    w = layer_weights.get(regime_key, layer_weights.get("neutral", _BASE_WEIGHTS))

    # P6: 非交易时段，流动性权重减半（数据可能为昨日值）
    is_market_open = is_market_hours()
    liquidity_weight = w.get("liquidity", 0)
    if not is_market_open:
        liquidity_weight *= 0.5
        scale_weight = w.get("scale", 0) + w.get("liquidity", 0) * 0.5
    else:
        scale_weight = w.get("scale", 0)

    if layer in ("core", "satellite", "defense", "opportunistic"):
        if layer in ("core", "satellite", "defense") and layer_amounts is not None:
            score = w["factor"] * math.tanh(factor_sum / 6.0)
            score += liquidity_weight * pct_rank(amount, layer_amounts)
            score += scale_weight * pct_rank(scale, layer_scales or [])
        else:
            score = w["factor"] * factor_sum
            score += liquidity_weight * amount * 1e-9
            score += scale_weight * scale * 1e-9
        if layer != "core":
            score += w.get("opp", 0) * opp_score
    else:
        score = amount * 1e-9  # research: liquidity only

    return score
