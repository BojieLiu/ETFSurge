"""Pure-function tests for engine/composite_signal.py.

round35 T-P2/B-3 (§16.4-B-3): split out of the oversized
``test_engine_pure_functions.py`` (now deleted) into per-module files, plus
new edge cases (tanh saturation, R85 None-skip, P0-4 dotted-key exclusion,
research-layer isolation, weight-table invariants).
"""

import math

import pytest

from app.engine.composite_signal import (
    _BASE_WEIGHTS,
    _LAYER_WEIGHTS,
    compute_composite,
    is_market_hours,
    normalize_regime,
    pct_rank,
)

_REGIMES = ("bull", "bear", "correction", "neutral")


class TestPctRank:
    def test_ties(self):
        assert pct_rank(30.0, [10.0, 30.0, 50.0]) == pytest.approx(0.5)
        assert pct_rank(50.0, [10.0, 30.0, 50.0]) == pytest.approx((2 + 0.5) / 3)
        assert pct_rank(100.0, [10.0, 30.0, 50.0]) == pytest.approx(1.0)
        assert pct_rank(1.0, []) == 0.0

    def test_below_all_is_zero(self):
        assert pct_rank(-100.0, [10.0, 30.0]) == 0.0

    def test_all_identical_series_gives_half(self):
        # below=0, equal=n -> (0 + n/2)/n = 0.5：并列全按半计的退化情形
        assert pct_rank(7.0, [7.0, 7.0, 7.0]) == pytest.approx(0.5)

    def test_single_element_equal_counts_half(self):
        assert pct_rank(1.0, [1.0]) == pytest.approx(0.5)


class TestNormalizeRegime:
    def test_maps_variants_to_table_keys(self):
        # delegates to core/regime.normalize_regime
        assert normalize_regime("neutral") in ("neutral",)
        assert callable(normalize_regime)


class TestIsMarketHours:
    def test_returns_bool(self):
        assert isinstance(is_market_hours(), bool)


class TestWeightTableInvariants:
    """权重表结构不变量：每层覆盖全部市况、各分量和为 1（防手改漂移）。"""

    def test_every_layer_covers_all_regimes(self):
        for layer, table in _LAYER_WEIGHTS.items():
            assert set(table.keys()) == set(_REGIMES), layer

    def test_every_weight_vector_sums_to_one(self):
        for table in _LAYER_WEIGHTS.values():
            for regime, w in table.items():
                assert sum(w.values()) == pytest.approx(1.0), f"{regime}: {w}"
        assert sum(_BASE_WEIGHTS.values()) == pytest.approx(1.0)


class TestComputeComposite:
    def _item(self, amount=1e9, scale=2000.0, factor_sum=0.0, extra_factors=None):
        fs = {"technical": factor_sum, "momentum": 0.0,
              "valuation": 0.0, "sentiment": 0.0}
        if extra_factors:
            fs.update(extra_factors)
        return {
            "amount": amount,
            "fund_scale": scale,
            "factor_scores": fs,
        }

    def test_scale_discrimination_restored(self):
        """2000 亿 vs 30 亿（factor_sum 均 0）→ composite 可区分。"""
        big = self._item(amount=1e9, scale=2000.0)
        small = self._item(amount=1e9, scale=30.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 30.0]
        s_big = compute_composite(big, "core", "neutral", amounts, scales,
                                  is_market_hours=lambda: True)
        s_small = compute_composite(small, "core", "neutral", amounts, scales,
                                    is_market_hours=lambda: True)
        assert s_big > s_small

    def test_factor_dominance_kept(self):
        hi = self._item(amount=1e9, scale=2000.0, factor_sum=9.0)
        lo = self._item(amount=1e9, scale=2000.0, factor_sum=0.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 2000.0]
        s_hi = compute_composite(hi, "core", "neutral", amounts, scales,
                                 is_market_hours=lambda: True)
        s_lo = compute_composite(lo, "core", "neutral", amounts, scales,
                                 is_market_hours=lambda: True)
        assert s_hi > s_lo

    def test_off_hours_liquidity_halved(self):
        item = self._item(amount=1e8, scale=10.0, factor_sum=0.0)
        on = compute_composite(item, "satellite", "neutral", None, None,
                               is_market_hours=lambda: True)
        off = compute_composite(item, "satellite", "neutral", None, None,
                                is_market_hours=lambda: False)
        assert off < on, "非交易时段流动性权重减半应降低 composite"

    def test_off_hours_conservation(self):
        """P6 精确语义：流动性权重减半，另一半并入规模——总量守恒。"""
        item = self._item(amount=4e9, scale=800.0, factor_sum=3.0)
        on = compute_composite(item, "defense", "neutral", None, None,
                               is_market_hours=lambda: True)
        off = compute_composite(item, "defense", "neutral", None, None,
                                is_market_hours=lambda: False)
        w = _LAYER_WEIGHTS["defense"]["neutral"]
        expected_off = (
            w["factor"] * 3.0
            + (w["liquidity"] / 2) * 4e9 * 1e-9
            + (w["scale"] + w["liquidity"] / 2) * 800.0 * 1e-9
            + w["opp"] * 0.5
        )
        assert off == pytest.approx(expected_off)
        assert on != off

    def test_legacy_path_backward_compat(self):
        item = self._item(amount=4.47e9, scale=1193.85, factor_sum=1.0)
        s = compute_composite(item, "core", "neutral", None, None,
                              is_market_hours=lambda: True)
        assert s == pytest.approx(0.50 * 1.0 + 0.25 * 4.47e9 * 1e-9 + 0.25 * 1193.85 * 1e-9)

    def test_opportunistic_keeps_legacy(self):
        item = self._item(amount=1e8, scale=10.0, factor_sum=0.0)
        item["composite_score"] = 0.6
        s = compute_composite(item, "opportunistic", "neutral", None, None,
                              is_market_hours=lambda: True)
        assert s == pytest.approx(0.15 * 1e8 * 1e-9 + 0.35 * 0.6, abs=1e-9)

    def test_opportunistic_ignores_cross_section_vectors(self):
        """opportunistic 不在百分位分支白名单——即使传截面向量也走 legacy 路径。"""
        item = self._item(amount=1e8, scale=10.0, factor_sum=2.0)
        s_vec = compute_composite(item, "opportunistic", "neutral",
                                  [1e8, 2e8], [10.0, 20.0],
                                  is_market_hours=lambda: True)
        s_legacy = compute_composite(item, "opportunistic", "neutral", None, None,
                                     is_market_hours=lambda: True)
        assert s_vec == pytest.approx(s_legacy)

    def test_default_helpers_used_when_not_injected(self):
        item = self._item(amount=1e8, scale=10.0, factor_sum=0.0)
        # no injection -> uses built-in is_market_hours/pct_rank/normalize_regime
        s = compute_composite(item, "satellite", "neutral")
        assert isinstance(s, float)

    def test_weights_tables_present(self):
        assert "core" in _LAYER_WEIGHTS
        assert "factor" in _BASE_WEIGHTS

    # ── 新增边界 ──────────────────────────────────────────────

    def test_unknown_layer_research_style_amount_only(self):
        """未登记层（含 research）只吃 amount*1e-9——因子/规模/opp 全部忽略。"""
        item = self._item(amount=3e9, scale=500.0, factor_sum=9.0)
        item["composite_score"] = 0.99
        s = compute_composite(item, "mystery-layer", "bull", None, None,
                              is_market_hours=lambda: True)
        assert s == pytest.approx(3e9 * 1e-9)

    def test_r85_none_factor_values_skipped_not_crash(self):
        """R85：None/非数值因子跳过（诚实缺数据），不抛 TypeError。"""
        item = self._item(factor_sum=2.0,
                          extra_factors={"technical": None, "sentiment": "n/a"})
        s = compute_composite(item, "core", "neutral", None, None,
                              is_market_hours=lambda: True)
        # 仅 momentum(0)+valuation(0) 计入 → factor_sum=0；core 走层表权重
        w = _LAYER_WEIGHTS["core"]["neutral"]
        assert s == pytest.approx(
            w["liquidity"] * 1e9 * 1e-9 + w["scale"] * 2000.0 * 1e-9
        )

    def test_p0_4_dotted_keys_excluded_from_sum(self):
        """P0-4：原始点分键不参与聚合（防 RSI=50 主导排序）。"""
        item = self._item(factor_sum=1.0,
                          extra_factors={"technical.rsi": 50.0})
        s_dotted = compute_composite(item, "core", "neutral", None, None,
                                     is_market_hours=lambda: True)
        s_clean = compute_composite(
            self._item(factor_sum=1.0), "core", "neutral", None, None,
            is_market_hours=lambda: True)
        assert s_dotted == pytest.approx(s_clean)

    def test_missing_factor_scores_key_defaults_zero(self):
        item = {"amount": 1e9, "fund_scale": 100.0}
        s = compute_composite(item, "core", "neutral", None, None,
                              is_market_hours=lambda: True)
        w = _LAYER_WEIGHTS["core"]["neutral"]
        assert s == pytest.approx(
            w["liquidity"] * 1e9 * 1e-9 + w["scale"] * 100.0 * 1e-9
        )

    def test_tanh_caps_cross_section_score_at_one(self):
        """tanh 饱和：极端 factor_sum 时百分位路径总分有界 ≤1，不会爆表。"""
        item = self._item(amount=2e9, scale=3000.0, factor_sum=1e6)
        s = compute_composite(item, "satellite", "bear",
                              [2e9], [3000.0],
                              is_market_hours=lambda: True)
        assert 0.0 < s <= 1.0
        # tanh 上界证据：factor 贡献逼近层权重而非线性爆炸
        assert s < _LAYER_WEIGHTS["satellite"]["bear"]["factor"] * math.tanh(1e6 / 6.0) + 0.55
