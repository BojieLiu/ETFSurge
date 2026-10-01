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
    # round59 R05: reset_circuit() 不含 403 streak/blocked_until（模块级独立 dict），
    # 不显式复位则 403 连击会跨用例泄漏——本文件用 403 造阻断，泄漏会让后续用例
    # 凭空跳过 provider，制造与生产无关的假失败。
    llm.client._r05_403_reset()
    llm.reset_circuit()
    yield
    llm.client._r05_403_reset()
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

    # round39: 429 TTL 改为 _CIRCUIT_TTL_QUOTA (30min) 而非 _CIRCUIT_TTL (5min)
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + llm._CIRCUIT_TTL_QUOTA + 1)

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


@pytest.mark.asyncio
async def test_r04_cloudflare_403_leads_to_permanent_error_and_exclusion(monkeypatch):
    """R04: Cloudflare 403 with specific headers is classified as permanent error,
    leading to long-cooldown and model exclusion on first hit.
    """
    # Part 1: Test the classifier directly
    from app.analysis.llm import gates
    exc = httpx.HTTPStatusError(
        "403 Client Error",
        request=httpx.Request("POST", "http://test"),
        response=httpx.Response(403, request=httpx.Request("POST", "http://test"),
                              text="Server: cloudflare\nx-opencode-log-id: abc123\n")
    )
    assert gates._classify_permanent_error(exc) is True

    # Part 2: Test the circuit breaker consequence in llm_complete (non-stream)
    # Reset circuit state (done by autouse fixture, but we do it explicitly for clarity)
    llm.reset_circuit()
    from app.analysis.llm import model_catalog
    # round59: model_catalog._exclusions 是**进程级全局单例**。只 clear 不还原会
    # 污染同 worker 内的其它用例——实测导致 -n auto 下
    # test_factor_compute_injects_mv.py::test_nav_one_uses_long_running_executor
    # 偶发红（单跑绿）。这里做快照/还原，而不是 clear。
    _saved_exclusions = set(model_catalog.model_catalog._exclusions)
    model_catalog.model_catalog._exclusions.clear()
    try:
        # Set up a single provider that returns the Cloudflare 403 error
        client = _FakeClient([exc])  # The effect list has one exception
        monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_prov("opencode_zen")])
        monkeypatch.setattr(llm.client, "_check_key", _noop)
        monkeypatch.setattr(llm.token_store, "record", _noop)
        monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
        monkeypatch.setattr(asyncio, "sleep", _noop)

        # Call llm_complete; it should fail because the provider fails and there are no more providers
        # round59: the escaping type depends on the path (llm_complete re-raises the
        # provider error; llm_complete_with_system raises a RuntimeError carrying the
        # 403 wording). The contract under test is "the call fails AND the model was
        # permanently dropped", so accept either escape.
        with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
            await llm.llm_complete("prompt")

        # Check that the model is in long cooldown and excluded
        assert llm.gates.is_long_cooldown("opencode_zen", "m") is True
        assert model_catalog.model_catalog.is_excluded("opencode_zen", "m") is True
    finally:
        model_catalog.model_catalog._exclusions.clear()
        model_catalog.model_catalog._exclusions.update(_saved_exclusions)

# ---------------------------------------------------------------------------
# round59 R05: SSE 路径的 403 连击熔断
#
# 缺陷（doc M6）：llm_complete_stream 只**读**熔断（:335 的 _r05_403_allow），
# 从不**写**——修复前该函数内零 _r05_403_record 调用。于是连击数永不累计、
# 熔断永不触发，每次调用都要把同一批死模型重新探一遍（实测 6/7 候选 403，
# 单次白等 ≈6s，token_usage.db id 63478-63484）。
#
# 断言口径是"实际发出的探测次数"，不是状态标志位——状态对了但请求仍发出去，
# 白等成本一分没省。
# ---------------------------------------------------------------------------


def _make_403_stream_exc(signature: bool = True):
    """opencode.ai 对被拒免费模型的真实形态：特征串在响应**头**，体为空。

    `content=b""` 而非 `resp.text = ""`——httpx 的 text 是只读 property。

    `signature=False` 造一个**无特征串**的普通 403。R04/R05 是两层不同的闸：
    R04 按特征串把模型永久摘除（`mark_excluded`，落 app_config 跨重启）；
    R05 按**任意** 403 的连击数把 provider 拉黑 60s。用带特征串的 403 测 R05
    会被 R04 的通用熔断抢先（circuit 直接 OPEN + quota gate），测到的是 R04
    而不是 R05——这是本文件第一版 R05 用例的真实失败原因。
    """
    req = httpx.Request("POST", "http://x")
    if signature:
        resp = httpx.Response(403, request=req, content=b"", headers={
            "server": "cloudflare", "x-opencode-log-id": "abc123", "cf-ray": "7-"})
    else:
        resp = httpx.Response(403, request=req, content=b"Forbidden",
                              headers={"server": "nginx"})
    return httpx.HTTPStatusError("403 Client Error", request=req, response=resp)


class _FakeStreamResp:
    def __init__(self, exc=None):
        self._exc = exc
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1
        if self._exc is not None:
            raise self._exc

    async def aiter_lines(self):
        # 2 个 token 事件（<2 会被判 dropout 换候选）+ [DONE]
        yield 'data: {"choices":[{"delta":{"content":"支撑位"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"在 3821.74"}}]}'
        yield "data: [DONE]"


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeStreamClient:
    """按 side_effect 列表逐次返回流式响应，并统计按 provider 的探测次数。"""

    def __init__(self, effects):
        self._effects = list(effects)
        self.probes = {"zen": 0, "deepseek": 0}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **kw):
        auth = (kw.get("headers") or {}).get("Authorization", "")
        prov = "zen" if "zen" in auth else "deepseek"
        self.probes[prov] += 1
        eff = self._effects.pop(0) if self._effects else _FakeStreamResp()
        if isinstance(eff, Exception):
            eff = _FakeStreamResp(exc=eff)
        return _FakeStreamCtx(eff)


async def _drain(gen):
    return [item async for item in gen]


@pytest.mark.asyncio
async def test_r05_stream_two_403s_then_provider_is_not_probed_again(monkeypatch):
    """R05 核心负向：连续 2 次 403 后，第 3 次调用对该 provider 零探测。

    修复前该断言必然失败（stream 路径从不 record，streak 恒为 0）。
    """
    llm.client._r05_403_reset()
    effects = [
        _make_403_stream_exc(signature=False), _make_403_stream_exc(signature=False),
        _FakeStreamResp(),                                    # 第 2 次调用：若仍探测则成功
    ]
    fake = _FakeStreamClient(effects)
    monkeypatch.setattr(
        llm.client, "get_configured_providers", lambda: [_prov("opencode_zen")]
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    # 第 1 次调用：两轮 403 后 provider 被拉黑 -> 抛错
    out1 = await _drain(llm.llm_complete_stream("sys", "p"))
    assert any(i.get("type") == "error" for i in out1), out1
    assert fake.probes["zen"] == 2, fake.probes
    assert not llm.client._r05_403_allow("opencode_zen"), "2 次 403 后应被拉黑 60s"

    # 第 2 次调用：必须**零探测**（省掉的就是那 ~6s 白等）
    out2 = await _drain(llm.llm_complete_stream("sys", "p"))
    assert fake.probes["zen"] == 2, f"403 熔断未生效，仍探测了 {fake.probes}"
    assert any(i.get("type") == "error" for i in out2), out2


@pytest.mark.asyncio
async def test_r05_stream_success_between_403s_resets_streak(monkeypatch):
    """负向：成功必须清零 403 连击——否则 403/成功交替会把 provider 拉黑。

    断言设计要点：只测"重置后仍可用"是弱断言，修复前后都为真、抓不住缺陷。
    因此末尾追加**两次连续 403 必须拉黑**——只有 streak 真的被记录过、
    又真的被清零过，才会走到"恰好第 2 次触发"。修复前 streak 恒为 0，
    该断言必然失败。
    """
    llm.client._r05_403_reset()
    effects = [
        _make_403_stream_exc(signature=False), _FakeStreamResp(),   # 403 -> 成功（清零）
        _make_403_stream_exc(signature=False), _FakeStreamResp(),   # 403 -> 成功（清零）
        _make_403_stream_exc(signature=False),                      # 连击 1
        _make_403_stream_exc(signature=False),                      # 连击 2 -> 拉黑
    ]
    fake = _FakeStreamClient(effects)
    monkeypatch.setattr(
        llm.client, "get_configured_providers", lambda: [_prov("opencode_zen")]
    )
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    # 前两轮：403 后成功 -> 完成，且未被拉黑（证明成功清零了连击）
    for _ in range(2):
        out = await _drain(llm.llm_complete_stream("sys", "p"))
        assert any(i.get("type") == "done" for i in out), out
        assert llm.client._r05_403_allow("opencode_zen"), "成功未清零 403 连击"

    # 第三轮：两次连续 403 -> 拉黑（修复前 streak 恒 0，此断言必失败）
    out3 = await _drain(llm.llm_complete_stream("sys", "p"))
    assert any(i.get("type") == "error" for i in out3), out3
    assert fake.probes["zen"] == 6, fake.probes
    assert not llm.client._r05_403_allow("opencode_zen"), "连续 2 次 403 后仍未拉黑"