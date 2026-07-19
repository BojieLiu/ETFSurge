"""
TDD tests for LLM provider dual-tier failover (OpenCode Zen → DeepSeek).

Covers:
  - P0: Primary provider (opencode_zen) succeeds
  - P1: Primary timeout → fallback succeeds
  - P2: Primary HTTP error → fallback succeeds
  - P3: Primary network error → fallback succeeds
  - P0.5: All providers exhausted
  - UX3: UsageRecord stores provider field
  - UX4: Missing OPENCODE_ZEN_API_KEY skips primary

All external HTTP calls are mocked (httpx.AsyncClient).
"""

import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock, ANY


# ─── Test data ─────────────────────────────────────────────────────
PRIMARY_CONTENT = '{"plans": [], "design_text": "primary result"}'
FALLBACK_CONTENT = '{"plans": [], "design_text": "fallback result"}'


# ─── Helper: build a fake httpx response ───────────────────────────

def _make_response(content: str, model: str = "deepseek-v4-flash-free",
                   status: int = 200, tokens: tuple = (50, 100, 150)) -> MagicMock:
    """Build a mock httpx.Response for OpenAI-compatible chat completion."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content, "reasoning_content": None}}],
        "usage": {
            "prompt_tokens": tokens[0],
            "completion_tokens": tokens[1],
            "total_tokens": tokens[2],
        },
        "model": model,
    }
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=resp
        )
    return resp


# ─── Helper: mock httpx.AsyncClient.post with side_effect list ───

def _patch_httpx(side_effects: list):
    """
    Patch app.analysis.llm.httpx.AsyncClient (used in llm_complete_with_system
    and llm_complete).  side_effects is a list of return values or exceptions.
    """
    patcher = patch("app.analysis.llm.httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_instance = mock_cls.return_value.__aenter__.return_value
    mock_instance.post = AsyncMock(side_effect=side_effects)
    return patcher


def _patch_provider_settings(**kwargs):
    """Patch settings values needed by provider.py."""
    defaults = dict(
        llm_primary_provider="opencode_zen",
        llm_fallback_provider="deepseek",
        opencode_zen_api_key="sk-zen-test-key",
        opencode_zen_model="deepseek-v4-flash-free",
        opencode_zen_api_url="https://opencode.ai/zen/v1/chat/completions",
        llm_primary_timeout=120,
        llm_fallback_timeout=120,
        deepseek_api_key="sk-ds-test-key",
        llm_model="deepseek-v4-flash",
    )
    defaults.update(kwargs)

    from app.config import settings
    patches = []
    for k, v in defaults.items():
        p = patch.object(settings, k, v)
        p.start()
        patches.append(p)
    return patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


# ─── Override provider module settings before each test ────────────

@pytest.fixture(autouse=True)
def _provider_settings():
    """Ensure provider configuration is set for each test."""
    patches = _patch_provider_settings()
    yield
    _stop_patches(patches)


# ─── P0: Primary succeeds ────────────────────────────────────────

class TestPrimarySuccess:
    async def test_p0_primary_returns_result(self):
        """Primary provider (opencode_zen) succeeds → return its content."""
        from app.analysis.llm import llm_complete_with_system

        resp = _make_response(PRIMARY_CONTENT, model="deepseek-v4-flash-free")
        patcher = _patch_httpx([resp])
        try:
            result = await llm_complete_with_system("system", "prompt",
                                                     response_format={"type": "json_object"})
            assert result == PRIMARY_CONTENT
        finally:
            patcher.stop()

    async def test_p0_only_one_provider_called(self):
        """Only the primary provider should be called on success."""
        from app.analysis.llm import llm_complete_with_system

        resp = _make_response("ok")
        patcher = _patch_httpx([resp])
        try:
            await llm_complete_with_system("system", "prompt")
        finally:
            patcher.stop()

        mock_instance = (
            patcher.return_value.__aenter__.return_value  # type: ignore
            if hasattr(patcher, "return_value") else None
        )
        # Actually let's verify through the mock_cls
        mock_cls = patcher.return_value
        mock_instance = mock_cls.return_value.__aenter__.return_value
        assert mock_instance.post.call_count == 1


# ─── P1: Primary timeout → fallback succeeds ─────────────────────

class TestPrimaryTimeout:
    async def test_p1_timeout_triggers_fallback(self):
        """Primary times out → fallback provider returns result."""
        from app.analysis.llm import llm_complete_with_system

        primary_err = httpx.TimeoutException("timed out", request=MagicMock())
        fallback_resp = _make_response(FALLBACK_CONTENT, model="deepseek-v4-flash")
        patcher = _patch_httpx([primary_err, fallback_resp])
        try:
            result = await llm_complete_with_system("system", "prompt")
            assert result == FALLBACK_CONTENT
        finally:
            patcher.stop()

    async def test_p1_logs_warning_on_fallback(self, caplog):
        """Warning-level log should record the fallback."""
        import logging
        caplog.set_level(logging.WARNING)

        from app.analysis.llm import llm_complete_with_system

        primary_err = httpx.TimeoutException("timed out", request=MagicMock())
        fallback_resp = _make_response("ok")
        patcher = _patch_httpx([primary_err, fallback_resp])
        try:
            await llm_complete_with_system("system", "prompt")
        finally:
            patcher.stop()

        assert any("Falling back" in rec.message for rec in caplog.records), \
            "Expected a WARNING log about fallback"


# ─── P2: Primary HTTP error → fallback succeeds ──────────────────

class TestPrimaryHttpError:
    async def test_p2_http_500_triggers_fallback(self):
        """Primary returns HTTP 500 → fallback returns result."""
        from app.analysis.llm import llm_complete_with_system

        primary_resp = _make_response("error", status=500)
        fallback_resp = _make_response(FALLBACK_CONTENT, model="deepseek-v4-flash")
        patcher = _patch_httpx([primary_resp, fallback_resp])
        try:
            result = await llm_complete_with_system("system", "prompt")
            assert result == FALLBACK_CONTENT
        finally:
            patcher.stop()


# ─── P3: Primary network error → fallback succeeds ───────────────

class TestPrimaryNetworkError:
    async def test_p3_connection_error_triggers_fallback(self):
        """Primary connection refused → fallback returns result."""
        from app.analysis.llm import llm_complete_with_system

        primary_err = httpx.ConnectError("Connection refused", request=MagicMock())
        fallback_resp = _make_response(FALLBACK_CONTENT, model="deepseek-v4-flash")
        patcher = _patch_httpx([primary_err, fallback_resp])
        try:
            result = await llm_complete_with_system("system", "prompt")
            assert result == FALLBACK_CONTENT
        finally:
            patcher.stop()


# ─── P0.5: All providers exhausted ───────────────────────────────

class TestAllProvidersExhausted:
    async def test_p05_all_providers_fail_raises(self):
        """Both primary and fallback fail → exception is raised."""
        from app.analysis.llm import llm_complete_with_system

        primary_err = httpx.TimeoutException("primary timeout", request=MagicMock())
        fallback_err = httpx.HTTPStatusError(
            "fallback 503", request=MagicMock(),
            response=_make_response("error", status=503),
        )
        patcher = _patch_httpx([primary_err, fallback_err])
        try:
            with pytest.raises(Exception):
                await llm_complete_with_system("system", "prompt")
        finally:
            patcher.stop()


# ─── UX3: UsageRecord stores provider field ─────────────────────

class TestUsageRecordProvider:
    async def test_ux3_record_primary_provider(self):
        """On primary success, UsageRecord.provider == 'opencode_zen'."""
        from app.analysis.llm import llm_complete_with_system
        from app.monitor.token_usage import token_store

        resp = _make_response("ok", model="deepseek-v4-flash-free")
        patcher = _patch_httpx([resp])
        try:
            await llm_complete_with_system("system", "prompt")
        finally:
            patcher.stop()

        # Since token_store is async and flushes in background, check the in-memory records
        async with token_store._lock:
            records = list(token_store._records)
        # Find the most recent record
        matching = [r for r in records if r.success and r.provider]
        assert any(r.provider == "opencode_zen" for r in matching), \
            f"No record found with provider='opencode_zen'. Records: {matching[-3:] if matching else 'empty'}"

    async def test_ux3_record_fallback_provider(self):
        """On fallback success, UsageRecord.provider == 'deepseek'."""
        from app.analysis.llm import llm_complete_with_system
        from app.monitor.token_usage import token_store

        primary_err = httpx.TimeoutException("timeout", request=MagicMock())
        fallback_resp = _make_response("ok", model="deepseek-v4-flash")
        patcher = _patch_httpx([primary_err, fallback_resp])
        try:
            await llm_complete_with_system("system", "prompt")
        finally:
            patcher.stop()

        async with token_store._lock:
            records = list(token_store._records)
        matching = [r for r in records if r.success and r.provider]
        assert any(r.provider == "deepseek" for r in matching), \
            f"No record found with provider='deepseek'. Records: {matching[-3:] if matching else 'empty'}"


# ─── UX4: Missing API key skips primary ─────────────────────────

class TestMissingApiKey:
    async def test_ux4_no_zen_key_skips_primary(self):
        """OPENCODE_ZEN_API_KEY is empty → skip primary, use deepseek directly."""
        _stop_patches(_patch_provider_settings(opencode_zen_api_key=""))
        from app.analysis.llm import llm_complete_with_system

        resp = _make_response("direct fallback", model="deepseek-v4-flash")
        patcher = _patch_httpx([resp])
        try:
            result = await llm_complete_with_system("system", "prompt")
            assert result == "direct fallback"
        finally:
            patcher.stop()

    async def test_ux4_no_keys_at_all_raises(self):
        """Both API keys empty → raise ValueError."""
        _stop_patches(_patch_provider_settings(
            opencode_zen_api_key="",
            deepseek_api_key="",
        ))
        # Need to re-import or force config reload
        from app.analysis.provider import has_any_api_key
        assert not has_any_api_key(), "Expected no keys configured"

        from app.analysis.llm import llm_complete_with_system
        with pytest.raises(ValueError, match="No LLM API keys configured"):
            await llm_complete_with_system("system", "prompt")
