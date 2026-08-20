# -*- coding: utf-8 -*-
"""round32 R99 (guard S1): momentum 聚合剔除静态政策因子 + 缺数据显式 None。

问题（round32 §4.1 实证）：`CATEGORY_PREFIXES["momentum"]` 误含 `china.policy.*`
（五年规划/战略新兴/双循环，静态政策契合度）。盘后 etf.return_1m/3m/change_pct 全部
no_data 时，静态政策因子 `china.policy.five_year_plan=0.3` 独占 momentum 聚合 →
设计 697 的 factor_breakdown `momentum=0.300` 18/18 全同占位污染（R85 在 partial
降级态回归）。

修复（A+B 双保险）：
- A: momentum 聚合仅保留 `etf.return_*`/`etf.change_pct`/`technical.signal.*`；
- B: 源因子全 no_data 时 momentum 键不设置（消费方 `factor_scores.get("momentum")`
  得 None → rationale 不再引用「动量因子 +0.300」）。

纯函数断言（aggregate_factor_scores 无 I/O）。含负向：静态因子不得再进 momentum。
"""
import pytest

from app.core.factor_aggregate import aggregate_factor_scores


class TestR99MomentumExcludesPolicyFactor:
    def test_policy_factor_not_in_momentum_when_momentum_sources_present(self):
        """etf.return_* 与 china.policy.* 并存 → momentum 只聚合 etf.return_*。"""
        raw = {
            "etf.return_1m": 0.4,
            "etf.return_3m": 0.6,
            "china.policy.five_year_plan": 0.3,
        }
        result = aggregate_factor_scores(raw)
        # R99 负向：china.policy 不得再进 momentum 聚合
        assert "momentum" in result
        assert abs(result["momentum"] - 0.5) < 0.001, (
            f"momentum 应为 etf.return_* 均值 0.5（不含 china.policy），实际 {result['momentum']}"
        )
        # 原始键保留（政策因子仍是独立维度，仅不进 momentum 聚合）
        assert "china.policy.five_year_plan" in result

    def test_momentum_absent_when_only_policy_factor_present(self):
        """负向：仅 china.policy.*（动量源全 no_data）→ momentum 键不设置（非 0.300 占位）。"""
        raw = {"china.policy.five_year_plan": 0.3, "technical.signal.overall": 0.0}
        result = aggregate_factor_scores(raw)
        # technical.signal.overall=0.0 被 |val|>0.001 过滤；china.policy 已剔除 →
        # momentum 无任何匹配源 → 键不设置
        assert "momentum" not in result, (
            f"动量源全缺失时不得设置 momentum 占位键，实际 {result.get('momentum')!r}"
        )
        assert "china.policy.five_year_plan" in result

    def test_momentum_zero_signal_also_absent(self):
        """momentum 源全为 0.0（technical.signal）→ 同样不设 momentum（防 0 占位）。"""
        raw = {"technical.signal.overall": 0.0, "technical.signal.bias": 0.0}
        result = aggregate_factor_scores(raw)
        assert "momentum" not in result

    def test_momentum_aggregates_technical_signal(self):
        """technical.signal.* 仍属 momentum 源（R99 仅剔 china.policy.*，不动其它前缀）。"""
        raw = {"technical.signal.overall": 0.8, "technical.signal.bias": -0.2}
        result = aggregate_factor_scores(raw)
        assert "momentum" in result
        assert abs(result["momentum"] - 0.3) < 0.001, (
            f"momentum 应为 technical.signal 均值 0.3，实际 {result['momentum']}"
        )

    def test_policy_factor_alone_no_momentum_no_technical(self):
        """纯静态政策因子（无任何技术/动量源）→ 无 momentum、无 technical 键。"""
        raw = {"china.policy.five_year_plan": 0.3, "china.policy.strategic_emerging": 0.5}
        result = aggregate_factor_scores(raw)
        assert "momentum" not in result
        assert "technical" not in result
        assert result["china.policy.five_year_plan"] == 0.3

    def test_ic_weighted_momentum_still_works_with_definitions(self):
        """剔除政策因子后 IC 加权路径不回归——definitions/ic_series 注入仍正常。"""
        raw = {"etf.return_1m": 0.4, "etf.change_pct": 0.2}
        ic = {"etf.return_1m": [0.05] * 10, "etf.change_pct": [0.03] * 10}
        result = aggregate_factor_scores(raw, definitions={}, ic_series=ic)
        assert "momentum" in result
        assert 0.0 < abs(result["momentum"]) < 1.0


class TestR99ConsumerContract:
    def test_rationale_omits_momentum_when_missing(self):
        """消费方契约：momentum 缺失（None）时 rationale 不引用「动量因子 +0.300」。"""
        from app.engine.rationale import build_rationale

        # 模拟设计 697 partial 态：momentum 键缺失（R99 修复后），其余因子键存在
        factor_scores = {"technical": 0.2, "valuation": 0.1, "sentiment": -0.05}
        rationale = build_rationale(
            code="512890",
            layer="core",
            strategy="balanced",
            factor_scores=factor_scores,
            regime="range_bound",
        )
        assert "动量因子 +0.300" not in rationale, "缺失动量不得引用占位值"
        assert "动量因子" not in rationale or "不可用" in rationale
