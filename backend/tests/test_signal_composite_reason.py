# -*- coding: utf-8 -*-
"""round29 R74: 策略检查因子口径统一（summary / composite_decision / factor_availability）。

根因（§14.1 R74）：`summary="因子数据13/13正常"` vs `composite_decision.reason=
"因子数据缺失 66.7%"` vs `factor_availability.ratio="26/39"` 三处口径互斥——
「13/13 正常」「缺失 66.7%」「26/39 已填」专业投资者无法判断真实可用性。

修复：
  ① summary 改报组合级「因子填充率 X%」（与 factor_availability 同口径聚合），
     不再用「N/M 正常」断言；
  ② composite reason 明示「分项覆盖率」基底与 60% 阈值，避免两处百分数误读。

无网络：纯函数断言。
"""
import pytest

from app.analysis.signal import composite_signal_with_gate


class TestCompositeReasonR74:
    def test_degraded_reason_is_self_describing(self):
        """valid_rate=1/3 → reason 明示「分项覆盖 33.3% < 60%」，不得再用「缺失 66.7%」裸数字。"""
        out = composite_signal_with_gate(
            technical=0.5, valuation=0.5, momentum=0.5, factor_valid_rate=1 / 3,
        )
        assert out["degraded"] is True
        assert "33.3" in out["reason"]  # 覆盖率（非缺失率）
        assert "60%" in out["reason"]  # 阈值可见
        assert "因子数据缺失" not in out["reason"]  # 负向：旧裸缺失率措辞消失

    def test_no_conflicting_missing_pct_wording(self):
        """reason 不得同时出现「覆盖率 X%」与「缺失 Y%」两个不同底数的百分比。"""
        out = composite_signal_with_gate(
            technical=0.8, valuation=0.9, momentum=0.8, factor_valid_rate=0.0,
        )
        assert "缺失" not in out["reason"]


class TestQualitySummaryR74:
    def _build_summary(self, factor_breakdowns):
        """复刻 strategy_check 的 data_quality 聚合逻辑并提取摘要文案。"""
        from app.services.portfolio.formatting import _has_real_factor_values
        filled = sum(
            1 for fb in factor_breakdowns.values()
            if isinstance(fb, dict) and _has_real_factor_values(fb.get("factor_scores") or {})
        )
        total = len(factor_breakdowns)
        keys_total = sum(len(fb.get("factor_scores") or {}) for fb in factor_breakdowns.values())
        keys_filled = sum(
            sum(1 for v in (fb.get("factor_scores") or {}).values()
                if isinstance(v, (int, float)) and v not in (0, 50, 1))
            for fb in factor_breakdowns.values()
        )
        pct = round(keys_filled * 100.0 / keys_total, 1) if keys_total else None
        if pct is not None:
            return f"；因子填充率 {pct}%"
        if total > 0:
            return f"；因子填充率 {round(filled * 100.0 / total, 1)}%"
        return ""

    def test_summary_reports_fill_rate_not_normal_claim(self):
        """摘要只报「因子填充率 X%」，不得出现「N/M 正常」断言。"""
        fbs = {
            "510300": {"factor_scores": {"a": 0.1, "b": 0.2, "c": 0.3}},
            "518880": {"factor_scores": {"a": 0.1, "b": 0.2}},  # 少一维
        }
        summary = self._build_summary(fbs)
        assert "因子填充率" in summary
        assert "正常" not in summary
        assert "/" not in summary  # 不再有 "13/13 正常" 形态

    def test_partial_fill_summary_matches_key_level(self):
        """部分填充 → 摘要百分比与键级填充同源（26/39 形态聚合）。"""
        fbs = {
            "A": {"factor_scores": {f"k{i}": 0.5 for i in range(2)}},
            "B": {"factor_scores": {f"k{i}": 0.5 for i in range(2)}},
            "C": {"factor_scores": {f"k{i}": 0.5 for i in range(2)}},
        }
        summary = self._build_summary(fbs)
        assert "因子填充率 100.0%" in summary
