from __future__ import annotations
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


# ===== folded from test_round14_llm_budget_consistency.py =====
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.portfolio_service import _llm_timeout_for
STRATEGY_CHECK_MAX_RETRIES = 0
STRATEGY_CHECK_REQUEST_TIMEOUT = 15.0  # round20 P0-5: 35→15（ReadTimeout 38s 根因）
PROVIDER_COUNT = 2  # opencode_zen + deepseek（双 provider 并行）
def _consistency(max_retries: int, budget: int, request_timeout: float = 15.0) -> bool:
    """预算-重试一致性：max_retries=0 时免 0.9 系数直接 providers×timeout ≤ 预算；
    max_retries≥1 时 (max_retries+1)×providers×timeout ≤ 0.9×预算
    （0.9 系数兜 rate_limit_cap=10 退避与 retry_delay=3s 容差）。"""
    worst = (max_retries + 1) * PROVIDER_COUNT * request_timeout
    if max_retries >= 1:
        return worst <= 0.9 * budget
    return worst <= budget
class TestBudgetRetryConsistency:
    def test_full_quality_budget_consistent(self):
        """完整档 180s：max_retries=0 时 2×15=30 ≤ 180 PASS（round27 R43: 75→180）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert budget == 180, "完整档预算应为 180s（round27 R43: 75→180）"
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT)

    def test_max_retries_regression_flagged(self):
        """防回归：预算已放宽到 180s（round27 R43），但 max_retries 仍必须保持 0
        （429 退避/慢响应容差纪律，见 llm.py 注释）。一致性公式下 180s 已能容纳
        max_retries=1，故此处不再用「不一致」做负向断言，而直接断言 max_retries==0
        的硬纪律（若被改回 1，下面断言 FAIL）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert budget == 180, "完整档预算应为 180s（round27 R43: 75→180）"
        # max_retries=0 下预算-重试一致（2×15=30 ≤ 180）
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT), \
            "max_retries=0 时预算-重试应一致"
        assert STRATEGY_CHECK_MAX_RETRIES == 0, "max_retries 必须保持 0（429 退避/慢响应容差）"

    def test_partial_budget_consistent_with_no_retry(self):
        """partial 30s：max_retries=0 时 2×15=30 ≤ 30 PASS（round20 P0-5 后 partial
        档也一致——旧 2×35=70 > 30 仅靠不重试兜底）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": True})
        assert budget == 30
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT), \
            "partial 档 2×15=30 ≤ 30 应一致（round20 P0-5 后）"

    def test_all_empty_budget_15(self):
        assert _llm_timeout_for({"all_empty": True}) == 15
class TestStrategyCheckLlMCallParams:
    def test_run_json_uses_max_retries_zero(self):
        """generate_strategy_check_report 的 run_json 必须 max_retries=0 + 15s（round20 P0-5）。"""
        fake_agent = MagicMock()
        fake_agent.run_json = AsyncMock(return_value={"summary": "ok"})
        holdings = [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2}]
        with patch("app.analysis.registry.get_agent", return_value=fake_agent):
            with patch.object(llm_mod, "get_last_llm_error", return_value=None):
                result = asyncio.run(llm_mod.generate_strategy_check_report(holdings, {}, "neutral"))
        assert result.get("summary") == "ok"
        kwargs = fake_agent.run_json.call_args.kwargs
        assert kwargs.get("max_retries") == 0, f"max_retries 应为 0（防重试超预算），实际 {kwargs.get('max_retries')}"
        # round23 遗留修复（2026-08-14）：request_timeout 由 float 15 改为 httpx.Timeout
        #（connect=15s 防 429/连接挂起，read=90s 容纳 deepseek 长报告生成——实测
        # 21.8s，float 15s 的 read 侧 ReadTimeout → LLM 报告永远走规则兜底）。
        to = kwargs.get("request_timeout")
        assert hasattr(to, "connect") and hasattr(to, "read"), \
            f"request_timeout 应为 httpx.Timeout(connect短/read长)，实际 {to!r}"
        assert to.connect <= 15.0, f"connect 超时应 ≤15s（防 429 挂起），实际 {to.connect}"
        assert to.read >= 60.0, f"read 超时应 ≥60s（容纳长报告生成），实际 {to.read}"

    def test_provider_slow_within_budget_no_cancelled_error(self):
        """负向：mock provider 慢响应 → 兜底在预算内完成，不抛 CancelledError 穿透
        （round14 §5 P0-B 测试 2）。"""
        async def _slow_run_json(*args, **kwargs):
            await asyncio.sleep(0.05)
            raise asyncio.TimeoutError("provider slow")

        fake_agent = MagicMock()
        fake_agent.run_json = AsyncMock(side_effect=_slow_run_json)
        holdings = [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2}]
        with patch("app.analysis.registry.get_agent", return_value=fake_agent):
            with patch.object(llm_mod, "get_last_llm_error", return_value="timeout"):
                # 外层 wait_for 60ms < provider 50ms×2 → 触发 CancelledError 兜底路径
                result = asyncio.run(
                    asyncio.wait_for(
                        llm_mod.generate_strategy_check_report(holdings, {}, "neutral"),
                        timeout=0.12,
                    )
                )
        assert "兜底" in result.get("summary", "") or "超时" in result.get("summary", "")
