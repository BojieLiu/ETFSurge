"""Tests for system-diagnosis-and-optimization-plan.md fixes.

Covers the verifiable (unit-testable) fixes:
  - F4: LLM max_tokens raised 8192 -> 12288 (budget for reasoning models)
  - F5: reasoning_content fallback removed (content empty -> "" not scratchpad)
  - F19: china_specific factors consume `industry` from factor data
        (five_year_plan / strategic_emerging / dual_circulation)

External network / LLM providers are mocked — no real calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


# ─── F4 / F5: llm_complete max_tokens + reasoning fallback ──────────

def _fake_provider():
    return SimpleNamespace(
        id="fake",
        model="deepseek-v4-flash",
        api_url="https://example.test/v1/chat/completions",
        api_key="sk-fake",
        timeout=30,
    )


async def _call_llm_with_response(payload):
    """Run llm_complete against a mocked httpx client returning `payload`."""
    from app.analysis import llm as llm_mod

    captured = {}

    class _Resp:
        def __init__(self, body):
            self._body = body
        def raise_for_status(self):
            return None
        def json(self):
            return self._body

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, headers=None, json=None):
            captured["body"] = json
            return _Resp(payload)

    with patch.object(llm_mod, "get_configured_providers", return_value=[_fake_provider()]), \
         patch.object(llm_mod, "_check_key", new=AsyncMock()), \
         patch("httpx.AsyncClient", _Client):
        content = await llm_mod.llm_complete("hello world")
    return content, captured.get("body", {})


@pytest.mark.asyncio
async def test_F4_max_tokens_raised_to_12288():
    content, body = await _call_llm_with_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    })
    assert content == "ok"
    assert body.get("max_tokens") == 12288


@pytest.mark.asyncio
async def test_F5_empty_content_returns_empty_not_reasoning():
    # reasoning_content present but content empty -> must return "" (no scratchpad leak)
    content, _ = await _call_llm_with_response({
        "choices": [{"message": {
            "content": "",
            "reasoning_content": "let me think step by step ...",
        }}],
        "usage": {},
    })
    assert content == ""


@pytest.mark.asyncio
async def test_F5_json_force_empty_content_returns_empty():
    content, _ = await _call_llm_with_response({
        "choices": [{"message": {
            "content": "",
            "reasoning_content": "not valid json at all",
        }}],
        "usage": {},
    })
    assert content == ""


# ─── F19: china_specific factors consume `industry` ────────────────

from app.factors.factor_registry import (
    _compute_five_year_plan,
    _compute_strategic_emerging,
    _compute_dual_circulation,
)


@pytest.mark.parametrize("industry,expected", [
    ("半导体", 0.95),
    ("银行", 0.25),
    ("食品饮料", 0.30),
    ("", 0.30),  # fallback
])
def test_F19_five_year_plan_uses_industry(industry, expected):
    assert _compute_five_year_plan({"industry": industry}) == expected


@pytest.mark.parametrize("industry,expected", [
    ("半导体", 1.0),
    ("计算机", 1.0),
    ("银行", 0.0),
    ("", 0.0),
])
def test_F19_strategic_emerging_uses_industry(industry, expected):
    assert _compute_strategic_emerging({"industry": industry}) == expected


@pytest.mark.parametrize("industry,concepts,expected", [
    ("食品饮料", [], 1.0),
    ("汽车", ["内需"], 1.0),
    ("银行", [], 0.0),
    ("", [], 0.0),
])
def test_F19_dual_circulation_uses_industry_and_concepts(industry, concepts, expected):
    assert _compute_dual_circulation({"industry": industry, "concepts": concepts}) == expected
