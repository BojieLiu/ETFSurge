"""
TDD: risk_controls.py — pure function risk control tests.

Covers P1-4 regression, drawdown, defense, stale, minnows, apply_risk_controls pipeline.
All tests are I/O-free, pure logic verification.
"""
from __future__ import annotations
from typing import Any
import pytest
from app.engine.risk_controls import (
    RISK_SETTINGS,
    _consolidate_minnows,
    apply_risk_controls,
    check_defense_effectiveness,
    filter_extreme_drawdown,
    remove_stale_candidates,
)

def _strategy(allocations=None, profile='aggressive', layer_budget=None):
    return {'profile': profile, 'allocations': allocations or [], 'layer_budget': layer_budget or {'core': 0.5, 'satellite': 0.25, 'defense': 0.15}}

def _etf(symbol, weight=0.1, layer='core', rationale='base', price=10.0, return_1m=0.02, return_3m=0.05):
    return {'symbol': symbol, 'weight': weight, 'layer': layer, 'selection_rationale': rationale, 'price': price, 'return_1m': return_1m, 'return_3m': return_3m}


class TestP14Regression:
    """P1-4 regression: rationale string not corrupted by operator precedence."""

    def test_rationale_not_corrupted_when_ret_is_none(self):
        etfs = [_etf('510300', rationale='good', return_1m=None)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'510300': {'return_1m': None}})
        assert result[0]['allocations'][0]['selection_rationale'] == 'good'

    def test_rationale_contains_note_when_ret_is_bad(self):
        etfs = [_etf('510300', rationale='good', return_1m=-0.25)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'510300': {'return_1m': -0.25}})
        assert '风控' in result[0]['allocations'][0]['selection_rationale']

    def test_rationale_string_not_swallowed_by_ternary(self):
        etfs = [_etf('159338', rationale='original text', return_1m=-0.25)]
        result = filter_extreme_drawdown([_strategy([etfs[0]])], {'159338': {'return_1m': -0.25}})
        assert 'original' in result[0]['allocations'][0]['selection_rationale']


class TestDrawdown:
    """filter_extreme_drawdown: bad ETFs removed, weight redistributed."""

    def test_removes_bad_etf(self):
        etfs = [_etf('510300', weight=0.3, return_1m=-0.50), _etf('518880', weight=0.2, return_1m=0.01)]
        fm = {'510300': {'return_1m': -0.50}, '518880': {'return_1m': 0.01}}
        result = filter_extreme_drawdown([_strategy(etfs)], fm)
        symbols = {a['symbol'] for a in result[0]['allocations']}
        assert '510300' not in symbols
        assert '518880' in symbols

    def test_redistributes_weight_to_survivors(self):
        etfs = [_etf('510300', weight=0.3, return_1m=-0.50), _etf('518880', weight=0.2, return_1m=0.01)]
        fm = {'510300': {'return_1m': -0.50}, '518880': {'return_1m': 0.01}}
        result = filter_extreme_drawdown([_strategy(etfs)], fm)
        survivor = [a for a in result[0]['allocations'] if a['symbol'] == '518880'][0]
        assert survivor['weight'] > 0.2

    def test_preserves_cash(self):
        etfs = [{'symbol': 'CASH', 'weight': 0.1, 'layer': 'satellite'}, _etf('510300', weight=0.2, return_1m=-0.50)]
        result = filter_extreme_drawdown([_strategy(etfs)], {'510300': {'return_1m': -0.50}})
        assert any(a['symbol'] == 'CASH' for a in result[0]['allocations'])


class TestDefenseEffectiveness:
    """check_defense_effectiveness: defense ETFs with bad 3m return get weight halved."""

    def test_reduces_weight_when_bad(self):
        etfs = [_etf('518880', weight=0.1, layer='defense', return_3m=-0.15)]
        result = check_defense_effectiveness([_strategy(etfs)], {'518880': {'return_3m': -0.15}})
        assert result[0]['allocations'][0]['weight'] < 0.08

    def test_ignores_non_defense(self):
        etfs = [_etf('510300', weight=0.1, layer='core', return_3m=-0.20)]
        result = check_defense_effectiveness([_strategy(etfs)], {'510300': {'return_3m': -0.20}})
        assert result[0]['allocations'][0]['weight'] == 0.1


class TestStaleCandidates:
    """remove_stale_candidates: ETFs without price/return data are removed."""

    def test_removes_etf_without_data(self):
        etfs = [_etf('510300', weight=0.1, price=None, return_1m=None), _etf('518880', weight=0.1, price=10.0, return_1m=0.01)]
        fm = {'510300': {}, '518880': {'price': 10.0, 'return_1m': 0.01}}
        result = remove_stale_candidates([_strategy(etfs)], fm)
        assert '510300' not in {a['symbol'] for a in result[0]['allocations']}

    def test_preserves_cash(self):
        etfs = [{'symbol': 'CASH', 'weight': 0.1}, _etf('510300', weight=0.2, price=None, return_1m=None)]
        result = remove_stale_candidates([_strategy(etfs)], {})
        assert any(a['symbol'] == 'CASH' for a in result[0]['allocations'])


class TestConsolidateMinnows:
    """_consolidate_minnows: small defense positions merged into largest one."""

    def test_merges_small_defense(self):
        etfs = [_etf('518880', weight=0.01, layer='defense'), _etf('511090', weight=0.08, layer='defense')]
        result = _consolidate_minnows([_strategy(etfs)])
        assert len(result[0]['allocations']) == 1

    def test_does_not_merge_when_above_minimum(self):
        etfs = [_etf('518880', weight=0.05, layer='defense'), _etf('511090', weight=0.08, layer='defense')]
        result = _consolidate_minnows([_strategy(etfs)])
        assert len(result[0]['allocations']) == 2


class TestApplyRiskControls:
    """Full pipeline integration."""

    def test_pipeline_does_not_crash(self):
        fm = {'510300': {'return_1m': 0.02, 'return_3m': 0.05, 'price': 10.0}}
        result = apply_risk_controls([_strategy([_etf('510300', weight=0.3)])], fm)
        assert len(result) == 1

    def test_single_weight_not_exceed_max(self):
        fm = {'510300': {'return_1m': 0.02, 'return_3m': 0.05, 'price': 10.0}}
        result = apply_risk_controls([_strategy([_etf('510300', weight=0.5)], layer_budget={'core': 0.5})], fm)
        for a in result[0]['allocations']:
            if a.get('symbol') != 'CASH':
                assert a['weight'] <= RISK_SETTINGS.max_single_weight + 0.001


# ===== folded from test_round15_bear_growth_trim.py =====
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
def _factor_matrix():
    """供管线测试：含 price/return 数据（remove_stale_candidates freshness 检查用）。"""
    return {
        "588000": {"price": 1.0, "etf.price": 1.0, "etf.return_1m": 0.01, "technical": -2.0},
        "510300": {"price": 3.8, "etf.price": 3.8, "etf.return_1m": 0.02, "technical": 1.0},
        "518880": {"price": 6.5, "etf.price": 6.5, "etf.return_1m": 0.01, "technical": 1.0},
    }
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


# ===== folded from test_round20_engine_fixes.py =====
from app.engine.allocation_engine import (
    allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
)
from app.engine.rationale import build_rationale
from app.analysis.signal import generate_signal
class TestR2MandatoryCorrelationExemption:
    """R2: 强制锚（沪深300/中证A500/黄金/国债）永不被关联度削减击穿 ≥5% 地板。

    design 570 实证：balanced 方案 159338 中证A500（强制锚）被 enforce_max_correlation
    削到 1%，违反 M7「核心单只 ≥5%」。根因是削减未继承 MANDATORY_CODES 豁免。
    """

    def _mk(self, allocs):
        return [{"id": "balanced", "allocations": allocs}]

    def test_both_mandatory_anchors_not_reduced(self):
        """双方强制锚（510300↔159338，r=0.98）合计 0.45 超阈 → 仅标注、不削减，各自 ≥5%。"""
        allocs = [
            {"symbol": "510300", "name": "沪深300", "layer": "core",
             "weight": 0.25, "factor_score": 0.8},
            {"symbol": "159338", "name": "中证A500", "layer": "core",
             "weight": 0.20, "factor_score": -0.96},  # 原 R2 触发方（深负因子分）
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.15, "factor_score": 0.6},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("510300", "159338"): 0.98}
        # 即便 159338 因子分极深负，也不得被削到 1%
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["159338"] >= 0.05 - 1e-9, f"强制锚 159338 被削到 {weights['159338']}"
        assert weights["510300"] >= 0.05 - 1e-9
        # 标注存在且不含被削减标的（round24 R24②: 沪深300/中证A500 同族 → 附加 near_substitute 层）
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert len(warnings) == 2
        assert warnings[0]["reduced_symbol"] is None
        assert "豁免" in warnings[0]["note"]
        assert any(w.get("type") == "near_substitute" for w in warnings)
        # 双方强制锚权重不变
        assert weights["159338"] == 0.20
        assert weights["510300"] == 0.25

    def test_one_mandatory_anchor_kept(self):
        """单方强制锚（510300, r=0.95 与非强制 512480 高相关，合计 0.30）→ 削非强制方，强制方 ≥5%。"""
        allocs = [
            {"symbol": "510300", "name": "沪深300", "layer": "core",
             "weight": 0.10, "factor_score": 0.9},
            {"symbol": "512480", "name": "半导体", "layer": "satellite",
             "weight": 0.20, "factor_score": 0.3},
            {"symbol": "CASH", "weight": 0.70},
        ]
        matrix = {("510300", "512480"): 0.95}
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        # 强制锚不被削减
        assert weights["510300"] == 0.10
        # 非强制方被削到合计 <= 阈值
        assert weights["510300"] + weights["512480"] <= 0.25 + 1e-9
        assert weights["512480"] < 0.20 + 1e-9
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert warnings[0]["reduced_symbol"] == "512480"

    def test_defense_anchor_not_reduced(self):
        """防御强制锚（518880 黄金）与非强制高相关 → 黄金不被削，非强制方被削。"""
        allocs = [
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.20, "factor_score": 0.7},
            {"symbol": "159985", "name": "豆粕", "layer": "defense",
             "weight": 0.20, "factor_score": 0.2},
            {"symbol": "CASH", "weight": 0.60},
        ]
        matrix = {("518880", "159985"): 0.93}
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["518880"] == 0.20          # 强制锚不动
        # 非强制方被削
        assert weights["518880"] + weights["159985"] <= 0.25 + 1e-9
