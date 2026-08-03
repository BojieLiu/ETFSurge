"""Unified agent runtime for all LLM analysis chains.

Every analysis endpoint is driven by an :class:`AgentRuntime` instance built
from an :class:`~app.analysis.registry.AgentConfig`. The runtime centralizes
the concerns that were previously copy-pasted across the nine ``generate_*``
functions:

* loading the system prompt from a versioned markdown file
* performing the LLM call with the agent's model/temperature/response_format
* retrying on transient failures (``max_retries``)
* parsing JSON responses (``run_json``)
* streaming responses (``run_stream``)
"""
import json
from typing import Any, AsyncGenerator

from ..core.logging import get_logger
from .prompts import load_prompt
from .llm import llm_complete_with_system, llm_complete_stream

logger = get_logger(__name__)


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output, tolerant of ```json fences."""
    if text is None:
        raise ValueError("empty LLM response")
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    return json.loads(s)


class AgentRuntime:
    """Drives a single configured agent: system prompt + LLM call + parsing."""

    def __init__(self, config):
        self.config = config
        self.system_prompt = load_prompt(config.system_prompt_file)

    def _response_format(self):
        if self.config.response_format == "json_object":
            return {"type": "json_object"}
        return None

    async def run(self, prompt: str, **kwargs) -> str:
        """Run the agent and return the raw LLM text response.

        Supports optional ``system_override`` in **kwargs:
        when provided, it replaces ``self.system_prompt`` for this call.
        R5-1-6: ``rate_limit_cap``/``max_retries``/``retry_delay`` 透传到
        llm_complete_with_system（策略检查传 max_retries=1, rate_limit_cap=10 快速失败）。
        """
        system_prompt = kwargs.get("system_override", self.system_prompt)
        last_exc: Exception | None = None
        # R5-1-6: 仅透传显式提供的参数（None 保持 llm_complete_with_system 默认值）
        _llm_kwargs = {}
        for _k in ("max_retries", "retry_delay", "rate_limit_cap"):
            _v = kwargs.get(_k)
            if _v is not None:
                _llm_kwargs[_k] = _v
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return await llm_complete_with_system(
                    system_prompt=system_prompt,
                    prompt=prompt,
                    response_format=self._response_format(),
                    **_llm_kwargs,
                )
            except Exception as exc:  # transient / network / LLM errors
                last_exc = exc
                logger.warning(
                    "Agent[%s] call failed (attempt %d/%d): %s",
                    self.config.name,
                    attempt,
                    self.config.max_retries,
                    exc,
                )
        if last_exc is None:
            raise RuntimeError(f"Agent[{self.config.name}] produced no result")
        raise last_exc

    async def run_stream(self, prompt: str, **kwargs) -> AsyncGenerator[dict, None]:
        """Run the agent and yield SSE events (token, done, error)."""
        try:
            async for event in llm_complete_stream(
                system_prompt=self.system_prompt,
                prompt=prompt,
                response_format=self._response_format(),
                temperature=self.config.temperature,
            ):
                if event["type"] == "token":
                    yield {"event": "token", "data": {"token": event["token"]}}
                elif event["type"] == "done":
                    yield {"event": "done", "data": event}
                    return
                elif event["type"] == "error":
                    yield {"event": "error", "data": event["error"]}
                    return
        except Exception as exc:
            logger.error("Agent[%s] stream failed: %s", self.config.name, exc)
            yield {"event": "error", "data": {"code": "STREAM_ERROR", "message": str(exc)}}

    async def run_json(self, prompt: str, **kwargs) -> dict:
        """Run the agent and parse the response as a JSON object.

        R5-1-6: kwargs（max_retries/rate_limit_cap）透传给 run → llm_complete_with_system。
        """
        raw = await self.run(prompt, **kwargs)
        return _extract_json(raw)
