"""Tests: LLM engine fallback (7.4 P1, updated v1.2).

Per the Provider diagnostics, the circuit breaker in generate_design_report()
causes false positives. Plan 方案一 removes it, keeping:
  - _build_engine_fallback() as a real fallback on LLM exception
  - Provider failover as the primary protection layer

Covers:
  - Engine fallback on LLM exception
  - Engine fallback content generation
  - Empty strategies handling
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.asyncio
async def test_llm_failure_returns_engine_fallback():
    """When LLM call fails, generate_design_report should return engine fallback."""
    from app.analysis.llm import generate_design_report

    with patch("app.analysis.llm.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run.side_effect = Exception("API Error")
        mock_get_agent.return_value = mock_agent

        strategies = [{
            "label": "保守型",
            "layer_budget": {"core": 0.5, "satellite": 0.3, "defense": 0.2},
            "allocations": [
                {"symbol": "510050", "name": "上证50ETF", "target_weight": 0.3, "factor_score": 0.75},
            ]
        }]

        result = await generate_design_report(
            strategies=strategies,
            market_sentiment={"overall": "cautious"},
            plan_tables="## 一、三种方案详解\n...",
        )

        # Should return meaningful fallback on LLM failure
        assert result, "Should return fallback on LLM failure"
        assert len(result) > 100, "Fallback should be meaningful"
        assert "保守型" in result, "Fallback should contain strategy data"


@pytest.mark.asyncio
async def test_llm_success_returns_llm_content():
    """When LLM call succeeds, generate_design_report should return LLM content."""
    from app.analysis.llm import generate_design_report

    with patch("app.analysis.llm.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = "LLM analysis with good content"
        mock_get_agent.return_value = mock_agent

        strategies = [{
            "label": "保守型",
            "layer_budget": {"core": 0.5, "satellite": 0.3, "defense": 0.2},
            "allocations": [
                {"symbol": "510050", "name": "上证50ETF", "target_weight": 0.3, "factor_score": 0.75},
            ]
        }]

        result = await generate_design_report(
            strategies=strategies,
            market_sentiment={"overall": "cautious"},
            plan_tables="## 一、三种方案详解\n...",
        )

        assert result == "LLM analysis with good content"
        mock_get_agent.assert_called_once()
        mock_agent.run.assert_called_once()


@pytest.mark.asyncio
async def test_engine_fallback_contains_strategy_data():
    """Engine fallback should contain strategy labels and allocation data."""
    from app.analysis.llm import _build_engine_fallback

    strategies = [{
        "label": "保守型",
        "layer_budget": {"core": 0.5, "satellite": 0.3, "defense": 0.2},
        "allocations": [
            {"symbol": "510050", "name": "上证50ETF", "target_weight": 0.3, "factor_score": 0.75},
        ]
    }]
    regime = "range_bound"

    result = _build_engine_fallback(strategies, regime)

    assert "保守型" in result
    assert "510050" in result
    assert "range_bound" in result or "市态" in result
    assert len(result) > 200


@pytest.mark.asyncio
async def test_engine_fallback_empty_strategies():
    """Engine fallback should handle empty strategies gracefully."""
    from app.analysis.llm import _build_engine_fallback

    result = _build_engine_fallback([], "unknown")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_engine_fallback_empty_regime():
    """Engine fallback should handle missing regime gracefully."""
    from app.analysis.llm import _build_engine_fallback

    result = _build_engine_fallback([], "")
    assert isinstance(result, str)
    assert len(result) > 0
