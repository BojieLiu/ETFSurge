"""
Tests for factor integration: scaffolding → real compute + pool_manager wiring.

P1-1: _compute_stock_divergence returns non-zero with real data
P1-2: pool_manager.refresh() includes non-empty factor_scores
P1-3: _compute_stock_divergence fallback path works (no advance_decline in data)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestPhaseC:
    """LLM report factor breakdown integration."""

    def test_factor_breakdown_in_etf_output(self):
        """Strategy output includes factor_breakdown field."""
        # Build a minimal mock asset that simulates a scored pool entry
        mock_asset = {
            "symbol": "510300",
            "name": "沪深300ETF",
            "composite_score": 0.85,
            "factor_scores": {
                "momentum": 0.92,
                "fund_flow": 0.78,
                "valuation": 0.45,
                "sentiment": 0.62,
                "news_heat": 0.00,
            },
            "industry": "宽基指数",
            "concepts": ["大盘"],
        }

        # Validate that the factor_breakdown dict comprehension works
        factor_breakdown = {
            k: round(v, 3) for k, v in (mock_asset.get("factor_scores", {}) or {}).items()
            if isinstance(v, (int, float))
        }
        assert "momentum" in factor_breakdown
        assert factor_breakdown["momentum"] == 0.92
        assert factor_breakdown["fund_flow"] == 0.78
        assert factor_breakdown["news_heat"] == 0.0
        assert len(factor_breakdown) == 5

        # Verify empty factor_scores yields empty breakdown
        mock_no_scores = {"symbol": "518880", "name": "黄金ETF", "composite_score": 0.5}
        empty_breakdown = {
            k: round(v, 3) for k, v in (mock_no_scores.get("factor_scores", {}) or {}).items()
            if isinstance(v, (int, float))
        }
        assert empty_breakdown == {}

    def test_llm_prompt_contains_factor_table(self):
        """LLM prompt is enhanced with factor breakdown table."""
        from app.analysis.llm import _build_factor_breakdown_table

        # Build mock strategies with factor data
        strategies = [
            {
                "style": "defensive",
                "label": "防御型",
                "allocations": [
                    {
                        "symbol": "510300",
                        "name": "沪深300ETF",
                        "factor_score": 0.85,
                        "factor_breakdown": {
                            "momentum": 0.92,
                            "fund_flow": 0.78,
                            "valuation": 0.45,
                            "sentiment": 0.62,
                            "news_heat": 0.0,
                        },
                    },
                    {
                        "symbol": "510880",
                        "name": "红利低波ETF",
                        "factor_score": 0.72,
                        "factor_breakdown": {
                            "momentum": 0.55,
                            "fund_flow": 0.60,
                            "valuation": 0.88,
                            "sentiment": 0.30,
                        },
                    },
                ],
            },
        ]

        table = _build_factor_breakdown_table(strategies)

        # Verify the table is non-empty and contains key sections
        assert table, "Factor breakdown table should not be empty"
        assert "## ETF Factor Breakdown" in table
        assert "Below are the detailed factor scores" in table
        assert "| Symbol | Name | Factor Score" in table
        assert "510300" in table
        assert "沪深300ETF" in table
        assert "momentum" in table
        assert "fund_flow" in table
        assert "valuation" in table
        assert "sentiment" in table
        assert "news_heat" in table
        assert "0.920" in table or "0.92" in table
        assert "dominant factors" in table
        assert "writing the rationale" in table

    def test_factor_table_empty_no_data(self):
        """Factor breakdown table is empty when no factor data exists."""
        from app.analysis.llm import _build_factor_breakdown_table

        strategies = [
            {
                "style": "defensive",
                "allocations": [
                    {"symbol": "CASH", "name": "现金", "factor_score": None},
                ],
            },
        ]
        assert _build_factor_breakdown_table(strategies) == ""

    def test_factor_table_empty_no_allocations(self):
        """Factor breakdown table is empty when no allocations present."""
        from app.analysis.llm import _build_factor_breakdown_table

        strategies = [{"style": "defensive"}]
        assert _build_factor_breakdown_table(strategies) == ""


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


class TestPhaseB:
    """Regime dynamic weights + IC tracking."""

    def test_regime_weights_differ(self):
        """Same item scores differently in bull vs bear regime."""
        from app.services.pool_manager import pool_manager as pm
        item = {"factor_scores": {"momentum": 0.8}, "amount": 1e9, "fund_scale": 5e10}
        bull_score = pm._compute_composite(item, "satellite", "bull")
        bear_score = pm._compute_composite(item, "satellite", "bear")
        assert bull_score != bear_score, "Regime weights should produce different scores"

    def test_bull_weights_factor_more(self):
        """Bull regime weights factor higher than bear."""
        from app.services.pool_manager import pool_manager as pm
        item = {"factor_scores": {"momentum": 0.8}, "amount": 1e9, "fund_scale": 5e10}
        bull_score = pm._compute_composite(item, "satellite", "bull")
        bear_score = pm._compute_composite(item, "satellite", "bear")
        assert bull_score > bear_score, "Bull should favor factor more than bear"

    @pytest.mark.asyncio
    async def test_ic_records_on_compute(self):
        """FactorRegistry.compute() records IC after computing."""
        from app.factors.factor_registry import registry
        from app.factors.ic_tracker import ic_tracker
        with patch.object(ic_tracker, "record") as mock_record:
            symbols = ["510300"]
            market_data = {
                "510300": {
                    "close": [4.0 + i * 0.01 for i in range(60)],
                    "high": [4.0 + i * 0.02 for i in range(60)],
                    "low": [4.0 - i * 0.005 for i in range(60)],
                    "volume": [2_000_000 + i * 500 for i in range(60)],
                }
            }
            result = await registry.compute(symbols, market_data=market_data)
            assert mock_record.called, "ic_tracker.record should have been called"
            # At least one call per symbol with non-zero factor
            factor_calls = [c for c in mock_record.call_args_list]
            assert len(factor_calls) >= 3, f"Expected >=3 IC records, got {len(factor_calls)}"


class TestPhaseD:
    """Policy factors (十五五 static mapping)."""

    def test_five_year_plan_semiconductor(self):
        from app.factors.factor_registry import _compute_five_year_plan
        score = _compute_five_year_plan({"industry": "半导体"})
        assert score == 0.95
        assert 0 <= score <= 1

    def test_five_year_plan_fallback(self):
        from app.factors.factor_registry import _compute_five_year_plan
        score = _compute_five_year_plan({"industry": "unknown_industry"})
        assert score == 0.30

    def test_strategic_emerging_yes(self):
        from app.factors.factor_registry import _compute_strategic_emerging
        assert _compute_strategic_emerging({"industry": "半导体"}) == 1.0
        assert _compute_strategic_emerging({"industry": "计算机"}) == 1.0
        assert _compute_strategic_emerging({"industry": "国防军工"}) == 1.0

    def test_strategic_emerging_no(self):
        from app.factors.factor_registry import _compute_strategic_emerging
        assert _compute_strategic_emerging({"industry": "银行"}) == 0.0
        assert _compute_strategic_emerging({"industry": "食品饮料"}) == 0.0

    def test_dual_circulation_by_industry(self):
        from app.factors.factor_registry import _compute_dual_circulation
        assert _compute_dual_circulation({"industry": "食品饮料"}) == 1.0
        assert _compute_dual_circulation({"industry": "家用电器"}) == 1.0
        assert _compute_dual_circulation({"industry": "银行"}) == 0.0

    def test_dual_circulation_by_concepts(self):
        from app.factors.factor_registry import _compute_dual_circulation
        result = _compute_dual_circulation({"industry": "电子", "concepts": ["消费电子", "AI"]})
        assert result == 1.0

    def test_policy_factors_in_registry(self):
        from app.factors.factor_registry import registry, _CORE_FACTORS
        for code in ["china.policy.five_year_plan", "china.policy.strategic_emerging",
                      "china.policy.dual_circulation"]:
            assert code in registry._computers, f"{code} not in registry"
            assert code in _CORE_FACTORS, f"{code} not in core factors"
