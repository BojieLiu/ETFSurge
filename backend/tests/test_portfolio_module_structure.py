"""Contract tests for the portfolio_service split (Batch 1).

Verifies the module-structure contract in
``api-contracts/internal/portfolio-split.md``:

- R1: every original symbol is importable from BOTH the old facade path and the
  new sub-module path, and resolves to a behavior-equivalent callable/constant.
- R2: cross-cluster deps route through ``_facade_refs`` (mock.patch semantics).
- R3: pure-function behavior is unchanged (same inputs -> same outputs).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.portfolio_service import (
    recompute_cost_after_trade,
    format_factor_summary,
    _factor_strength_band,
)

# (facade_path_module, new_submodule_path, symbol)
STRUCTURE_PARITY = [
    # formatting
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_factor_hint"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_factor_strength_band"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "format_factor_summary"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_factor_value_real"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_has_real_factor_values"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_normalize_confidence"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_compute_confidence"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "FACTOR_LABELS"),
    ("app.services.portfolio_service", "app.services.portfolio.formatting", "_CONFIDENCE_ZH"),
    # pricing
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "build_price_map"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_build_price_map_async"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_get_etf_attr"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_split_symbols"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_fetch_realtime_price"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_clear_price_map_cache"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_PRICE_MAP_CACHE"),
    ("app.services.portfolio_service", "app.services.portfolio.pricing", "_FUNDAMENTALS_CACHE"),
    # crud
    ("app.services.portfolio_service", "app.services.portfolio.crud", "list_etfs"),
    ("app.services.portfolio_service", "app.services.portfolio.crud", "add_etf"),
    ("app.services.portfolio_service", "app.services.portfolio.crud", "update_etf"),
    ("app.services.portfolio_service", "app.services.portfolio.crud", "remove_etf"),
    ("app.services.portfolio_service", "app.services.portfolio.crud", "_resolve_tracked_index"),
    ("app.services.portfolio_service", "app.services.portfolio.crud", "_recompute_target_weight"),
    # allocation
    ("app.services.portfolio_service", "app.services.portfolio.allocation", "calculate_allocation"),
    ("app.services.portfolio_service", "app.services.portfolio.allocation", "recompute_cost_after_trade"),
    ("app.services.portfolio_service", "app.services.portfolio.allocation", "calculate_weight_drift"),
    # pnl
    ("app.services.portfolio_service", "app.services.portfolio.pnl", "calculate_daily_pnl"),
    ("app.services.portfolio_service", "app.services.portfolio.pnl", "calculate_cumulative_pnl"),
    # strategy_check
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "strategy_check"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_is_failed_result"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_build_llm_fail_summary"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_llm_timeout_for"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_collect_strategy_data"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_empty_portfolio_diagnosis"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_attach_composite_decisions"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_cross_sectional_factor_composite"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_within_symbol_factor_composite"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_full_pool_factor_composite"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_build_rule_fallback_holdings_analysis"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_rule_based_suggestion"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_build_rule_fallback_report"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_combine_risk_warnings"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_compute_risk_warnings"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_compute_indicators"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_strategy_check_cache"),
    ("app.services.portfolio_service", "app.services.portfolio.strategy_check", "_COMPOSITE_FACTOR_MAP"),
    # design / transfer
    ("app.services.portfolio_service", "app.services.portfolio.design", "apply_portfolio_design"),
    ("app.services.portfolio_service", "app.services.portfolio.transfer", "export_portfolio"),
    ("app.services.portfolio_service", "app.services.portfolio.transfer", "import_portfolio"),
]


@pytest.mark.parametrize("old_path,new_path,symbol", STRUCTURE_PARITY)
def test_symbol_available_on_both_paths(old_path, new_path, symbol):
    """R1: symbol importable from old facade path and new sub-module path."""
    import importlib

    old_mod = importlib.import_module(old_path)
    new_mod = importlib.import_module(new_path)
    assert hasattr(old_mod, symbol), f"{old_path} lost {symbol}"
    assert hasattr(new_mod, symbol), f"{new_path} missing {symbol}"


def test_recompute_cost_after_trade_behavior_unchanged():
    """R3: pure-function behavior identical via new path."""
    from app.services.portfolio.allocation import recompute_cost_after_trade as new_f

    cases = [
        (None, None, 100, 4.5),
        (200, 4.2, 100, 4.5),
        (200, 4.2, -50, 5.0),
        (0, None, 100, 3.9),
    ]
    for old_shares, old_cost, delta, price in cases:
        assert new_f(old_shares, old_cost, delta, price) == recompute_cost_after_trade(
            old_shares, old_cost, delta, price
        )


def test_format_factor_summary_behavior_unchanged():
    """R3: formatting output identical via new path."""
    from app.services.portfolio.formatting import format_factor_summary as new_f

    fs = {"technical.rsi.rsi_14": 39.53}
    assert new_f(fs) == format_factor_summary(fs)


def test_cross_cluster_dep_uses_facade_refs_proxy():
    """R2: transfer.list_etfs routes through the facade at call time."""
    from app.services.portfolio import transfer as transfer_mod
    import app.services.portfolio._facade_refs as fr

    assert transfer_mod.list_etfs is fr.list_etfs


@pytest.mark.asyncio
async def test_patch_on_facade_intercepts_proxy_callsite():
    """R2: mock.patch('app.services.portfolio_service.list_etfs') still intercepts."""
    from app.services.portfolio.transfer import import_portfolio

    class FakeDb:
        def add(self, obj):
            pass

        async def flush(self):
            pass

        async def commit(self):
            pass

    csv_content = (
        "symbol,name,asset_type,portfolio_type,target_weight\n"
        "510300,沪深300ETF,ETF,on_exchange,0.1\n"
    )
    with patch(
        "app.services.portfolio_service.list_etfs", new=AsyncMock(return_value=[])
    ):
        result = await import_portfolio(FakeDb(), csv_content)
    assert result["imported"] == 1
    assert result["errors"] == []
