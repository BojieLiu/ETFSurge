"""round25 R27: 因子分两路径口径统一——截面 z-score 复合分。

问题（round25 §2.2 实证）：同一标的 159338 在组合设计路径 composite z-score = -0.958
（深负），在策略检查路径「因子分 1.68（偏强）」——两屏方向相反。根因：策略检查
`_rule_based_suggestion` 用原始因子值均值（avg_factor），被 KDJ≈77 等量纲大的技术因子
主导；设计用截面 z-score。

修复（round25 R27）：
- `_cross_sectional_factor_composite`：对每个因子键在组合内所有持仓上 z-score 归一，
  再按持仓平均 → 与设计同量纲的复合分；
- `_rule_based_suggestion` 新增 `factor_composite` 参数，传入时优先使用（回落原始均值）。
"""

import pytest

from app.services.portfolio_service import (
    _cross_sectional_factor_composite,
    _rule_based_suggestion,
)


class TestCrossSectionalFactorComposite:
    """R27: 截面 z-score 复合分（跨持仓可比口径）。"""

    def test_kdj_dominated_symbol_gets_negative_composite(self):
        """KDJ≈77（量纲大）的标的不得再得正分——z-score 归一后与截面相对位置一致。"""
        fbs = {
            "510300": {
                "factor_scores": {
                    "technical.rsi.rsi_14": 58.0,
                    "technical.kdj.k": 55.0,
                    "momentum.recent_return": 0.05,
                },
            },
            "159338": {
                "factor_scores": {
                    "technical.rsi.rsi_14": 42.0,
                    "technical.kdj.k": 77.0,
                    "momentum.recent_return": 0.03,
                },
            },
            "511090": {
                "factor_scores": {
                    "technical.rsi.rsi_14": 35.0,
                    "technical.kdj.k": 30.0,
                    "momentum.recent_return": 0.01,
                },
            },
        }
        comps = _cross_sectional_factor_composite(fbs)
        assert "510300" in comps and "159338" in comps and "511090" in comps
        # 159338 KDJ 最高（77）但 RSI/动量均偏低 → 复合分应显著低于 510300
        assert comps["159338"] < comps["510300"], (
            f"159338 复合分 {comps['159338']} 应 < 510300 {comps['510300']}"
        )
        # 511090（全低）复合分应为负或最低
        assert comps["511090"] <= comps["159338"]

    def test_single_symbol_returns_empty(self):
        """单只持仓无法构成截面 → 返回空 dict（调用方回落原始均值，诚实）。"""
        fbs = {"510300": {"factor_scores": {"technical.rsi.rsi_14": 50.0}}}
        assert _cross_sectional_factor_composite(fbs) == {}

    def test_std_zero_key_skipped(self):
        """某因子全部相同（std=0）→ 不引入噪声（跳过该键）。"""
        fbs = {
            "A": {"factor_scores": {"technical.rsi.rsi_14": 50.0, "x": 0.1}},
            "B": {"factor_scores": {"technical.rsi.rsi_14": 50.0, "x": 0.9}},
        }
        comps = _cross_sectional_factor_composite(fbs)
        # rsi 全 50 → std=0 跳过；只有 x 参与 → 方向明确
        assert comps["A"] < 0 < comps["B"]
        assert abs(comps["A"]) == pytest.approx(abs(comps["B"]), abs=0.01)


class TestRuleBasedSuggestionFactorComposite:
    """R27: _rule_based_suggestion 使用截面复合分（替代原始均值）。"""

    def test_composite_overrides_raw_mean(self):
        """传 factor_composite → 决策用复合分，reason 呈现复合值而非 KDJ 原始均值。"""
        fs = {"technical.kdj.k": 77.0, "momentum.recent_return": 0.03}
        out = _rule_based_suggestion(
            symbol="159338", name="中证A500", target_weight=0.1,
            factor_score=fs, signal={"signal": "sell"},
            regime="range_bound", current_weight=0.1,
            factor_composite=-0.9,
        )
        assert out["action"] in ("decrease", "hold")
        # reason 应含复合分（-0.90），不得出现「77」冒充强度
        assert "-0.90" in out["reason"] or "因子分 -0.9" in out["reason"]
        assert "77" not in out["reason"], "KDJ 原始值不得出现在因子分表述中（R27）"

    def test_negative_composite_with_sell_gives_decrease(self):
        """复合分 < -0.5 + sell → decrease（决策表分档作用于同量纲 z-score）。"""
        out = _rule_based_suggestion(
            symbol="X", name="X", target_weight=0.1,
            factor_score={}, signal={"signal": "sell"},
            regime="range_bound", current_weight=0.1,
            factor_composite=-0.8,
        )
        assert out["action"] == "decrease"

    def test_no_composite_falls_back_to_raw_mean(self):
        """未传 factor_composite 且因子键非真实分类键 → 回落原始均值（向后兼容）。"""
        out = _rule_based_suggestion(
            symbol="X", name="X", target_weight=0.1,
            factor_score={"a": 0.9, "b": 0.5}, signal={"signal": "buy"},
            regime="range_bound", current_weight=0.1,
        )
        # 原始均值 (0.9+0.5)/2 = 0.7 > 0.5 + buy → increase
        assert out["action"] == "increase"

    def test_single_symbol_real_factors_use_within_symbol_composite(self):
        """单标的真实因子（factor_composite=None）→ 用 within-symbol z 复合分，
        不得把异构量纲原始政策因子（+8.97）当 z 强度（R27 单标的场景修复）。"""
        fs = {"china.policy.monetary": 8.97, "technical.rsi": 50.0}
        out = _rule_based_suggestion(
            symbol="159338", name="中证A500", target_weight=0.1,
            factor_score=fs, signal={"signal": "hold"},
            regime="range_bound", current_weight=0.1,
        )
        # 负向断言：异构原始值不得冒充 z 强度出现在因子分描述里
        assert "8.97" not in out["reason"]
        # raw 朴素均值 ≈ (8.97+50)/2 量级极大，z 复合分应远小于此（不被拉正到偏强级）
        assert "29.49" not in out["reason"] and "29.5" not in out["reason"]