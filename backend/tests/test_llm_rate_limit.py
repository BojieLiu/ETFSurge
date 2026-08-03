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
async def test_llm_complete_retries_twice_on_429(monkeypatch):
    """429 时至少重试 2 次（共 3 轮尝试）后才放弃，并抛「LLM 限流，已降级」。"""
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

    monkeypatch.setattr(llm, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    with pytest.raises(RuntimeError, match="LLM 限流，已降级"):
        await llm.llm_complete("prompt")
    # LLM_MAX_RETRIES=2 → 3 轮尝试（失败前重试 ≥2 次）
    assert calls["n"] >= 3, f"应尝试 ≥3 次，实际 {calls['n']}"


@pytest.mark.asyncio
async def test_llm_complete_respects_retry_after(monkeypatch):
    """429 响应带 Retry-After 头 → 退避等待使用 Retry-After 值（cap 30s）。"""
    sleeps = []

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise _make_429_exc(headers={"retry-after": "2"})

    monkeypatch.setattr(llm, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(RuntimeError):
        await llm.llm_complete("prompt")
    assert sleeps, "应发生退避等待"
    assert all(w == 2.0 for w in sleeps), f"应尊重 Retry-After=2s，实际 {sleeps}"


@pytest.mark.asyncio
async def test_llm_complete_exponential_backoff_cap(monkeypatch):
    """无 Retry-After 时指数退避（3s, 6s），cap ≤30s。"""
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

    monkeypatch.setattr(llm, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)

    async def _fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(RuntimeError):
        await llm.llm_complete("prompt")
    # 3 轮尝试间 2 次退避：3s（attempt 0）→ 6s（attempt 1）
    assert len(sleeps) == 2, f"实际退避 {sleeps}"
    assert sleeps[0] == 3.0 and sleeps[1] == 6.0, f"指数退避错误: {sleeps}"


@pytest.mark.asyncio
async def test_llm_stream_retries_on_429(monkeypatch):
    """流式版本 429 → 重试 ≥2 次后 error 事件带「LLM 限流，已降级」。"""
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

    monkeypatch.setattr(llm, "get_configured_providers", lambda: [_make_provider()])
    monkeypatch.setattr(llm, "_check_key", _noop)
    monkeypatch.setattr(llm.token_store, "record", _noop)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(asyncio, "sleep", _noop)

    events = [ev async for ev in llm.llm_complete_stream("sys", "prompt")]
    assert calls["n"] >= 3, f"流式应尝试 ≥3 次，实际 {calls['n']}"
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
