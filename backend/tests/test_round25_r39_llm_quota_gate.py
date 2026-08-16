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
    """_circuit_record_failure(is_quota_error=True) 必须联动 mark_exhausted（集中覆盖三调用点）。"""
    from app.analysis import llm as llm_mod

    fake = {"t": 1000.0}

    def fake_monotonic():
        return fake["t"]

    with patch("app.analysis.llm.time.monotonic", side_effect=fake_monotonic):
        llm_mod.llm_quota_gate._exhausted_until = 0.0
        llm_mod._circuit_record_failure("deepseek", is_quota_error=True)
        # mark_exhausted 将 exhausted_until 设为 now + quota_cooldown
        assert llm_mod.llm_quota_gate._exhausted_until > 0.0
