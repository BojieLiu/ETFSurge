"""Tests: AgentRuntime system_override fix (plan update v1.2).

TDD: Written before implementation.
Covers:
  - AgentRuntime.run() should use system_override from kwargs if provided
  - AgentRuntime.run() should fall back to self.system_prompt when no override
  - AgentRuntime.run() and run_stream() both accept kwargs
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def agent_runtime():
    """Create a minimal AgentRuntime for testing."""
    from app.analysis.registry import AgentConfig, get_agent
    
    # We need to mock the prompt loading to avoid file dependency
    with patch("app.analysis.runtime.load_prompt") as mock_load:
        mock_load.return_value = "default system prompt"
        
        config = AgentConfig(
            name="test_agent",
            system_prompt_file="test_prompt.md",
            temperature=0.5,
        )
        from app.analysis.runtime import AgentRuntime
        runtime = AgentRuntime(config)
        yield runtime


@pytest.mark.asyncio
async def test_run_uses_system_override_when_provided(agent_runtime):
    """When system_override is provided in kwargs, run() should use it."""
    with patch("app.analysis.runtime.llm_complete_with_system") as mock_llm:
        mock_llm.return_value = "LLM response"
        
        override_prompt = "custom system prompt for test"
        result = await agent_runtime.run(
            "user prompt",
            system_override=override_prompt,
        )
        
        # Verify llm_complete_with_system was called with the override
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["system_prompt"] == override_prompt, \
            f"Expected {override_prompt}, got {call_kwargs['system_prompt']}"
        assert result == "LLM response"


@pytest.mark.asyncio
async def test_run_falls_back_to_default_prompt(agent_runtime):
    """When no system_override provided, run() should use default prompt."""
    with patch("app.analysis.runtime.llm_complete_with_system") as mock_llm:
        mock_llm.return_value = "LLM response"
        
        result = await agent_runtime.run("user prompt")
        
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["system_prompt"] == "default system prompt", \
            "Should use default system prompt"
        assert result == "LLM response"


@pytest.mark.asyncio
async def test_run_passes_other_kwargs_correctly(agent_runtime):
    """run() should pass response_format and prompt correctly."""
    with patch("app.analysis.runtime.llm_complete_with_system") as mock_llm:
        mock_llm.return_value = "response"
        
        await agent_runtime.run(
            "test prompt",
            system_override="override",
        )
        
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["prompt"] == "test prompt"
        assert "system_prompt" in call_kwargs
        assert "response_format" in call_kwargs


@pytest.mark.asyncio
async def test_run_without_override_and_without_kwargs(agent_runtime):
    """run() without any kwargs should still work."""
    with patch("app.analysis.runtime.llm_complete_with_system") as mock_llm:
        mock_llm.return_value = "response"
        
        result = await agent_runtime.run("just a prompt")
        
        mock_llm.assert_called_once()
        assert result == "response"
