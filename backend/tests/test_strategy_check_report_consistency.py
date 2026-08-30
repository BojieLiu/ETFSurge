# -*- coding: utf-8 -*-
"""round31 R95: 报告正文数值一致性校验（纯函数断言）。

根因（§4.3）：报告正文（LLM/rule 文本层）与结构化层数值源不一致——512890 KDJ J
正文 6.16 vs 结构化 84.49；518880 SMA 3.07/13.06 vs 实测 9.02/8.99；量比 -9.86
负值异常；record 793「港股相关资产合计权重 10%」vs holdings_json 结构化权重和 13%。

修复（方案 A）：`_reconcile_report_numbers` 文本生成后逐持仓比对 KDJ/RSI/SMA/量比
vs technical_indicators 结构化值，不一致用结构化值覆盖 + WARNING（仿
_validate_report_consistency 修正脚注模式）；「合计权重 N%」聚合表述与 weight_map
结构化权重和一致性校验。

无网络：纯函数断言（构造确定输入 → 断言校正输出）。
"""
import pytest


def _fb(kdj_j=84.49, kdj_k=70.0, kdj_d=65.0, rsi=56.7, ma5=9.02, ma10=8.99):
    return {
        "technical_indicators": {
            "kdj": {"k": kdj_k, "d": kdj_d, "j": kdj_j},
            "rsi": rsi, "ma5": ma5, "ma10": ma10,
        },
        "factor_scores": {"technical.rsi.rsi_14": rsi},
    }


def _reconcile(text, fbs=None, weights=None):
    from app.services.portfolio.strategy_check import _reconcile_report_numbers
    return _reconcile_report_numbers(text, fbs, weights)


class TestIndicatorReconciliation:
    def test_kdj_j_corrected(self):
        """KDJ J 正文 6.16 vs 结构化 84.49 → 覆盖为 84.49（R95 ①④）。"""
        out, warns = _reconcile("512890 KDJ J=6.16超买", {"512890": _fb()})
        assert "KDJ J=84.49" in out
        assert "6.16" not in out
        assert any("KDJ J" in w for w in warns)

    def test_kdj_k_d_corrected(self):
        """KDJ K/D 同样校正。"""
        out, warns = _reconcile("512890 KDJ K=10.0, KDJ D=20.0 金叉",
                                {"512890": _fb(kdj_k=70.0, kdj_d=65.0)})
        assert "KDJ K=70.00" in out
        assert "KDJ D=65.00" in out
        assert len(warns) == 2

    def test_rsi_corrected(self):
        """RSI 正文 42.0 vs 结构化 56.7 → 覆盖。"""
        out, warns = _reconcile("159338 RSI=42.0 中性", {"159338": _fb(rsi=56.7)})
        assert "RSI=56.70" in out
        assert "42.0" not in out
        assert any("RSI" in w for w in warns)

    def test_sma_pair_corrected(self):
        """SMA5/10 正文 3.07/13.06 vs 实测 9.02/8.99 → 覆盖（R95 ③）。"""
        out, warns = _reconcile("518880 价格站上 SMA5/10(3.07/13.06)",
                                {"518880": _fb(ma5=9.02, ma10=8.99)})
        assert "SMA5/10(9.02/8.99)" in out
        assert "3.07" not in out and "13.06" not in out
        assert any("SMA" in w for w in warns)

    def test_matching_values_untouched(self):
        """正文与结构化一致 → 不改动、无 warning（无假修正）。"""
        out, warns = _reconcile("512890 KDJ J=84.49超买；RSI=56.70 中性",
                                {"512890": _fb()})
        assert out == "512890 KDJ J=84.49超买；RSI=56.70 中性"
        assert warns == []

    def test_single_sma5_corrected(self):
        """单独 SMA5/10 冒号形式。"""
        out, warns = _reconcile("518880 SMA5:3.07 SMA10:13.06",
                                {"518880": _fb(ma5=9.02, ma10=8.99)})
        assert "SMA5:9.02" in out and "SMA10:8.99" in out


class TestVolRatioReconciliation:
    def test_negative_vol_ratio_flagged(self):
        """量比负值（真实量比应≥0，负值是 z-score 冒充）→ 标数据待核（R95 ②）。"""
        out, warns = _reconcile("159545 量比-9.86 资金流出", {"159545": _fb()})
        assert "-9.86" not in out
        assert "数据待核" in out
        assert any("量比" in w for w in warns)

    def test_positive_vol_ratio_kept(self):
        """量比非负 → 保留（无原始值可比对，不误改）。"""
        out, warns = _reconcile("159545 量比1.25 放量", {"159545": _fb()})
        assert "量比1.25" in out
        assert warns == []


class TestAggregateWeightReconciliation:
    WEIGHTS = {"159545": 0.05, "513120": 0.05, "513010": 0.03}

    def test_hk_aggregate_weight_corrected(self):
        """港股类合计权重 10% vs 结构化权重和 13% → 覆盖（R95 ⑤）。"""
        text = "港股相关资产（159545、513120、513010）合计权重10%"
        out, warns = _reconcile(text, weights=self.WEIGHTS)
        assert "合计权重13%" in out
        assert "10%" not in out.replace("合计权重13%", "")
        assert any("合计权重" in w for w in warns)

    def test_correct_aggregate_untouched(self):
        """合计权重与权重和一致 → 不改动。"""
        text = "港股相关资产（159545、513120、513010）合计权重13%"
        out, warns = _reconcile(text, weights=self.WEIGHTS)
        assert "合计权重13%" in out
        assert warns == []

    def test_aggregate_without_symbols_untouched(self):
        """上下文无 symbol（无法校验）→ 不误改。"""
        text = "各行业合计权重受预算约束，单只不超过30%"
        out, warns = _reconcile(text, weights=self.WEIGHTS)
        assert "30%" in out
        assert warns == []


class TestEdgeCases:
    def test_empty_text(self):
        out, warns = _reconcile("", {"512890": _fb()})
        assert out == ""
        assert warns == []

    def test_no_breakdowns(self):
        out, warns = _reconcile("512890 KDJ J=6.16超买", {})
        assert "6.16" in out  # 无结构化值可比 → 保留原文（诚实）
        assert warns == []

    def test_warnings_footnote(self):
        """warnings 非空 → 调用方应追加脚注（本函数只返回，不注入）。"""
        out, warns = _reconcile("512890 KDJ J=6.16超买", {"512890": _fb()})
        assert warns, "应有修正 warning"
