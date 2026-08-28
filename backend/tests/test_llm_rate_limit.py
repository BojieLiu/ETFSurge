# -*- coding: utf-8 -*-
"""F3-6: LLM 429 限流重试（指数退避 ≤30s + Retry-After 尊重 + 「LLM 限流，已降级」提示）。

验收：单次分析失败前至少 2 次重试（LLM_MAX_RETRIES=2 → 3 轮尝试）。
"""
import asyncio
import time

import httpx
import pytest

from app.analysis import llm


async def _noop(*a, **kw):
    return None


def _make_provider():
    return llm.ProviderConfig(
        id="test", name="test", model="m",
        api_key="k", api_url="http://llm.test/v1/chat/completions",
        timeout=5.0,
    )


def _make_429_exc(headers=None):
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers=headers or {})
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


@pytest.mark.asyncio
async def test_llm_complete_429_opens_circuit_no_retry(monkeypatch):
    """round23 F8/F9: 429（额度耗尽）立即 OPEN，不再重复探测白等退避。

    旧行为：429 后指数退避重试 ≥2 次（每调用缴 2.1-2.4s 过路费）。
    新行为：收到 429 立即置 OPEN，本轮后续 attempt 直接跳过，快速失败。
    """
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            calls["n"] += 1
            raise _make_429_exc()

    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(asyncio, "sleep", _noop)
    llm.reset_circuit()

    with pytest.raises(RuntimeError, match="LLM 限流，已降级"):
        await llm.llm_complete("prompt")
    # 429 → 立即 OPEN → 下一 attempt 直接跳过，不再重试
    assert calls["n"] == 1, f"429 不应重试，实际 {calls['n']} 次"
    assert llm._circuit_state("test") == "OPEN"


@pytest.mark.asyncio
async def test_llm_complete_transient_5xx_flat_backoff(monkeypatch):
    """round23 F8/F9: 瞬态 5xx 保留有限重试，退避为固定 retry_delay（非 429 指数退避）。

    阈值 2：前 2 次实际调用，第 3 次被 OPEN 跳过 → 2 次退避，每次 3.0s（flat）。
    """
    sleeps = []
    attempts = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            attempts["n"] += 1
            raise _make_5xx_exc()

    def _make_5xx_exc():
        req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
        resp = httpx.Response(500, request=req)
        return httpx.HTTPStatusError("500", request=req, response=resp)

    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    llm.reset_circuit()

    with pytest.raises(Exception):
        await llm.llm_complete("prompt")
    assert attempts["n"] == 2, f"瞬态应重试至阈值，实际 {attempts['n']}"
    # 阈值 2：第 2 次失败后 OPEN，第 3 次 attempt 直接跳过 → 仅 1 次退避
    assert sleeps == [3.0], f"瞬态退避应为固定 3.0s（1 次），实际 {sleeps}"


@pytest.mark.asyncio
async def test_llm_complete_no_exponential_backoff_on_429(monkeypatch):
    """回归：429 不再触发指数退避（3s→6s），立即 OPEN 无退避等待。"""
    sleeps = []

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise _make_429_exc()

    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    llm.reset_circuit()

    with pytest.raises(RuntimeError, match="LLM 限流，已降级"):
        await llm.llm_complete("prompt")
    assert sleeps == [], f"429 不应有任何退避等待，实际 {sleeps}"


@pytest.mark.asyncio
async def test_llm_stream_429_opens_circuit(monkeypatch):
    """round23 F9: 流式版本 429 → 立即 OPEN，不再重复探测，error 事件带「LLM 限流，已降级」。"""
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **kw):
            calls["n"] += 1
            return _FakeStream()

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            raise _make_429_exc()

    monkeypatch.setattr(llm.client, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm.client, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(asyncio, "sleep", _noop)
    llm.reset_circuit()

    events = [ev async for ev in llm.llm_complete_stream("sys", "prompt")]
    assert calls["n"] == 1, f"流式 429 不应重试，实际 {calls['n']}"
    err = next((ev for ev in events if ev.get("type") == "error"), None)
    assert err and "LLM 限流，已降级" in err["error"], f"实际: {events}"


# ── R5-1-1: design/check 任务 LLM 互斥（同一时间仅 1 个 LLM 任务在跑） ─────
class _FakeMgr:
    """最小 TaskManager mock：get_task / update_task 记录调用。"""

    def __init__(self):
        self.updated = []

    async def get_task(self, task_id):
        return {"task_id": task_id, "type": "check", "params": {"capital": 100000}}

    async def update_task(self, task_id, **kw):
        self.updated.append((task_id, kw))
        return None


async def test_strategy_check_worker_uses_shared_llm_semaphore(monkeypatch):
    """R5-1-1: strategy_check_pipeline 与 design_pipeline 共享 LLM 互斥信号量。

    预热期并发场景：两个 check 任务同时提交 → 同一时间仅 1 个进入 LLM 阶段
    （asyncio.Semaphore(1) 串行化），不出现双任务并发打满 DeepSeek 配额。
    """
    from app.tasks import task_manager
    from app.tasks import strategy_check_worker

    concurrent = {"active": 0, "max_active": 0}

    async def _fake_pipeline_body(mgr, task_id):
        concurrent["active"] += 1
        concurrent["max_active"] = max(concurrent["max_active"], concurrent["active"])
        await asyncio.sleep(0.05)  # 模拟 LLM 调用耗时
        concurrent["active"] -= 1
        return {}

    # 用真实 _design_semaphore 验证互斥生效（不替换信号量本体）
    monkeypatch.setattr(strategy_check_worker, "_strategy_check_pipeline_guarded", _fake_pipeline_body)

    mgr = _FakeMgr()
    await asyncio.gather(
        strategy_check_worker.strategy_check_pipeline(mgr, 1),
        strategy_check_worker.strategy_check_pipeline(mgr, 2),
    )
    # 若互斥生效：两任务并发时同时活跃数 ≤1
    assert concurrent["max_active"] == 1, \
        f"R5-1-1 互斥失效：同时活跃 {concurrent['max_active']} 个任务"

    # 互斥信号量来自 task_manager（design 与 check 共享同一把锁）
    import inspect
    src = inspect.getsource(strategy_check_worker.strategy_check_pipeline)
    assert "_design_semaphore" in src, \
        "check 任务必须复用 task_manager 的共享 LLM 互斥信号量（design/check 共用）"


# ===================================================================
# merged from test_round25_r39_llm_quota_gate.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round25 R39: 跨任务 LLM 配额门禁 LLMQuotaGate。

问题（round25 §0.3 P1-8 / §2.8）：design↔strategy_check 已被 _design_semaphore 串行，
但无冷却/预算，信号量释放即发；enrich_news_summaries 更在信号量外独立发 LLM 调用 →
背靠背 strategy-check 恒 429。修复：集中式 LLMQuotaGate 单例，任意两次 LLM 调用间隔
≥ inter_call_cooldown，429 后全局暂停 quota_cooldown（后续调用直落兜底不硬撞配额）。
"""
import asyncio
from unittest.mock import patch

import pytest

from app.analysis.llm import LLMQuotaGate


@pytest.mark.asyncio
async def test_acquire_enforces_min_gap_between_calls():
    """两次调用间隔必须 ≥ inter_call_cooldown（跨任务冷却）。

    注：time.monotonic 真实值很大，类默认 _last=0 远在过去 → 首次调用等待 0；
    本测试用大基准时钟（1000s）模拟该语义。
    """
    gate = LLMQuotaGate()
    gate.inter_call_cooldown = 8.0
    fake = {"t": 1000.0}
    sleeps = []

    def fake_monotonic():
        return fake["t"]

    async def fake_sleep(d):
        sleeps.append(d)
        fake["t"] += d

    with patch("app.analysis.llm.time.monotonic", side_effect=fake_monotonic), \
            patch("app.analysis.llm.asyncio.sleep", side_effect=fake_sleep):
        await gate.acquire()           # 首次（_last=0 远在过去）→ 等待 0（不 sleep）
        await gate.acquire()           # 紧接第二次（now 未推进）→ 必须等待完整 gap 8.0
    # 首次 wait=0 跳过 sleep；第二次紧接 → sleep 完整 cooldown
    assert sleeps == [8.0]


@pytest.mark.asyncio
async def test_mark_exhausted_pauses_subsequent_acquire():
    """429 后全局暂停 quota_cooldown，后续调用直落兜底不硬撞。"""
    gate = LLMQuotaGate()
    gate.inter_call_cooldown = 8.0
    gate.quota_cooldown = 60.0
    fake = {"t": 1000.0}
    sleeps = []

    def fake_monotonic():
        return fake["t"]

    async def fake_sleep(d):
        sleeps.append(d)
        fake["t"] += d

    with patch("app.analysis.llm.time.monotonic", side_effect=fake_monotonic), \
            patch("app.analysis.llm.asyncio.sleep", side_effect=fake_sleep):
        await gate.acquire()           # 等待 0
        gate.mark_exhausted()          # exhausted_until = 1060
        fake["t"] = 1002.0
        await gate.acquire()           # now=1002, exhausted_until=1060 → 等待 58
    assert sleeps[-1] == 58.0


@pytest.mark.asyncio
async def test_circuit_429_triggers_quota_exhausted():
    """round39 改进: 单 429 不再联动 mark_exhausted（避免其它可用模型被连坐）。
    仅「整 provider 全 model 都 429」时由 _circuit_record_failure_all_models_quota
    显式触发全局暂停。
    """
    from app.analysis import llm as llm_mod

    fake = {"t": 1000.0}

    def fake_monotonic():
        return fake["t"]

    with patch("app.analysis.llm.time.monotonic", side_effect=fake_monotonic):
        llm_mod.llm_quota_gate._exhausted_until = 0.0
        # 单 429：熔断该 (provider, model) 但**不**触发全局 mark_exhausted
        llm_mod._circuit_record_failure("deepseek", is_quota_error=True, model="ds-v1")
        assert llm_mod._circuit_state("deepseek", "ds-v1") == "OPEN"
        # 关键断言：exhausted_until 应仍为 0（未触发全局暂停）
        assert llm_mod.llm_quota_gate._exhausted_until == 0.0, (
            "单模型 429 不应触发全局 mark_exhausted，否则其它模型被连坐"
        )
        # 兜底路径：整 provider 全 model 都 429 → 触发全局暂停
        llm_mod._circuit_record_failure_all_models_quota("deepseek", models=["ds-v1"])
        assert llm_mod.llm_quota_gate._exhausted_until > 0.0
