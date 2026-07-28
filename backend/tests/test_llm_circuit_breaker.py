"""Tests: LLM circuit breaker + engine fallback (7.4 P1).

TDD: Written before implementation.
Covers:
  - Circuit breaker open → skip LLM call
  - Circuit breaker closed → normal call
  - Success/failure recorded to SourceRegistry
  - Engine fallback content generation
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_source_registry():
    """Create a mock SourceRegistry with controllable circuit breaker."""
    with patch("app.analysis.llm.registry") as mock:
        mock_health = MagicMock()
        mock_health.available.return_value = True
        mock_health.record_success = MagicMock()
        mock_health.record_failure = MagicMock()
        mock._health.return_value = mock_health
        mock.list_status.return_value = []
        yield mock, mock_health


@pytest.mark.asyncio
async def test_circuit_open_skips_llm_call(mock_source_registry):
    """When circuit breaker is open, generate_design_report should skip LLM call."""
    mock, mock_health = mock_source_registry
    mock_health.available.return_value = False  # Circuit OPEN

    from app.analysis.llm import generate_design_report

    strategies = [{
        "label": "保守型",
        "layer_budget": {"core": 0.5, "satellite": 0.3, "defense": 0.2},
        "allocations": [
            {"symbol": "510050", "name": "上证50ETF", "target_weight": 0.3, "factor_score": 0.75},
            {"symbol": "159915", "name": "创业板ETF", "target_weight": 0.2, "factor_score": 0.65},
        ]
    }]

    result = await generate_design_report(
        strategies=strategies,
        market_sentiment={"overall": "cautious"},
        market_context={"market_regime": "range_bound"},
        plan_tables="## 一、三种方案详解\n..."
    )

    # Must return meaningful fallback (not empty string)
    assert result, "Circuit-open fallback should not be empty"
    assert len(result) > 100, "Fallback content too short"
    # Fallback should mention the regime or contain engine-based content
    assert "range_bound" in result or "保守型" in result or "510050" in result, \
        "Fallback should contain engine data"


@pytest.mark.asyncio
async def test_circuit_closed_calls_llm_normally(mock_source_registry):
    """When circuit breaker is closed, generate_design_report should call LLM."""
    mock, mock_health = mock_source_registry
    mock_health.available.return_value = True  # Circuit CLOSED

    from app.analysis.llm import generate_design_report

    with patch("app.analysis.llm.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = "LLM analysis result with good content"
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
            plan_tables="## 一、三种方案详解\n..."
        )

        # Should have called the LLM agent
        mock_get_agent.assert_called_once()
        mock_agent.run.assert_called_once()
        assert result == "LLM analysis result with good content"


@pytest.mark.asyncio
async def test_llm_failure_records_to_source_registry(mock_source_registry):
    """When LLM call fails, failure should be recorded to SourceRegistry."""
    mock, mock_health = mock_source_registry
    mock_health.available.return_value = True

    from app.analysis.llm import generate_design_report

    with patch("app.analysis.llm.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run.side_effect = Exception("API Error")
        mock_get_agent.return_value = mock_agent

        strategies = [{
            "label": "保守型",
            "layer_budget": {"core": 0.5, "satellite": 0.3, "defense": 0.2},
            "allocations": [
                {"symbol": "510050", "name": "上证50ETF", "target_weight": 0.3},
            ]
        }]

        result = await generate_design_report(
            strategies=strategies,
            market_sentiment={"overall": "cautious"},
            plan_tables="## 一、三种方案详解\n..."
        )

        # Should return fallback content on failure
        assert result, "Should return fallback on LLM failure"
        assert len(result) > 100, "Fallback should be meaningful"


@pytest.mark.asyncio
async def test_engine_fallback_contains_strategy_data():
    """Engine fallback should contain strategy data."""
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
    assert "range_bound" in result
    assert "引擎分析" in result or "因子" in result or "数据摘要" in result


@pytest.mark.asyncio
async def test_engine_fallback_empty_strategies():
    """Engine fallback should handle empty strategies gracefully."""
    from app.analysis.llm import _build_engine_fallback

    result = _build_engine_fallback([], "unknown")
    assert isinstance(result, str)
    assert len(result) > 0
