"""Portfolio service facade — re-exports the split ``app.services.portfolio`` package.

Batch 1 (Step 1) of the giant-file split: implementations moved into
``app/services/portfolio/``; this module only re-exports the original symbols so
every existing ``from app.services.portfolio_service import X`` keeps working
with zero behavior change. The re-export layer is removed in Batch 5 (Step 3)
after consumers migrate to the new sub-module paths.
"""

import logging

from app.services.portfolio import (
    # constants
    FACTOR_LABELS,
    _RSI_HINT,
    _KDJ_HINT,
    _CONFIDENCE_ZH,
    _PRICE_MAP_CACHE,
    _PRICE_MAP_TTL,
    _FUNDAMENTALS_CACHE,
    _strategy_check_cache,
    _COMPOSITE_FACTOR_MAP,
    # formatting
    _factor_hint,
    _factor_strength_band,
    format_factor_summary,
    _factor_value_real,
    _has_real_factor_values,
    _normalize_confidence,
    _compute_confidence,
    # pricing
    build_price_map,
    _build_price_map_async,
    _get_etf_attr,
    _split_symbols,
    _fetch_realtime_price,
    _clear_price_map_cache,
    # crud
    list_etfs,
    add_etf,
    update_etf,
    remove_etf,
    _resolve_tracked_index,
    _recompute_target_weight,
    # allocation
    calculate_allocation,
    recompute_cost_after_trade,
    calculate_weight_drift,
    # pnl
    calculate_daily_pnl,
    calculate_cumulative_pnl,
    # strategy check
    strategy_check,
    _is_failed_result,
    _build_llm_fail_summary,
    _llm_timeout_for,
    _collect_strategy_data,
    _empty_portfolio_diagnosis,
    _attach_composite_decisions,
    _within_symbol_factor_composite,
    _full_pool_factor_composite,
    _build_rule_fallback_holdings_analysis,
    _rule_based_suggestion,
    _build_rule_fallback_report,
    _combine_risk_warnings,
    _compute_risk_warnings,
    _compute_indicators,
    # design / transfer
    apply_portfolio_design,
    export_portfolio,
    import_portfolio,
    market_data_hub,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FACTOR_LABELS",
    "_RSI_HINT",
    "_KDJ_HINT",
    "_CONFIDENCE_ZH",
    "_PRICE_MAP_CACHE",
    "_PRICE_MAP_TTL",
    "_FUNDAMENTALS_CACHE",
    "_strategy_check_cache",
    "_COMPOSITE_FACTOR_MAP",
    "_factor_hint",
    "_factor_strength_band",
    "format_factor_summary",
    "_factor_value_real",
    "_has_real_factor_values",
    "_normalize_confidence",
    "_compute_confidence",
    "build_price_map",
    "_build_price_map_async",
    "_get_etf_attr",
    "_split_symbols",
    "_fetch_realtime_price",
    "_clear_price_map_cache",
    "list_etfs",
    "add_etf",
    "update_etf",
    "remove_etf",
    "_resolve_tracked_index",
    "_recompute_target_weight",
    "calculate_allocation",
    "recompute_cost_after_trade",
    "calculate_weight_drift",
    "calculate_daily_pnl",
    "calculate_cumulative_pnl",
    "strategy_check",
    "_is_failed_result",
    "_build_llm_fail_summary",
    "_llm_timeout_for",
    "_collect_strategy_data",
    "_empty_portfolio_diagnosis",
    "_attach_composite_decisions",
    "_within_symbol_factor_composite",
    "_full_pool_factor_composite",
    "_build_rule_fallback_holdings_analysis",
    "_rule_based_suggestion",
    "_build_rule_fallback_report",
    "_combine_risk_warnings",
    "_compute_risk_warnings",
    "_compute_indicators",
    "apply_portfolio_design",
    "export_portfolio",
    "import_portfolio",
    "market_data_hub",
]
