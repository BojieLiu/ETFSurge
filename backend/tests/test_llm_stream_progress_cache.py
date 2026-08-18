# -*- coding: utf-8 -*-
"""R49: LLM 流式首字节前可见进度 + 交易日内结果缓存。

反假完成负向断言：
1. progress 事件必须在首字节（首个 token）之前产出——验证「首字节前有可见进度」。
2. 同 query 二次请求命中缓存，不再调用 LLM 且返回时间显著更短（≤ 缓存命中阈值）。
3. 同 query 但不同市场数据（prompt 不同）→ 缓存不串味（miss，再次调用 LLM）。
"""
import asyncio
import time

import pytest

from app.analysis.llm import (
    run_stream_with_cache,
    _REPORT_CACHE,
    _REPORT_CACHE_LOCK,
)


def _clear_cache():
    with _REPORT_CACHE_LOCK:
        _REPORT_CACHE.clear()


@pytest.mark.asyncio
async def test_progress_event_before_first_token():
    """首字节前必产 progress 事件，且先于任何 token（反假：禁止空白等待）。"""
    # 模拟 first_byte 34-78s 延迟：首个 token 前 sleep
    async def slow_agent_stream(prompt, **kwargs):
        await asyncio.sleep(0.2)
        yield {"event": "token", "data": {"token": "你"}}
        yield {"event": "done", "data": {"full_text": "你好世界", "usage": {}}}

    from app.routers.analysis import _sse_stream

    async def _factory():
        return slow_agent_stream("p")

    resp = _sse_stream(_factory)
    events = []
    async for chunk in resp.body_iterator:
        if not isinstance(chunk, str):
            chunk = chunk.decode("utf-8", errors="replace")
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                events.append(line[len("event: "):].strip())

    assert events[0] == "progress", f"首事件应为 progress，实际 {events}"
    assert "token" in events, "应存在 token 事件"
    assert events.index("progress") < events.index("token"), "progress 必须早于首个 token"


@pytest.mark.asyncio
async def test_progress_before_prefetch_io():
    """R49: 重 I/O（上下文采集/取数）在 factory 内、首字节(progress) 之后发生——
    即便采集很慢，首 SSE 事件仍是 progress（反假：禁止重 I/O 阻塞首字节）。

    实现契约：_sse_stream(agent_gen_factory) 先 yield progress，再 await factory；
    若 factory 在返回 agent 生成器前 sleep，first_byte 不应被该 sleep 阻塞。
    """
    async def slow_factory():
        await asyncio.sleep(0.2)  # 模拟 build_full_context / 历史 K 线取数等重 I/O
        async def agent_gen():
            yield {"event": "token", "data": {"token": "结"}}
            yield {"event": "done", "data": {"full_text": "分析结果", "usage": {}}}
        return agent_gen()

    from app.routers.analysis import _sse_stream

    resp = _sse_stream(slow_factory)
    events = []
    async for chunk in resp.body_iterator:
        if not isinstance(chunk, str):
            chunk = chunk.decode("utf-8", errors="replace")
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                events.append(line[len("event: "):].strip())

    assert events[0] == "progress", f"首事件应为 progress（未被重 I/O 阻塞），实际 {events}"
    assert "token" in events and "done" in events


@pytest.mark.asyncio
async def test_cache_hit_skips_llm_and_is_faster():
    """同 query 二次请求命中缓存：不二次调用 LLM，且返回更快。"""
    call_count = {"n": 0}

    def _make_agent():
        async def stream_fn(prompt, **kwargs):
            call_count["n"] += 1
            await asyncio.sleep(0.3)  # 模拟慢首字节
            yield {"event": "token", "data": {"token": "实时"}}
            yield {"event": "done", "data": {"full_text": "实时分析结果", "usage": {"total_tokens": 10}}}

        class _A:
            def run_stream(self, p, **kw):
                return stream_fn(p, **kw)
        return _A()

    try:
        prompt = "同一问题 + 同一市场数据快照"
        # 首次：缓存未命中 → 真实调用（慢）
        t0 = time.monotonic()
        e1 = [ev async for ev in run_stream_with_cache(_make_agent(), prompt, query="advice:q", data_as_of=None)]
        dt_first = time.monotonic() - t0
        assert call_count["n"] == 1
        assert any(ev.get("event") == "done" for ev in e1)

        # 二次：缓存命中 → 不调用 LLM，秒级返回
        t0 = time.monotonic()
        e2 = [ev async for ev in run_stream_with_cache(_make_agent(), prompt, query="advice:q", data_as_of=None)]
        dt_second = time.monotonic() - t0
        assert call_count["n"] == 1, "命中缓存不应再次调用 LLM"
        assert dt_second < dt_first, f"命中应更快：{dt_second:.3f} < {dt_first:.3f}"
        done = [ev for ev in e2 if ev.get("event") == "done"][0]
        assert done["data"].get("cached") is True
    finally:
        _clear_cache()


@pytest.mark.asyncio
async def test_cache_miss_for_different_market_data():
    """同 query 但不同市场数据（prompt 不同）→ 缓存不串味，仍调用 LLM。"""
    call_count = {"n": 0}

    def _make_agent():
        async def stream_fn(prompt, **kwargs):
            call_count["n"] += 1
            yield {"event": "done", "data": {"full_text": "结果", "usage": {}}}

        class _A:
            def run_stream(self, p, **kw):
                return stream_fn(p, **kw)
        return _A()

    try:
        q = "advice:相同问题"
        # 不同 prompt 指纹（模拟不同市场数据快照）
        await _collect(run_stream_with_cache(_make_agent(), "prompt-snapshot-A", query=q, data_as_of=None))
        await _collect(run_stream_with_cache(_make_agent(), "prompt-snapshot-B", query=q, data_as_of=None))
        assert call_count["n"] == 2, "不同市场数据不应命中同一缓存"
    finally:
        _clear_cache()


async def _collect(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out
