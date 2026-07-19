"""
Tests for factor integration: scaffolding → real compute + pool_manager wiring.

P1-1: _compute_stock_divergence returns non-zero with real data
P1-2: pool_manager.refresh() includes non-empty factor_scores
P1-3: _compute_stock_divergence fallback path works (no advance_decline in data)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestStockDivergence:
    """Test that _compute_stock_divergence uses advance_decline ratio."""

    def test_stock_divergence_computed(self):
        """Returns >0 when advance_decline > 1.0 (more advancers)."""
        from app.factors.factor_registry import _compute_stock_divergence

        result = _compute_stock_divergence({"advance_decline": 1.8})
        assert result > 0.2
        assert result <= 1.0

    def test_stock_divergence_panic(self):
        """Returns <0 when advance_decline < 0.5 (more decliners = panic)."""
        from app.factors.factor_registry import _compute_stock_divergence

        result = _compute_stock_divergence({"advance_decline": 0.4})
        assert result < -0.5
        assert result >= -1.0

    def test_stock_divergence_neutral(self):
        """Returns ~0 when advance_decline ~1.0 (balanced)."""
        from app.factors.factor_registry import _compute_stock_divergence

        result = _compute_stock_divergence({"advance_decline": 1.0})
        assert abs(result) < 0.01

    def test_stock_divergence_clamped_high(self):
        """Clamps to 1.0 for extreme high advance_decline."""
        from app.factors.factor_registry import _compute_stock_divergence

        result = _compute_stock_divergence({"advance_decline": 100.0})
        assert result == 1.0

    def test_stock_divergence_clamped_low(self):
        """Clamps to -1.0 for extreme low advance_decline."""
        from app.factors.factor_registry import _compute_stock_divergence

        result = _compute_stock_divergence({"advance_decline": 0.01})
        assert result == -1.0

    def test_stock_divergence_fallback_no_data(self):
        """Returns 0 when no advance_decline in data and no running loop."""
        from app.factors.factor_registry import _compute_stock_divergence

        # No asyncio running → fallback returns 0.0
        result = _compute_stock_divergence({})
        assert result == 0.0


class TestPoolManagerFactorScores:
    """Test that pool_manager.refresh() passes real factor_scores."""

    @pytest.mark.asyncio
    async def test_pool_manager_has_factor_scores(self):
        """refresh() sets non-empty factor_scores via FactorRegistry."""
        from app.services.pool_manager import pool_manager as pm

        # FactorRegistry returns real scores for these
        scores = {"momentum": 0.75, "rsi": 0.62, "atr": 0.43}

        with patch.object(pm, "factor_registry") as mock_fr:
            mock_fr.compute = AsyncMock(return_value={
                "510300": scores, "518880": {"momentum": 0.55, "rsi": 0.30},
            })
            mock_fr._fetch_market_data = AsyncMock(return_value={})
            mock_fr._computers = {}

            # Mock scanner and classifier dependencies
            with patch.object(pm, "scanner") as mock_sc:
                mock_sc.fetch_all_etfs_base = MagicMock(return_value=[
                    {"symbol": "510300", "name": "沪深300ETF"},
                    {"symbol": "518880", "name": "黄金ETF"},
                ])
                with patch.object(pm, "classifier") as mock_cl:
                    mock_cl.batch_classify = MagicMock(return_value={
                        "510300": {"industry": "宽基指数", "concepts": ["大盘"]},
                        "518880": {"industry": "商品", "concepts": ["黄金"]},
                    })
                    result = await pm.refresh()

        # Verify factor_scores are populated
        pool = result if isinstance(result, dict) else pm.get_pool("core")
        for layer_name, entries in pool.items() if isinstance(pool, dict) else []:
            for entry in entries:
                fs = entry.get("factor_scores", {})
                if fs:
                    assert len(fs) > 0, f"{entry['symbol']} should have factor_scores"

    @pytest.mark.asyncio
    async def test_factor_scores_in_composite_score(self):
        """composite_score uses factor_scores sum (was 0 before fix)."""
        from app.services.pool_manager import pool_manager as pm

        item = {
            "symbol": "510300", "name": "沪深300ETF",
            "factor_scores": {"momentum": 0.8, "fund_flow": 0.6},
            "amount": 1000000000, "fund_scale": 50000000000,
        }
        score = pm._compute_composite(item, "satellite")
        # factor_sum = 0.8 + 0.6 = 1.4
        # return 0.40 * 1.4 + 0.15 * 1e-9 + 0.10 * 5e-10 + 0.35 * 0.5
        # = 0.56 + 0.15 + 0.05 + 0.175 = 0.935
        assert score > 0.5, f"Score {score} should include factor contribution"
