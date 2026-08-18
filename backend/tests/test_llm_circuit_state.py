# -*- coding: utf-8 -*-
"""round23 F7/F8/F9: 模块级 TTL 熔断验证。

核心验收（round23 §4.1）:
- zen 持久 429（FreeUsageLimitError，额度耗尽）→ 立即 OPEN、零探测零过路费，
  后续 attempt 直接走 deepseek，zen 不再被重复探测。
- TTL 到期后 HALF_OPEN 复探；成功回 CLOSED、又 429 回 OPEN。
- 两个 provider 都 OPEN（都 429）→ 快速失败（不再白等退避）。
- 瞬态 5xx/timeout 保留有限重试（累计达阈值才 OPEN）。
"""
import asyncio
import time

import httpx
import pytest

from app.analysis import llm


async def _noop(*a, **kw):
    return None


def _prov(pid, timeout=5.0):
    return llm.ProviderConfig(
        id=pid, name=pid, model="m",
        api_key=f"{pid}-key", api_url="http://llm.test/v1/chat/completions",
        timeout=timeout,
    )


def _make_429_exc():
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


def _make_5xx_exc():
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(500, request=req)
    return httpx.HTTPStatusError("500", request=req, response=resp)


def _make_200(content="ok"):
    resp = httpx.Response(200, request=httpx.Request("POST", "http://x"))
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"choices": [{"message": {"content": content}}], "usage": {}}
    return resp


class _FakeClient:
    """按 side_effect 列表依次返回（每次 post 消耗一个），按 Authorization 区分 provider。"""

    def __init__(self, effects):
        self._effects = list(effects)
        self.post_calls = {"n": 0}
        self._by_provider = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        self.post_calls["n"] += 1
        auth = (kw.get("headers") or {}).get("Authorization", "")
        prov = "zen" if "zen" in auth else "deepseek"
        self._by_provider.setdefault(prov, 0)
        self._by_provider[prov] += 1
        eff = self._effects.pop(0)
        if isinstance(eff, Exception):
            raise eff
        return eff


@pytest.fixture(autouse=True)
def _reset_circuit():
    llm.reset_circuit()
    yield
    llm.reset_circuit()


@pytest.mark.asyncio
async def test_429_primary_opens_circuit_and_fails_fast(monkeypatch):
    """单一 provider 持续 429 → 立即 OPEN，不再重试（旧逻辑白等 3 轮）。"""
    client = _FakeClient([_make_429_exc()])
    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_prov("opencode_zen")])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    with pytest.raises(RuntimeError, match="LLM 限流，已降级"):
        await llm.llm_complete("prompt")
    # 关键：429 后不得重复探测（旧行为 ≥3 次）；OPEN 后直接跳出
    assert client.post_calls["n"] == 1, f"429 不应重试，实际 {client.post_calls['n']} 次"
    assert llm._circuit_state("opencode_zen") == "OPEN"


@pytest.mark.asyncio
async def test_429_primary_skipped_after_open_fallback_used(monkeypatch):
    """zen 429 → OPEN；deepseek 成功；zen 全程仅被探测 1 次（零过路费）。"""
    client = _FakeClient([_make_429_exc(), _make_200("fallback-ok")])
    monkeypatch.setattr(
        llm.client, "get_configured_providers",
        lambda: [_prov("opencode_zen"), _prov("deepseek")],
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    result = await llm.llm_complete("prompt")
    assert result == "fallback-ok"
    assert client._by_provider.get("zen", 0) == 1, "zen 不应被重复探测"
    assert client._by_provider.get("deepseek", 0) == 1
    assert llm._circuit_state("opencode_zen") == "OPEN"


@pytest.mark.asyncio
async def test_open_primary_not_reprobed_in_second_call(monkeypatch):
    """zen 仍 OPEN 时第二轮调用直接走 deepseek，zen 探测次数保持 1。"""
    client = _FakeClient([_make_429_exc(), _make_200("fb1"), _make_200("fb2")])
    monkeypatch.setattr(
        llm.client, "get_configured_providers",
        lambda: [_prov("opencode_zen"), _prov("deepseek")],
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    r1 = await llm.llm_complete("prompt")
    r2 = await llm.llm_complete("prompt")
    assert r1 == "fb1" and r2 == "fb2"
    assert client._by_provider.get("zen", 0) == 1


@pytest.mark.asyncio
async def test_transient_5xx_retries_until_threshold(monkeypatch):
    """瞬态 5xx：保留有限重试（累计达阈值才 OPEN），非 429 不立即 OPEN。"""
    client = _FakeClient([_make_5xx_exc(), _make_5xx_exc()])
    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_prov("opencode_zen")])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    with pytest.raises(Exception):
        await llm.llm_complete("prompt")
    # 阈值 2：前 2 次实际调用，第 3 次被 OPEN 跳过
    assert client.post_calls["n"] == 2, f"瞬态应重试至阈值，实际 {client.post_calls['n']}"
    assert llm._circuit_state("opencode_zen") == "OPEN"


@pytest.mark.asyncio
async def test_half_open_recovers_after_ttl(monkeypatch):
    """OPEN 超时 TTL 后转 HALF_OPEN 复探 zen（仍 429）→ 立即回 OPEN；deepseek 兜底。"""
    # zen 两次都 429（OPEN + HALF_OPEN 复探），deepseek 每次都成功
    client = _FakeClient([_make_429_exc(), _make_200("fb1"),
                          _make_429_exc(), _make_200("fb2")])
    monkeypatch.setattr(
        llm.client, "get_configured_providers",
        lambda: [_prov("opencode_zen"), _prov("deepseek")],
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    r1 = await llm.llm_complete("prompt")
    assert r1 == "fb1"
    assert llm._circuit_state("opencode_zen") == "OPEN"
    assert client._by_provider.get("zen", 0) == 1  # 首次 429 触发 OPEN

    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + llm._CIRCUIT_TTL + 1)

    r2 = await llm.llm_complete("prompt")
    assert r2 == "fb2"
    # HALF_OPEN 复探 zen（再次 429）→ 立即回 OPEN；zen 累计探测 2 次
    assert client._by_provider.get("zen", 0) == 2
    assert llm._circuit_state("opencode_zen") == "OPEN"


@pytest.mark.asyncio
async def test_all_providers_open_fails_without_toll(monkeypatch):
    """两个 provider 都 429 → 各自 OPEN，快速失败（不再相互重试白等）。"""
    client = _FakeClient([_make_429_exc(), _make_429_exc()])
    monkeypatch.setattr(
        llm.client, "get_configured_providers",
        lambda: [_prov("opencode_zen"), _prov("deepseek")],
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    with pytest.raises(RuntimeError):
        await llm.llm_complete("prompt")
    assert client.post_calls["n"] == 2
    assert llm._circuit_state("opencode_zen") == "OPEN"
    assert llm._circuit_state("deepseek") == "OPEN"
