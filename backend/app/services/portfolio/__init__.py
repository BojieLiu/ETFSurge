"""Portfolio service package — split from portfolio_service.py (Batch 1).

Each sub-module implements one responsibility cluster. This ``__init__`` re-exports
every public + private symbol that historically lived in
``app.services.portfolio_service`` so existing imports keep working unchanged.

Import order matters: ``crud`` lazily imports ``recompute_cost_after_trade`` from
``allocation`` inside ``update_etf`` to break the crud <-> allocation cycle.
"""

from app.services.market_data_hub import market_data_hub
from app.services.portfolio.allocation import (
    calculate_allocation,
    calculate_weight_drift,
    recompute_cost_after_trade,
)
from app.services.portfolio.crud import (
    _recompute_target_weight,
    _resolve_tracked_index,
    add_etf,
    list_etfs,
    remove_etf,
    update_etf,
)
from app.services.portfolio.design import apply_portfolio_design
from app.services.portfolio.formatting import (
    _CONFIDENCE_ZH,
    _KDJ_HINT,
    _RSI_HINT,
    FACTOR_LABELS,
    _compute_confidence,
    _factor_hint,
    _factor_strength_band,
    _factor_value_real,
    _has_real_factor_values,
    _normalize_confidence,
    format_factor_summary,
)
from app.services.portfolio.pnl import (
    calculate_cumulative_pnl,
    calculate_daily_pnl,
)
from app.services.portfolio.pricing import (
    _FUNDAMENTALS_CACHE,
    _PRICE_MAP_CACHE,
    _PRICE_MAP_TTL,
    _build_price_map_async,
    _clear_price_map_cache,
    _fetch_realtime_price,
    _get_etf_attr,
    _split_symbols,
    build_price_map,
)
from app.services.portfolio.strategy_check import (
    _COMPOSITE_FACTOR_MAP,
    _attach_composite_decisions,
    _build_llm_fail_summary,
    _build_rule_fallback_holdings_analysis,
    _build_rule_fallback_report,
    _collect_strategy_data,
    _combine_risk_warnings,
    _compute_indicators,
    _compute_risk_warnings,
    _empty_portfolio_diagnosis,
    _full_pool_factor_composite,
    _is_failed_result,
    _llm_timeout_for,
    _rule_based_suggestion,
    _strategy_check_cache,
    _within_symbol_factor_composite,
    strategy_check,
)
from app.services.portfolio.transfer import (
    export_portfolio,
    import_portfolio,
)

__all__ = [
    # constants
    "FACTOR_LABELS",
    "_RSI_HINT",
    "_KDJ_HINT",
    "_CONFIDENCE_ZH",
    "_PRICE_MAP_CACHE",
    "_PRICE_MAP_TTL",
    "_FUNDAMENTALS_CACHE",
    "_strategy_check_cache",
    "_COMPOSITE_FACTOR_MAP",
    # formatting
    "_factor_hint",
    "_factor_strength_band",
    "format_factor_summary",
    "_factor_value_real",
    "_has_real_factor_values",
    "_normalize_confidence",
    "_compute_confidence",
    # pricing
    "build_price_map",
    "_build_price_map_async",
    "_get_etf_attr",
    "_split_symbols",
    "_fetch_realtime_price",
    "_clear_price_map_cache",
    # crud
    "list_etfs",
    "add_etf",
    "update_etf",
    "remove_etf",
    "_resolve_tracked_index",
    "_recompute_target_weight",
    # allocation
    "calculate_allocation",
    "recompute_cost_after_trade",
    "calculate_weight_drift",
    # pnl
    "calculate_daily_pnl",
    "calculate_cumulative_pnl",
    # strategy check
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
    # design / transfer
    "apply_portfolio_design",
    "export_portfolio",
    "import_portfolio",
    "market_data_hub",
]
