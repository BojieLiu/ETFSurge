"""
O7 (docs/archived/round8-rediagnosis.md §7 P7-新/R7-P25): 策略检查 LLM 超时与降级文案。

验收③: 兜底 summary 含超时原因与数据摘要（而非固定「LLM 分析超时」文案）。
"""

import pytest

from app.services.portfolio_service import _build_llm_fail_summary, _llm_timeout_for


class TestLlmFailSummary:
    def test_timeout_reason_with_data_summary(self):
        """超时兜底文案含原因分类 + 数据摘要（N/M 可用）。"""
        s = _build_llm_fail_summary(32.0, "connection timed out", {
            "filled_count": 8, "total_count": 10, "partial": True, "all_empty": False,
        })
        assert "LLM 响应超时" in s
        assert "32s" in s
        assert "8/10" in s
        assert "规则引擎兜底" in s

    def test_rate_limited_reason(self):
        s = _build_llm_fail_summary(5.0, "429 Too Many Requests", None)
        assert "LLM 限流" in s
        assert "429" in s

    def test_all_empty_quality_note(self):
        """数据全缺时文案注明「上下文不足快速兜底」。"""
        s = _build_llm_fail_summary(15.0, "timeout", {
            "filled_count": 0, "total_count": 10, "partial": False, "all_empty": True,
        })
        assert "数据缺失" in s
        assert "0/10" in s


class TestLlmTimeoutGrading:
    def test_graded_timeouts(self):
        """超时按数据完整性分级：all_empty 15s < partial 30s < 完整 60s。"""
        assert _llm_timeout_for({"all_empty": True}) == 15
        assert _llm_timeout_for({"all_empty": False, "partial": True}) == 30
        assert _llm_timeout_for({"all_empty": False, "partial": False}) == 60
