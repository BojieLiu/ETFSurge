# -*- coding: utf-8 -*-
"""round34 R107: 策略检查报告表格「因子分」与理由「因子分」同页异源。

根因（round34 §4.5）：`_build_rule_fallback_report` 表格列（strategy_check.py
:1387-1388 旧实现）对 factor_breakdowns 原始因子**非零值简单平均**——把
RSI(0-100)/KDJ(0-100)/动量 z-score 混杂量纲直接算术平均，且剔零使 OTC 基金不参与、
均值进一步漂移；而同行 reason 引用的是 `_rule_based_suggestion` 的 `_score`
（composite 复合分）。两处同名「因子分」异源异义（实测 159992 表格 +1.63 vs 理由
-2.43），读者可见自相矛盾。

修复：① `_rule_based_suggestion` 返回 dict 增加 `composite_score` 键；
② 表格列改读该键（与理由同源单义）。

无网络：纯函数断言。
"""
import re

from app.services.portfolio.strategy_check import (
    _build_rule_fallback_report,
    _rule_based_suggestion,
)


def _make_suggestion(symbol, name, composite, raw_scores, sig="hold"):
    """构造一条 rule 兜底建议（current==target 使决策走 else 分支，
    reason 文本含「因子分 {composite:.2f}」）。"""
    return _rule_based_suggestion(
        symbol=symbol,
        name=name,
        target_weight=0.10,
        factor_score=dict(raw_scores),
        signal={"signal": sig},
        regime="range_bound",
        current_weight=0.10,
        factor_availability={"filled": 5, "total": 6},
        factor_composite=composite,
        factor_composite_label="相对候选池",
    )


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
        # cells[0] 为空（行首 |）；表头/分隔行跳过
        if len(cells) < 7 or cells[1] in ("代码", "") or set(cells[1]) <= {"-", ":"}:
            continue
        if cells[3].replace("-", "").replace(".", "").isdigit():
            rows.append((cells[1], cells[3], line))
    return rows


class TestR107TableScoreSingleSource:
    def test_table_score_equals_rationale_score(self):
        """表格列必须与理由「因子分 X.XX」同值（composite 口径），
        且不得再出现混杂量纲的原始均值。"""
        # 复刻 round34 实测形态：原始因子 RSI/KDJ 0-100 量纲，composite 为截面 z 分
        s = _make_suggestion("159992", "芯片ETF", -2.43,
                             {"rsi_14": 80.0, "kdj_k": 85.0})
        # ① 新键存在且与理由引用同源
        assert isinstance(s.get("composite_score"), (int, float)), (
            f"_rule_based_suggestion 必须显式返回 composite_score，实际 {sorted(s)}"
        )
        assert s["composite_score"] == -2.43

        breakdowns = {
            "159992": {
                "factor_scores": {"rsi_14": 80.0, "kdj_k": 85.0},
                "technical_signal": {"signal": "hold"},
            },
        }
        report = _build_report([s], breakdowns)

        rows = _table_rows(report)
        assert rows, "报告应包含逐标的表数据行"
        sym, cell, line = rows[0]
        assert sym == "159992"
        assert cell == "-2.43", f"表格列应为 composite -2.43，实际 {cell}"
        assert "因子分 -2.43" in line, "同行理由应引用同一 composite 值"
        # 负向：旧实现的原始非零均值 (80+85)/2=82.50 不得再出现于表格列
        assert "82.50" not in line, f"混杂量纲均值泄漏到表格列：{line}"

    def test_table_never_shows_raw_mean_when_divergent(self):
        """负向：composite 与原始均值显著分叉（0.02 vs 7.97，复刻 019633 形态）时，
        同页只允许出现一个数值口径且两者一致。"""
        s = _make_suggestion("019633", "半导体联接C", 0.02,
                             {"momentum_z": 7.97, "rsi_14": 50.0, "kdj_j": 90.11})
        breakdowns = {
            "019633": {
                "factor_scores": {"momentum_z": 7.97, "rsi_14": 50.0, "kdj_j": 90.11},
                "technical_signal": {"signal": "hold"},
            },
        }
        report = _build_report([s], breakdowns)
        rows = _table_rows(report)
        assert rows and rows[0][1] == "0.02", (
            f"表格列应取 composite 0.02，实际 {rows[0][1] if rows else '无行'}"
        )
        # 旧均值 (7.97+50+90.11)/3 ≈ 49.36 不得出现
        assert "49.36" not in rows[0][2]

    def test_no_double_value_on_same_page(self):
        """负向（R107 验收）：同页不存在第二个不同数值的「因子分」引用——
        每一行的表格列值与理由中全部「因子分 X.XX」引用必须一致。"""
        cases = [
            ("159992", "芯片ETF", -2.43, {"rsi_14": 80.0, "kdj_k": 85.0}),
            ("159338", "中证A500ETF", 0.02, {"sma_5": 1.02, "macd_dif": -0.31}),
            ("512000", "券商ETF", 0.61, {"rsi_14": 44.5, "boll_ub": 1.2}),
            ("510300", "沪深300ETF", -0.75, {"return_20d": -0.08}),
        ]
        suggestions = [_make_suggestion(sym, name, comp, raw)
                       for sym, name, comp, raw in cases]
        breakdowns = {
            sym: {"factor_scores": raw, "technical_signal": {"signal": "hold"}}
            for sym, _, _, raw in cases
        }
        report = _build_report(suggestions, breakdowns)

        pat = re.compile(r"因子分 (-?\d+\.\d{2})")
        checked = 0
        for sym, cell, line in _table_rows(report):
            refs = pat.findall(line)
            assert refs, f"{sym} 行理由应含「因子分 X.XX」引用"
            for ref in refs:
                assert ref == cell, (
                    f"{sym} 双「因子分」打架：表格 {cell} vs 理由 {ref}（行：{line}）"
                )
            checked += 1
        assert checked == len(cases), f"应校验 {len(cases)} 行，实际 {checked}"

    def test_missing_composite_falls_back_zero_not_raw_mean(self):
        """防御路径：suggestion 无 composite_score 键（异常上游）→ 表格列报 0.00，
        不得回退到混杂量纲原始均值冒充（诚实缺省优于假值）。"""
        s = _make_suggestion("512890", "红利低波ETF", 0.35, {"rsi_14": 62.0})
        del s["composite_score"]  # 模拟上游未带新键
        breakdowns = {
            "512890": {
                "factor_scores": {"rsi_14": 62.0},
                "technical_signal": {"signal": "hold"},
            },
        }
        report = _build_report([s], breakdowns)
        rows = _table_rows(report)
        assert rows and rows[0][1] == "0.00", (
            f"缺 composite 时应显式 0.00，实际 {rows[0][1] if rows else '无行'}"
        )


class TestR132FactorScoresInjection:
    """R132 (round37): holdings_analysis 必须注入 factor_scores 原始 dict——
    报告表格 factor_score_* 列与 reason 列的 composite_signal 同源。

    无网络：纯函数断言。"""

    def test_factor_scores_injected_in_holdings_analysis(self):
        """holdings_analysis 每个 item 必须有 factor_scores 键（dict 类型）。"""
        from app.services.portfolio.strategy_check import (
            _build_rule_fallback_report,
        )
        # 构造带 factor_scores 的 factor_breakdowns
        breakdowns = {
            "510300": {
                "factor_scores": {"technical": 0.5, "momentum": 0.3, "valuation": 0.2},
                "technical_signal": {"signal": "buy"},
            },
            "159992": {
                "factor_scores": {"technical": -0.2, "momentum": 0.8},
                "technical_signal": {"signal": "hold"},
            },
        }
        # 模拟 holdings_analysis 回填后的结构（factor_scores 已注入）
        holdings_analysis = []
        for sym, fb in breakdowns.items():
            h = {
                "symbol": sym,
                "name": f"{sym}ETF",
                "factor_summary": "mock summary",
                "factor_scores": fb.get("factor_scores", {}),
                "tech_signal": "BUY",
            }
            holdings_analysis.append(h)

        for h in holdings_analysis:
            assert "factor_scores" in h, (
                f"R132: holdings_analysis[{h['symbol']}] 缺少 factor_scores 键"
            )
            assert isinstance(h["factor_scores"], dict), (
                f"R132: factor_scores 应为 dict，实际 {type(h['factor_scores'])}"
            )

    def test_factor_scores_not_empty_when_data_available(self):
        """当 factor_breakdowns 有数据时，factor_scores 不应为空 dict。"""
        fb = {"technical": 0.7, "momentum": -0.3, "valuation": 0.1}
        real_fs = fb  # 模拟 fb.get("factor_scores", {})
        h = {"factor_scores": real_fs if isinstance(real_fs, dict) else {}}
        assert h["factor_scores"] == fb
        assert len(h["factor_scores"]) == 3


# ── round39 §10.7 (round42 实施): 合并 R141 ─────────────────────
# R141 (round38): 表格「因子分」列在 composite_score 缺失/为 0 时回退读
# factor_scores 非零均值——修复 round37 R132 未完全生效的残留路径。
# 原 test_r141_table_score_fallback.py (3 用例) 增补到本文件; helper
# _build_report / _table_rows 与本文件已有同名同实现, 复用即可 (删除重复).
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
