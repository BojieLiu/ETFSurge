"""Agent registry: declarative configuration for every LLM analysis chain.

Adding a new analysis chain requires only:
  1. one ``AgentConfig`` entry in ``AGENTS`` below
  2. a prompt file under ``prompts/v1/``

No new Python function is needed. The runtime (``runtime.py``) drives every
agent uniformly, centralizing the LLM call, retry/backoff, and JSON parsing.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    """Declarative configuration for a single LLM analysis agent."""

    name: str
    system_prompt_file: str
    model: Optional[str] = None  # None -> fall back to settings.llm_model
    temperature: float = 0.3
    response_format: Optional[str] = None  # None | "json_object"
    max_retries: int = 1


# Keyed by the agent key referenced from routers and services.
AGENTS: dict[str, AgentConfig] = {
    "market_report": AgentConfig("市场研判报告", "general_analyst.md"),
    "advice": AgentConfig("投资建议", "general_analyst.md", temperature=0.5),
    "news_analysis": AgentConfig("资讯分析", "general_analyst.md"),
    "news_impact": AgentConfig(
        "新闻影响评估", "news_impact.md", response_format="json_object"
    ),
    "strategy_suggestions": AgentConfig(
        "策略建议", "general_analyst.md", response_format="json_object"
    ),
    "sector_analysis": AgentConfig("行业分析", "sector_analyst.md"),
    "symbol_analysis": AgentConfig("个股分析", "general_analyst.md"),
    "strategy_check": AgentConfig(
        "策略检查", "strategy_check.md", temperature=0.1, response_format="json_object"
    ),
}


def get_agent(name: str) -> "AgentRuntime":  # type: ignore[name-defined]
    """Return an ``AgentRuntime`` for the named agent config."""
    from .runtime import AgentRuntime

    if name not in AGENTS:
        raise KeyError(f"Unknown agent: {name}")
    return AgentRuntime(AGENTS[name])
