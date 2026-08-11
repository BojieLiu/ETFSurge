"""round15 9-F1: core 层市态绝对防线（docs §10.1 验证 4 条负向断言）。

- 熊市 + 进攻方案 core 层含 科创50（非强制、composite=-2.0）与 510300（强制）：
  1. 科创50 权重 ≤ 1%（修复前按相对排序给 ~10%+）
  2. 510300 权重不变（强制标的豁免）
  3. Σcore + Σdefense 与执行前一致（释放额全部回流，无权重丢失）
  4. 市态=neutral 时函数为 no-op（不触发）
"""
import pytest

from app.engine.risk_controls import (
    RISK_SETTINGS,
    apply_core_bear_growth_trim,
    apply_risk_controls,
)


def _allocs(core_w: float, defense_w: float = 0.2, core_score: float = -2.0):
    return [
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "weight": core_w, "factor_score": core_score, "industry": "宽基指数"},
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "weight": 0.05, "factor_score": 1.0, "industry": "宽基指数"},
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "weight": defense_w, "factor_score": 1.0, "industry": "商品"},
    ]


class TestApplyCoreBearGrowthTrim:
    def test_bear_negative_growth_trimmed_to_min(self):
        """断言 1: bear + 负分成长宽基 → 权重 ≤ min_weight(1%)。"""
        allocs = _allocs(core_w=0.10)
        out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime="bear")
        growth = next(a for a in out if a["symbol"] == "588000")
        assert growth["weight"] <= RISK_SETTINGS.min_weight + 1e-9

    def test_mandatory_anchor_exempt(self):
        """断言 2: 强制标的（510300）权重不变。"""
        allocs = _allocs(core_w=0.10)
        out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime="bear")
        anchor = next(a for a in out if a["symbol"] == "510300")
        assert anchor["weight"] == pytest.approx(0.05)

    def test_weight_conserved_across_layers(self):
        """断言 3: Σcore + Σdefense 守恒（释放额全部回流 defense，无权重丢失）。"""
        allocs = _allocs(core_w=0.10, defense_w=0.20)
        before = sum(a["weight"] for a in allocs)
        out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime="bear")
        after = sum(a["weight"] for a in out)
        assert after == pytest.approx(before, abs=1e-6)

    def test_neutral_regime_noop(self):
        """断言 4: neutral 市态 → 函数 no-op（不触发）。"""
        allocs = _allocs(core_w=0.10)
        out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime="neutral")
        assert out == allocs

    def test_positive_score_growth_not_trimmed(self):
        """正分成长宽基不 trim（市态绝对防线只压负分）。"""
        allocs = _allocs(core_w=0.10, core_score=2.0)
        out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime="bear")
        growth = next(a for a in out if a["symbol"] == "588000")
        assert growth["weight"] == pytest.approx(0.10)

    def test_correction_and_panic_also_trigger(self):
        for regime in ("correction", "panic"):
            allocs = _allocs(core_w=0.10)
            out = apply_core_bear_growth_trim(allocs, {"core": 0.5, "defense": 0.2}, regime=regime)
            growth = next(a for a in out if a["symbol"] == "588000")
            assert growth["weight"] <= RISK_SETTINGS.min_weight + 1e-9, regime


def _factor_matrix():
    """供管线测试：含 price/return 数据（remove_stale_candidates freshness 检查用）。"""
    return {
        "588000": {"price": 1.0, "etf.price": 1.0, "etf.return_1m": 0.01, "technical": -2.0},
        "510300": {"price": 3.8, "etf.price": 3.8, "etf.return_1m": 0.02, "technical": 1.0},
        "518880": {"price": 6.5, "etf.price": 6.5, "etf.return_1m": 0.01, "technical": 1.0},
    }


class TestApplyRiskControlsPipeline:
    def test_pipeline_invokes_trim_before_layer_budget(self):
        """管线集成：apply_risk_controls(regime='bear') 触发 9-F1。"""
        strategies = [{
            "allocations": _allocs(core_w=0.10, defense_w=0.30),
            "layer_budget": {"core": 0.5, "defense": 0.20},
        }]
        out = apply_risk_controls(strategies, _factor_matrix(), regime="bear")
        allocs = out[0]["allocations"]
        growth = next(a for a in allocs if a["symbol"] == "588000")
        assert growth["weight"] <= RISK_SETTINGS.min_weight + 1e-9
        # 层预算校验仍生效：defense 吸收释放额后压回 budget(0.20)
        defense_sum = sum(a["weight"] for a in allocs if a["layer"] == "defense")
        assert defense_sum <= 0.20 + 1e-9

    def test_pipeline_default_regime_neutral_noop(self):
        strategies = [{"allocations": _allocs(core_w=0.10)}]
        out = apply_risk_controls(strategies, _factor_matrix())  # 默认 regime='neutral'
        growth = next(a for a in out[0]["allocations"] if a["symbol"] == "588000")
        assert growth["weight"] == pytest.approx(0.10)
