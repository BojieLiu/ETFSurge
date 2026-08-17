"""round27 R43: 策略检查 LLM 超时 75s → 180s（反假完成测试）。

验收（doc §15.1 R43）：`_llm_timeout_for` 「数据完整」分支 75→180，使 DeepSeek 流式
首字节实测 34-78s 的场景不再几乎必然超时（恒落规则兜底）。

负向断言：
① 数据完整 → 180（不再 75）；② 分支分级保持不变（all_empty=15 / partial=30）；
③ 模拟「LLM 首字节 60s、生成到 120s」场景下，180s 预算能容纳（旧 75s 必截断）。
"""
import pytest

from app.services.portfolio_service import _llm_timeout_for


def test_data_complete_timeout_is_180_not_75():
    """R43 主修复：数据完整分支必须 180s（负向：仍是 75 → FAIL）。"""
    dq_full = {"all_empty": False, "partial": False}
    assert _llm_timeout_for(dq_full) == 180, "数据完整分支应为 180s（round27 R43: 75→180）"


def test_timeout_tiers_unchanged():
    """分支分级保持：all_empty=15 / partial=30 / full=180。"""
    assert _llm_timeout_for({"all_empty": True}) == 15
    assert _llm_timeout_for({"all_empty": False, "partial": True}) == 30
    assert _llm_timeout_for({"all_empty": False, "partial": False}) == 180


def test_full_budget_absorbs_real_first_byte():
    """R43 现实证真：DeepSeek 首字节实测 34-78s、单报告更长，180s 预算可容纳；
    旧 75s 在首字节 60s 时仅剩 15s 生成 → 必超时。
    """
    budget = _llm_timeout_for({"all_empty": False, "partial": False})
    first_byte = 60.0  # 首字节实测上沿附近
    assert budget > first_byte, "180s 预算应大于首字节延迟，留出生成余量"
    assert budget - first_byte >= 60.0, "至少应留 60s 生成余量（否则复现旧 75s 截断）"
