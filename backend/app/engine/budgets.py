"""
ETF Surge — Strategy budgets and meta-configuration.

Pure functions only — no I/O, no database, no HTTP.
"""

from __future__ import annotations

from typing import Any


# ── Strategy metadata ───────────────────────────────────────────────
STRATEGY_META: dict[str, dict[str, Any]] = {
    "defensive": {
        "id": "defensive",
        "label": "防御型",
        "color": "#43A047",
        "portfolio_name": "防御稳健组合",
        "positioning": "低波稳健配置，控制回撤，适合保守风险偏好者",
        "expected_return": 0.08,
        "max_drawdown": -0.12,
        "sharpe_ratio": 1.2,
        "layer_budget": {"core": 0.50, "satellite": 0.15, "defense": 0.05},
        "expected_characteristics": "预期年化波动10-12%，最大回撤区间10-12%",
    },
    "balanced": {
        "id": "balanced",
        "label": "平衡型",
        "color": "#1976D2",
        "portfolio_name": "均衡配置组合",
        "positioning": "核心稳健+卫星增强，攻守兼备",
        "expected_return": 0.11,
        "max_drawdown": -0.18,
        "sharpe_ratio": 1.0,
        "layer_budget": {"core": 0.50, "satellite": 0.25, "defense": 0.05},
        "expected_characteristics": "预期年化波动15-18%，最大回撤区间15-18%",
    },
    "aggressive": {
        "id": "aggressive",
        "label": "进攻型",
        "color": "#E53935",
        "portfolio_name": "锐意进取组合",
        "positioning": "高弹性行业/主题权重大，承受较大回撤博取超额",
        "expected_return": 0.16,
        "max_drawdown": -0.35,
        "sharpe_ratio": 0.8,
        "layer_budget": {"core": 0.50, "satellite": 0.35, "defense": 0.05},
        "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
    },
}


def dynamic_layer_budget(risk_profile: str, regime: str) -> dict[str, float]:
    """
    Adjust layer budgets dynamically based on market regime.

    Args:
        risk_profile: One of "defensive", "balanced", "aggressive".
        regime: Market regime label (e.g. "bear", "bull_strong", "range_bound").

    Returns:
        {"core": float, "satellite": float, "defense": float}
        Cash ratio = 1 - sum(values).
    """
    if risk_profile not in STRATEGY_META:
        risk_profile = "balanced"
    base = dict(STRATEGY_META[risk_profile]["layer_budget"])

    # ── Defensive rotate / bear / correction: boost defense ──
    if regime in ("defensive_rotate", "bear", "correction"):
        shift = {"defensive": 0.10, "balanced": 0.08, "aggressive": 0.05}.get(
            risk_profile, 0.05
        )
        base["defense"] = min(base.get("defense", 0.05) + shift, 0.30)
        base["satellite"] = max(base.get("satellite", 0.20) - shift * 0.5, 0.10)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)

        # correction / bear: extra satellite reduction
        if regime in ("correction", "bear"):
            sat_reduce = {
                "defensive": 0.00,
                "balanced": 0.03,
                "aggressive": 0.08,
            }.get(risk_profile, 0.00)
            if sat_reduce > 0:
                base["satellite"] = max(base["satellite"] - sat_reduce, 0.08)
                base["core"] = min(base["core"] + sat_reduce * 0.4, 0.60)

        # bear: extra cash protection
        if regime == "bear":
            cash_boost = {
                "defensive": 0.05,
                "balanced": 0.05,
                "aggressive": 0.10,
            }.get(risk_profile, 0.05)
            base["core"] = max(base["core"] - cash_boost * 0.3, 0.30)
            base["satellite"] = max(base["satellite"] - cash_boost * 0.3, 0.05)

    # ── Strong bull: boost satellite ──
    elif regime in ("bull_strong",):
        shift = {"defensive": 0.05, "balanced": 0.08, "aggressive": 0.10}.get(
            risk_profile, 0.05
        )
        base["satellite"] = min(base.get("satellite", 0.20) + shift, 0.50)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)
        base["defense"] = max(base.get("defense", 0.05) - shift * 0.3, 0.03)

    return base


def adjust_expected_return(
    risk_profile: str,
    regime: str,
    macro: dict[str, Any] | None = None,
) -> float:
    """
    Adjust expected annual return based on market regime.

    Panic/bear lowers expectations; bull markets raise them.

    Args:
        risk_profile: One of "defensive", "balanced", "aggressive".
        regime: Market regime label.
        macro: Optional macro context (reserved for future refinement).

    Returns:
        Adjusted annual return as a float (e.g. 0.08 for 8%).
    """
    _ = macro  # reserved for future macro-based adjustments
    if risk_profile not in STRATEGY_META:
        risk_profile = "balanced"
    base_return = STRATEGY_META[risk_profile]["expected_return"]

    adjustment: dict[str, float] = {
        "panic": -0.04,
        "bear": -0.03,
        "correction": -0.02,
        "defensive_rotate": -0.01,
        "range_bound": 0.0,
        "bull_weakening": 0.01,
        "bull_strong": 0.02,
    }
    adj = adjustment.get(regime, 0.0)
    return round(max(base_return + adj, 0.02), 4)
