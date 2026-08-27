# -*- coding: utf-8 -*-
"""round38 R141: 策略检查报告表格「因子分」列在 composite_score 缺失/为 0 时
回退读 factor_scores 非零均值——修复 round37 R132 未完全生效的残留路径。

根因（round38 §4）：dcd47e0 只在 holdings_analysis 注入 factor_scores 键，
`_build_rule_fallback_report` 表格行（strategy_check.py:1394-1395）仍读
`s.get("composite_score")`；规则兜底路径 factor_composite=None → avg_factor=0.0
→ 表格「因子分」列恒 0.00，与 reason 引用真实因子脱节（round38 实测
strategy_check_records 3 条报告全 0.00）。

修复：表格行 composite_score 缺失或为 0 时，回退读 factor_breakdowns 中
factor_scores 的非零均值（与 _rule_based_suggestion 的 avg_factor 同口径）。

无网络：纯函数断言。
"""

from app.services.portfolio.strategy_check import _build_rule_fallback_report


def _build_report(suggestions, breakdowns):
    return _build_rule_fallback_report(
        market_data=[],
        factor_breakdowns=breakdowns,
        merged_suggestions=suggestions,
        regime="range_bound",
        data_quality={},
        llm_failed=True,
        risk_warnings=[],
    )


def _table_rows(report_text):
    """提取逐标的表数据行：[(代码, 表格因子分单元格, 整行文本)]。"""
    rows = []
    for line in report_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 7 or cells[1] in ("代码", "") or set(cells[1]) <= {"-", ":"}:
            continue
        if cells[3].replace("-", "").replace(".", "").isdigit():
            rows.append((cells[1], cells[3], line))
    return rows


class TestR141TableScoreFallback:
    def test_table_falls_back_to_factor_scores_when_composite_missing(self):
        """composite_score 缺失时表格列回退读 factor_scores 非零均值。"""
        s = {
            "symbol": "512890", "name": "红利低波ETF",
            "action": "hold", "current_weight": 0.10, "suggested_weight": 0.10,
            "reason": "测试理由", "confidence": "medium", "source": "rule",
            # 无 composite_score 键（规则兜底路径）
        }
        breakdowns = {
            "512890": {
                "factor_scores": {"technical": 0.8, "momentum": 0.6,
                                  "valuation": 0.0, "sentiment": 0.0},
                "technical_signal": {"signal": "hold"},
            },
        }
        report = _build_report([s], breakdowns)
        rows = _table_rows(report)
        assert rows, "报告应包含逐标的表数据行"
        sym, cell, line = rows[0]
        assert sym == "512890"
        # (0.8+0.6)/2 = 0.70 —— 非零均值，不得再显示 0.00
        assert cell == "0.70", f"表格列应为回退均值 0.70，实际 {cell}"

    def test_table_falls_back_when_composite_is_zero(self):
        """composite_score 显式为 0.0 时同样回退（不显示误导性 0.00）。"""
        s = {
            "symbol": "159338", "name": "中证A500ETF",
            "action": "decrease", "current_weight": 0.20, "suggested_weight": 0.15,
            "reason": "测试理由", "confidence": "high", "source": "rule",
            "composite_score": 0.0,
        }
        breakdowns = {
            "159338": {
                "factor_scores": {"technical": -0.4, "momentum": -0.2,
                                  "valuation": 0.0, "sentiment": 0.0},
                "technical_signal": {"signal": "sell"},
            },
        }
        report = _build_report([s], breakdowns)
        rows = _table_rows(report)
        assert rows, "报告应包含逐标的表数据行"
        sym, cell, line = rows[0]
        assert sym == "159338"
        # (-0.4 + -0.2)/2 = -0.30
        assert cell == "-0.30", f"表格列应为回退均值 -0.30，实际 {cell}"

    def test_stays_zero_when_no_factor_scores(self):
        """factor_scores 全空时回退无值可算，保持 0.00（诚实降级，不硬编）。"""
        s = {
            "symbol": "510300", "name": "沪深300ETF",
            "action": "hold", "current_weight": 0.10, "suggested_weight": 0.10,
            "reason": "测试理由", "confidence": "low", "source": "rule",
        }
        breakdowns = {
            "510300": {
                "factor_scores": {},
                "technical_signal": {"signal": "hold"},
            },
        }
        report = _build_report([s], breakdowns)
        rows = _table_rows(report)
        assert rows, "报告应包含逐标的表数据行"
        sym, cell, line = rows[0]
        assert sym == "510300"
        assert cell == "0.00", f"无因子分时保持 0.00（诚实降级），实际 {cell}"
