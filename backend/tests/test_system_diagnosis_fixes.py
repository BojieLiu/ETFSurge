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
        name="Fake Provider",
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


# ─── F7: LLM health probe ────────────────────────────────────────────

async def _run_health_check(ok_providers, timeout=15.0):
    """Run llm_health_check with providers whose post() returns per-index ok flag."""
    import httpx
    from app.analysis import llm as llm_mod

    class _Resp:
        def __init__(self, ok):
            self._ok = ok
        def raise_for_status(self):
            if not self._ok:
                raise httpx.HTTPStatusError("bad", request=None, response=None)
        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

    queue = list(ok_providers)  # shared across concurrent probe clients

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, headers=None, json=None):
            ok = queue.pop(0) if queue else False
            return _Resp(ok)

    with patch.object(llm_mod, "get_configured_providers",
                      return_value=[_fake_provider(), _fake_provider()]), \
         patch.object(llm_mod, "has_any_api_key", return_value=True), \
         patch("httpx.AsyncClient", _Client):
        return await llm_mod.llm_health_check(timeout=timeout)


@pytest.mark.asyncio
async def test_F7_health_ok_when_provider_available():
    report = await _run_health_check([True, True])
    assert report["status"] == "ok"
    assert report["has_api_key"] is True
    assert len(report["providers"]) == 2
    assert all(p["ok"] for p in report["providers"])
    assert all(p["status"] == "available" for p in report["providers"])


@pytest.mark.asyncio
async def test_F7_health_degraded_when_all_fail():
    report = await _run_health_check([False, False])
    assert report["status"] == "degraded"
    assert all(p["ok"] is False for p in report["providers"])
    assert all(p["error"] is not None for p in report["providers"])


@pytest.mark.asyncio
async def test_F7_health_ok_if_any_provider_up():
    report = await _run_health_check([False, True])
    assert report["status"] == "ok"
    assert report["providers"][0]["ok"] is False
    assert report["providers"][1]["ok"] is True


@pytest.mark.asyncio
async def test_F7_health_no_key():
    from app.analysis import llm as llm_mod
    with patch.object(llm_mod, "has_any_api_key", return_value=False):
        report = await llm_mod.llm_health_check()
    assert report["status"] == "no_key"
    assert report["has_api_key"] is False
    assert report["providers"] == []


# ─── F3: HK/US search enrichment ──────────────────────────────────

@pytest.mark.asyncio
async def test_F3_hk_us_static_match_without_keyword():
    from app.services import market_service as ms
    # No enrichment -> pure static map
    with patch.object(ms, "get_asset_realtime", new=AsyncMock(return_value=None)):
        res = await ms.search_hk_us("", enrich=False)
    assert len(res) > 0
    assert all(r["market"] in ("HK", "US") for r in res)
    assert "price" not in res[0]


@pytest.mark.asyncio
async def test_F3_hk_us_enriched_with_live_quote():
    from app.services import market_service as ms

    async def _fake_quote(symbol, market):
        return {"price": 25.6, "change_pct": 1.23}

    with patch.object(ms, "get_asset_realtime", new=_fake_quote):
        res = await ms.search_hk_us("盈富", enrich=True)
    assert len(res) >= 1
    hit = next(r for r in res if r["symbol"] == "02800.HK")
    assert hit["price"] == 25.6
    assert hit["change_pct"] == 1.23


@pytest.mark.asyncio
async def test_F3_hk_us_enrich_falls_back_on_error():
    from app.services import market_service as ms

    async def _boom(symbol, market):
        raise RuntimeError("network down")

    # Even if live enrich fails, static result must be returned (no raise)
    with patch.object(ms, "get_asset_realtime", new=_boom):
        res = await ms.search_hk_us("SPY", enrich=True)
    assert any(r["symbol"] == "SPY" for r in res)
    assert "price" not in res[0]  # enrichment failed -> no price field


# ─── F11: demjson -> orjson/json shim ────────────────────────────

def test_F11_shim_fast_path_for_strict_json():
    import sys, types
    import app.core.fast_json as fast_json

    # Fake demjson module: its real decode records a call and echoes input.
    fake = types.ModuleType("demjson")
    fake.decode = lambda text, *a, **k: f"ORIG:{text}"

    fast_json.reset_demjson_shim()
    saved = sys.modules.get("demjson")
    sys.modules["demjson"] = fake
    try:
        assert fast_json.install_demjson_shim() is True
        # strict JSON -> shim takes the fast path, original NOT called
        assert fake.decode('{"a": 1}') == {"a": 1}
        # non-strict JSON -> shim falls back to original demjson
        assert fake.decode('{"a": 1,}') == 'ORIG:{"a": 1,}'
    finally:
        if saved is None:
            sys.modules.pop("demjson", None)
        else:
            sys.modules["demjson"] = saved
        fast_json.reset_demjson_shim()


def test_F11_shim_noop_when_demjson_absent():
    import sys
    import app.core.fast_json as fast_json

    saved = sys.modules.get("demjson")
    sys.modules.pop("demjson", None)  # pretend demjson not installed
    fast_json.reset_demjson_shim()
    try:
        assert fast_json.install_demjson_shim() is False
    finally:
        if saved is not None:
            sys.modules["demjson"] = saved
        fast_json.reset_demjson_shim()


# ─── F9: ETF scan batching (parallel gtimg chunks) ───────────────

def test_F9_gtimg_batch_merges_chunks():
    from app.fetchers import etf_scanner as es

    def _fake_chunk(chunk):
        # mark which codes came through this chunk
        return {c: {"amount": len(chunk), "turnover": 0,
                    "fund_scale": 0, "pe": 0} for c in chunk}

    codes = [f"5{i:05d}" for i in range(350)]  # 4 chunks of 100/100/100/50
    with patch.object(es, "_tencent_gtimg_chunk", side_effect=_fake_chunk):
        merged = es._tencent_gtimg_batch(codes)
    # all codes present, merged across parallel chunks
    assert set(merged.keys()) == set(codes)
    assert merged[codes[0]]["amount"] == 100  # chunk size preserved


def test_F9_gtimg_batch_small_input_serial():
    from app.fetchers import etf_scanner as es

    calls = []

    def _fake_chunk(chunk):
        calls.append(tuple(chunk))
        return {c: {"amount": 1, "turnover": 0, "fund_scale": 0, "pe": 0} for c in chunk}

    # 2 chunks -> serial path (<=2 chunks)
    codes = [f"5{i:05d}" for i in range(150)]
    with patch.object(es, "_tencent_gtimg_chunk", side_effect=_fake_chunk):
        merged = es._tencent_gtimg_batch(codes)
    assert set(merged.keys()) == set(codes)
    assert len(calls) == 2  # serial: exactly 2 chunk calls
