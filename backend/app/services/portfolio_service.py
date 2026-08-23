"""Portfolio service facade — re-exports the split ``app.services.portfolio`` package.

Batch 1 (Step 1) of the giant-file split: implementations moved into
``app/services/portfolio/``; this module only re-exports the original symbols so
every existing ``from app.services.portfolio_service import X`` keeps working
with zero behavior change. The re-export layer is removed in Batch 5 (Step 3)
after consumers migrate to the new sub-module paths.
"""

import logging

from app.services.portfolio import (
    _COMPOSITE_FACTOR_MAP,
    _CONFIDENCE_ZH,
    _FUNDAMENTALS_CACHE,
    _KDJ_HINT,
    _PRICE_MAP_CACHE,
    _PRICE_MAP_TTL,
    _RSI_HINT,
    # constants
    FACTOR_LABELS,
    _attach_composite_decisions,
    _build_llm_fail_summary,
    _build_price_map_async,
    _build_rule_fallback_holdings_analysis,
    _build_rule_fallback_report,
    _clear_price_map_cache,
    _collect_strategy_data,
    _combine_risk_warnings,
    _compute_confidence,
    _compute_indicators,
    _compute_risk_warnings,
    _empty_portfolio_diagnosis,
    # formatting
    _factor_hint,
    _factor_strength_band,
    _factor_value_real,
    _fetch_realtime_price,
    _full_pool_factor_composite,
    _get_etf_attr,
    _has_real_factor_values,
    _is_failed_result,
    _llm_timeout_for,
    _normalize_confidence,
    _recompute_target_weight,
    _resolve_tracked_index,
    _rule_based_suggestion,
    _split_symbols,
    _strategy_check_cache,
    _within_symbol_factor_composite,
    add_etf,
    # design / transfer
    apply_portfolio_design,
    # pricing
    build_price_map,
    # allocation
    calculate_allocation,
    calculate_cumulative_pnl,
    # pnl
    calculate_daily_pnl,
    calculate_weight_drift,
    export_portfolio,
    format_factor_summary,
    import_portfolio,
    # crud
    list_etfs,
    market_data_hub,
    recompute_cost_after_trade,
    remove_etf,
    # strategy check
    strategy_check,
    update_etf,
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
