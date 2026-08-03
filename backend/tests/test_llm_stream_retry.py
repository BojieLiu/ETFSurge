"""R6-F8 (round6 §五 R6-09): LLM 流式偶发断流自动重试。

背景：deepseek 流式偶发断流——首测 events=1 仅 disclaimer（正文空），
HTTP 层成功无异常，现有重试机制（仅异常触发）不覆盖。
修复：正文过短（<20 字符）视为断流，自动重试 1 次（对齐 design task 重试语义）。
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.analysis import llm as llm_mod


class _FakeStreamCtx:
    """模拟 httpx client.stream 的 async context manager + aiter_lines。"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def aiter_lines(self):
        async def _gen():
            for c in self._chunks:
                yield c
        return _gen()


def _make_stream(chunks_seq):
    """构造 mock AsyncClient：stream 按序返回多个 FakeStreamCtx。

    chunks_seq 每个元素是一次 stream 调用的 chunks 列表。
    """
    patcher = patch("httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_instance = mock_cls.return_value.__aenter__.return_value
    ctxs = [_FakeStreamCtx(c) for c in chunks_seq]
    # httpx.AsyncClient.stream 是同步方法返回 async CM——MagicMock 而非 AsyncMock
    mock_instance.stream = MagicMock(side_effect=ctxs)
    return patcher, mock_instance


def _patch_provider_settings(**kwargs):
    from app.config import settings
    defaults = dict(
        llm_primary_provider="deepseek",
        llm_fallback_provider="",
        opencode_zen_api_key="",
        deepseek_api_key="sk-ds-test-key",
        llm_model="deepseek-v4-flash",
        llm_primary_timeout=30,
    )
    defaults.update(kwargs)
    patches = []
    for k, v in defaults.items():
        p = patch.object(settings, k, v)
        p.start()
        patches.append(p)
    return patches


@pytest.fixture(autouse=True)
def _settings():
    patches = _patch_provider_settings()
    yield
    for p in patches:
        p.stop()


def _chunk(token: str) -> str:
    """构造 OpenAI SSE 行。"""
    return f"data: {__import__('json').dumps({'choices': [{'delta': {'content': token}}]})}"


async def test_stream_empty_content_retries_then_succeeds():
    """0 token（仅 [DONE]）→ 自动重试 → 第二次返回完整内容。"""
    dropout = [_chunk(""), "data: [DONE]"]
    ok = [_chunk("正常"), _chunk("报告"), "data: [DONE]"]
    patcher, mock_instance = _make_stream([dropout, ok])
    try:
        events = []
        async for ev in llm_mod.llm_complete_stream("system", "prompt"):
            events.append(ev)
        done = [e for e in events if e["type"] == "done"]
        assert done, "最终应产出 done"
        assert "正常报告" in done[0]["full_text"]
        assert mock_instance.stream.call_count >= 2, "断流后应重试"
    finally:
        patcher.stop()


async def test_stream_short_content_retries():
    """仅 disclaimer（短内容）→ 视为断流重试 → 第二次完整。"""
    short = [_chunk("仅"), "data: [DONE]"]
    ok = [_chunk("完整"), _chunk("报告内容"), "data: [DONE]"]
    patcher, mock_instance = _make_stream([short, ok])
    try:
        events = []
        async for ev in llm_mod.llm_complete_stream("system", "prompt"):
            events.append(ev)
        done = [e for e in events if e["type"] == "done"]
        assert done
        assert "完整报告内容" in done[0]["full_text"]
        assert mock_instance.stream.call_count >= 2
    finally:
        patcher.stop()


async def test_stream_always_empty_yields_error():
    """多次断流（重试后仍空）→ 产出 error 而非静默空 done。"""
    empty = [_chunk(""), "data: [DONE]"]
    patcher, mock_instance = _make_stream([empty, empty])
    try:
        events = []
        async for ev in llm_mod.llm_complete_stream("system", "prompt", max_retries=1):
            events.append(ev)
        types = [e["type"] for e in events]
        assert "error" in types or (types and types[-1] == "done" and not events[-1].get("full_text")), types
    finally:
        patcher.stop()
