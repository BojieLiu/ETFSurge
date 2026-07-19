"""Unit tests for the Agent Registry + Runtime architecture.

These tests validate the refactored analysis layer without hitting the network:
the LLM call (``llm_complete_with_system``) is mocked at the runtime boundary.
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analysis.registry import AGENTS, get_agent, AgentConfig
from app.analysis.runtime import AgentRuntime, _extract_json


EXPECTED_AGENTS = {
    "market_report",
    "advice",
    "news_analysis",
    "news_impact",
    "portfolio_design",
    "portfolio_review",
    "strategy_suggestions",
    "sector_analysis",
    "symbol_analysis",
    "strategy_check",
}


def test_all_ten_agents_registered():
    """Contract: exactly the 10 documented analysis chains exist."""
    assert set(AGENTS.keys()) == EXPECTED_AGENTS


def test_get_agent_returns_runtime_with_loaded_prompt():
    rt = get_agent("market_report")
    assert isinstance(rt, AgentRuntime)
    assert rt.system_prompt.strip()  # loaded from prompts/v1/*.md


def test_unknown_agent_raises_keyerror():
    with pytest.raises(KeyError):
        get_agent("does_not_exist")


def test_prompts_loaded_from_versioned_files():
    """Contract: each agent resolves its system prompt from a markdown file."""
    review = get_agent("portfolio_review")
    assert "风控官" in review.system_prompt
    news = get_agent("news_impact")
    assert "impact_scope" in news.system_prompt
    design = get_agent("portfolio_design")
    assert "角色设定" in design.system_prompt


def test_response_format_config():
    """Contract: only JSON agents declare response_format='json_object'."""
    json_agents = {k for k, v in AGENTS.items() if v.response_format == "json_object"}
    assert json_agents == {
        "news_impact",
        "portfolio_design",
        "portfolio_review",
        "strategy_suggestions",
        "strategy_check",
    }


def test_extract_json_tolerates_fences_and_surrounding_text():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('prefix {"b": 2} suffix') == {"b": 2}
    assert _extract_json('{"c": 3}') == {"c": 3}


@pytest.mark.asyncio
async def test_runtime_run_returns_raw_text():
    rt = get_agent("market_report")
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(return_value="report text"),
    ) as mock:
        result = await rt.run("some prompt")
    assert result == "report text"
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_run_json_parses_response():
    rt = get_agent("news_impact")
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(return_value='{"impact_scope": "x", "affected_holdings": [], "summary": "s"}'),
    ):
        result = await rt.run_json("p")
    assert result == {"impact_scope": "x", "affected_holdings": [], "summary": "s"}


@pytest.mark.asyncio
async def test_runtime_retries_then_succeeds():
    cfg = AgentConfig("retry-test", "general_analyst.md", max_retries=3)
    rt = AgentRuntime(cfg)
    side = [RuntimeError("fail1"), RuntimeError("fail2"), "success"]
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(side_effect=side),
    ):
        result = await rt.run("p")
    assert result == "success"


@pytest.mark.asyncio
async def test_runtime_reraises_after_exhausting_retries():
    rt = get_agent("market_report")  # max_retries = 1
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError):
            await rt.run("p")
