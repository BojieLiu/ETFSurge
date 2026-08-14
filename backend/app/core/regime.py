"""regime — 市态归一化共用（round23 §10.2 E2）。

origin: market_data_hub._normalize_regime（外部 regime → 简化 key 映射）+
        risk_controls._BEARISH_REGIMES（熊市判定集合）——两份此前各自维护同口径。

单一口径：本模块为唯一实现，market_data_hub 与 risk_controls 都从本模块取，
消除「同口径」注释式同步（漂移风险）。
"""

# 外部 detect_market_regime() 返回值 → _LAYER_WEIGHTS 简化 key
REGIME_MAP: dict[str, str] = {
    "bull_strong": "bull",
    "bull_weakening": "bull",
    "range_bound": "neutral",
    "neutral": "neutral",
    "correction": "correction",
    "bear": "bear",
    "defensive_rotate": "neutral",
    "panic": "bear",
}

# 熊市/回调/恐慌——核心层市态绝对防线（apply_core_bear_growth_trim）判定集合
BEARISH_REGIMES: frozenset[str] = frozenset({"bear", "correction", "panic"})


def normalize_regime(regime: str) -> str:
    """外部市态 → 简化 key（bull / neutral / correction / bear）。"""
    return REGIME_MAP.get(regime, "neutral")


def is_bearish_regime(regime: str) -> bool:
    """简化的 regime 是否为熊市/回调/恐慌（触发核心层防御）。"""
    return regime in BEARISH_REGIMES
