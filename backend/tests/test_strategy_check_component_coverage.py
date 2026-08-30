# -*- coding: utf-8 -*-
"""round30 R87: 策略检查口径统一为「分项覆盖率」（R74 四值并存修复）。

已决策（§14.1，2026-08-19）：统一为 technical/valuation/momentum 三分项覆盖率。
 ① summary「因子填充率」→ 组合级分项覆盖 = Σ持仓分项有值数/(持仓数×3)；
 ② factor_availability → 每持仓分项覆盖（如 1/3）；
 ③ composite.reason「分项覆盖 X%」保持，三处同底；
 ④ report_text 不再出现「N/N 无兜底」持仓级口径。

无网络：纯函数断言。
"""
import pytest


def _fb(tech_score=1.0, tech_ok=True, valuation=0.0, momentum=0.0,
        tech_factor=None):
    """构造 factor_breakdown 项。"""
    fs = {}
    if tech_factor is not None:
        fs["technical.rsi.rsi_14"] = tech_factor
    if valuation != 0:
        fs["valuation.pe"] = valuation
    if momentum != 0:
        fs["momentum.recent_return"] = momentum
    return {
        "factor_scores": fs,
        "technical_signal": {"score": tech_score, "signal": "buy"} if tech_ok else {"signal": "hold"},
    }


class TestComponentCoverageStatsR87:
    def test_aggregate_coverage(self):
        """组合级分项覆盖 = Σ持仓分项有值数/(持仓数×3)。"""
        from app.services.portfolio.strategy_check import _component_coverage_stats
        fbs = {
            "A": _fb(tech_score=1.0, valuation=0.1, momentum=0.1),  # 3/3
            "B": _fb(tech_score=0.5, valuation=0.0, momentum=0.0),  # 1/3
            "C": _fb(tech_score=None, tech_ok=False),               # 0/3
        }
        stats = _component_coverage_stats(fbs)
        assert stats["agg_filled"] == 4
        assert stats["agg_total"] == 9
        assert stats["coverage_pct"] == pytest.approx(round(4 * 100.0 / 9, 1))
        assert stats["per_holding"]["A"]["ratio"] == "3/3"
        assert stats["per_holding"]["B"]["ratio"] == "1/3"
        assert stats["per_holding"]["C"]["ratio"] == "0/3"

    def test_per_holding_components(self):
        """每持仓分项标注具体缺哪个分项（技术✓/估值✗/动量✗）。"""
        from app.services.portfolio.strategy_check import _component_coverage_stats
        fbs = {"B": _fb(tech_score=0.5, valuation=0.0, momentum=0.0)}
        ph = _component_coverage_stats(fbs)["per_holding"]["B"]
        assert ph["components"] == {"technical": True, "valuation": False, "momentum": False}
        assert ph["filled"] == 1
        assert ph["total"] == 3

    def test_empty_breakdowns(self):
        """空 breakdowns → 0/0，不崩溃。"""
        from app.services.portfolio.strategy_check import _component_coverage_stats
        stats = _component_coverage_stats({})
        assert stats["agg_total"] == 0
        assert stats["coverage_pct"] == 0.0


class TestQualitySummaryR87:
    def test_summary_uses_coverage_not_key_fill(self):
        """摘要用「因子覆盖 X%」（组合级分项覆盖），不再用键级「因子填充率」。"""
        from app.services.portfolio.strategy_check import _quality_summary_text
        from app.services.portfolio.strategy_check import _component_coverage_stats
        # 两持仓各 1/3 → 组合覆盖 2/6=33.3%
        stats = _component_coverage_stats({"A": _fb(tech_score=0.5), "B": _fb(tech_score=0.5)})
        text = _quality_summary_text(stats)
        assert "因子覆盖" in text
        assert "33.3%" in text

    def test_summary_no_fill_rate_wording(self):
        """负向：不得再出现键级「因子填充率」与分项覆盖并存。"""
        from app.services.portfolio.strategy_check import _quality_summary_text
        from app.services.portfolio.strategy_check import _component_coverage_stats
        stats = _component_coverage_stats({"A": _fb(tech_score=0.5, valuation=0.1)})
        text = _quality_summary_text(stats)
        assert "因子填充率" not in text


class TestCompositeConsistencyR87:
    def test_composite_reason_matches_coverage(self):
        """composite.reason 的「分项覆盖 X%」与聚合覆盖同底。"""
        from app.services.portfolio.strategy_check import (
            _component_coverage_stats, _attach_composite_decisions,
        )
        fbs = {"B": _fb(tech_score=0.5, valuation=0.0, momentum=0.0)}
        _attach_composite_decisions(fbs)
        cd = fbs["B"]["composite_decision"]
        assert cd["degraded"] is True
        assert "33.3" in cd["reason"]  # 1/3 分项覆盖
        # 三处同底：coverage_pct == composite valid_rate
        stats = _component_coverage_stats(fbs)
        assert stats["coverage_pct"] == pytest.approx(33.3)


class TestReportTextR87:
    def test_report_text_no_n_over_n(self):
        """负向：report_text 不得再出现「N/N 无兜底」持仓级口径。"""
        from app.services.portfolio.strategy_check import _rule_fallback_quality_line
        from app.services.portfolio.strategy_check import _component_coverage_stats
        stats = _component_coverage_stats({"A": _fb(tech_score=0.5), "B": _fb(tech_score=0.5)})
        line = _rule_fallback_quality_line(stats, fallback_count=0)
        assert "无兜底" not in line
        assert "覆盖" in line
