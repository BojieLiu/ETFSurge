"""Test Z11: Design pipeline degradation contract.

Covers:
1. Empty candidate pool -> static_pool mode, 3 strategies, degradation field present
2. Normal path -> degradation.mode='normal'
3. Static pool layer weights derived from STRATEGY_META.layer_budget (not hardcoded)
4. Partial factor matrix -> partial_data mode (still 3 strategies)
5. Pipeline exception -> fallback 3 strategies + degradation
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _make_hub(**overrides):
    """Build a fake market_data_hub with overridable methods."""
    hub = MagicMock()
    hub.refresh = AsyncMock()
    hub.get_market_regime.return_value = "range_bound"
    hub.get_factor_matrix.return_value = {}
    hub.get_pool.side_effect = lambda layer=None: ([] if layer is None else [])
    hub.get_by_code.return_value = None
    hub.etf_pool = None
    for k, v in overrides.items():
        setattr(hub, k, v)
    return hub


class TestDesignDegradation:
    """Z11: generate_enhanced_design degradation modes."""

    @pytest.mark.asyncio
    async def test_empty_pool_static_mode_three_strategies(self):
        """Empty pool -> static_pool degradation, exactly 3 strategies, layer weights from STRATEGY_META."""
        from app.services.strategy_design import generate_enhanced_design

        hub = _make_hub()
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        strategies = result["strategies"]
        assert len(strategies) == 3, f"expected 3 strategies, got {len(strategies)}"
        profiles = {s["id"] for s in strategies}
        assert profiles == {"defensive", "balanced", "aggressive"}

        degradation = result["degradation"]
        assert degradation["mode"] == "static_pool"
        assert degradation["factor_matrix_empty"] is True
        assert degradation["pool_empty"] is True
        assert len(degradation["static_pool_used"]) == 6

        # Layer weights must derive from STRATEGY_META.layer_budget (equal-weight within layer)
        from app.engine.budgets import STRATEGY_META
        balanced = next(s for s in strategies if s["id"] == "balanced")
        budget = STRATEGY_META["balanced"]["layer_budget"]
        etfs = balanced["etfs"]
        non_cash = [e for e in etfs if e["symbol"] != "CASH"]
        core_etfs = [e for e in non_cash if e["layer"] == "core"]
        assert len(core_etfs) == 2  # 510300 + 510050
        expected_per = round(budget["core"] / len(core_etfs), 4)
        assert core_etfs[0]["weight"] == pytest.approx(expected_per)
        # Weights sum to layer budget
        core_sum = sum(e["weight"] for e in core_etfs)
        assert core_sum == pytest.approx(budget["core"])

    @pytest.mark.asyncio
    async def test_normal_path_degradation_normal(self):
        """Healthy pipeline -> degradation.mode='normal'."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"},
                     {"symbol": "510050", "name": "上证50ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        factor_matrix = {
            "510300": {"trend_1m": 0.5, "momentum_20d": 0.4},
            "510050": {"trend_1m": 0.3},
            "159915": {"trend_1m": -0.2},
            "511090": {"trend_1m": 0.1},
        }
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value=factor_matrix),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        assert result["degradation"]["mode"] == "normal"
        assert len(result["strategies"]) == 3

    @pytest.mark.asyncio
    async def test_partial_factor_matrix_partial_data(self):
        """Some symbols missing from factor matrix -> partial_data mode, still 3 strategies."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        # 510300 has factor data; others missing
        factor_matrix = {"510300": {"trend_1m": 0.5}}
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value=factor_matrix),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        assert result["degradation"]["mode"] == "partial_data"
        assert result["degradation"]["factor_matrix_empty"] is False
        assert len(result["strategies"]) == 3

    @pytest.mark.asyncio
    async def test_pipeline_exception_fallback_three_strategies(self):
        """allocate() raises -> fallback 3 strategies + degradation static_pool."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value={"510300": {"trend_1m": 0.5}}),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            with patch("app.services.strategy_design.engine_allocate",
                       side_effect=RuntimeError("engine exploded")):
                result = await generate_enhanced_design(capital=500000)

        assert len(result["strategies"]) == 3
        assert result["degradation"]["mode"] == "static_pool"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])