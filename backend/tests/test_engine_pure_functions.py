"""Pure-function tests for the engine/ extraction (Batch 4, plan A Step 2).

Functions moved from MarketDataHub to engine/ (composite_signal + pool_balancing)
are pure: deterministic inputs -> deterministic outputs. These tests give them
standalone coverage (target >=90%) and pin the behavior extracted from the facade.
"""

import pytest

from app.engine.composite_signal import (
    _LAYER_WEIGHTS,
    _BASE_WEIGHTS,
    normalize_regime,
    is_market_hours,
    pct_rank,
    compute_composite,
)
from app.engine.pool_balancing import (
    ALL_LAYERS,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    MANDATORY_CODES,
    assign_layer,
    normalize_tracked_index,
    deduplicate_by_index,
    ensure_mandatory,
    truncate_with_mandatory_protection,
    recheck_mandatory_after_truncate,
    balance_by_industry,
)


class TestAssignLayer:
    def test_core_wide_index(self):
        assert assign_layer("core", "") == LAYER_CORE
        assert assign_layer("", "宽基指数") == LAYER_CORE

    def test_defense_commodity_fixed_income(self):
        assert assign_layer("defense", "") == LAYER_DEFENSE
        assert assign_layer("", "商品") == LAYER_DEFENSE
        assert assign_layer("", "固收") == LAYER_DEFENSE

    def test_cross_border_satellite_not_defense(self):
        assert assign_layer("", "跨境") == LAYER_SATELLITE

    def test_unknown_research_and_fallback(self):
        assert assign_layer("", "unknown") == LAYER_RESEARCH
        assert assign_layer("opportunistic", "whatever") == LAYER_SATELLITE


class TestNormalizeTrackedIndex:
    def test_family_slices(self):
        assert normalize_tracked_index("中证500价值") == "中证500"
        assert normalize_tracked_index("中证500成长") == "中证500"
        assert normalize_tracked_index("中证500增强") == "中证500"
        assert normalize_tracked_index("沪深300增强") == "沪深300"
        assert normalize_tracked_index("沪深300价值") == "沪深300"

    def test_base_untouched_and_empty(self):
        assert normalize_tracked_index("中证500") == "中证500"
        assert normalize_tracked_index("") == ""


class TestDeduplicateByIndex:
    def test_keeps_largest_in_family(self):
        pool = {"core": [
            {"symbol": "510310", "tracked_index": "沪深300", "fund_scale": 100},
            {"symbol": "510300", "tracked_index": "沪深300", "fund_scale": 500},
        ]}
        result = deduplicate_by_index(pool)
        codes = [e["symbol"] for e in result["core"]]
        assert codes == ["510300"]

    def test_family_normalized_before_dedup(self):
        pool = {"core": [
            {"symbol": "A", "tracked_index": "沪深300增强", "fund_scale": 100},
            {"symbol": "B", "tracked_index": "沪深300", "fund_scale": 200},
        ]}
        result = deduplicate_by_index(pool)
        assert [e["symbol"] for e in result["core"]] == ["B"]

    def test_keeps_other_indices(self):
        pool = {"core": [
            {"symbol": "A", "tracked_index": "沪深300", "fund_scale": 100},
            {"symbol": "B", "tracked_index": "中证500", "fund_scale": 200},
        ]}
        result = deduplicate_by_index(pool)
        assert {e["symbol"] for e in result["core"]} == {"A", "B"}

    def test_name_based_dedup_when_no_tracked_index(self):
        pool = {"core": [
            {"symbol": "A", "name": "沪深300ETF", "fund_scale": 100},
            {"symbol": "B", "name": "沪深300联接", "fund_scale": 200},
        ]}
        result = deduplicate_by_index(pool)
        # 同一概念（沪深300）：ETF 优先于联接
        assert [e["symbol"] for e in result["core"]] == ["A"]

    def test_name_based_dedup_scale_replaces(self):
        pool = {"core": [
            {"symbol": "A", "name": "沪深300联接", "fund_scale": 100},
            {"symbol": "B", "name": "沪深300联接", "fund_scale": 300},
        ]}
        result = deduplicate_by_index(pool)
        assert [e["symbol"] for e in result["core"]] == ["B"]

    def test_name_concept_unresolvable_kept(self):
        pool = {"core": [
            {"symbol": "X", "name": "华夏", "fund_scale": 10},
        ]}
        result = deduplicate_by_index(pool)
        assert [e["symbol"] for e in result["core"]] == ["X"]

    def test_empty(self):
        assert deduplicate_by_index({}) == {layer: [] for layer in ALL_LAYERS}


class TestEnsureMandatory:
    def test_injects_missing_from_flat(self):
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        flat = [{"symbol": "510300", "layer": "satellite"}]
        ensure_mandatory(pool, flat)
        core_codes = [e["symbol"] for e in pool[LAYER_CORE]]
        assert "510300" in core_codes

    def test_defense_codes_inject_to_defense(self):
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        flat = [{"symbol": "518880"}, {"symbol": "511090"}]
        ensure_mandatory(pool, flat)
        defense_codes = {e["symbol"] for e in pool[LAYER_DEFENSE]}
        assert {"518880", "511090"} <= defense_codes

    def test_skips_when_already_in_pool(self):
        # R105 B' (round34): 缺锚时 ensure_mandatory 会静态注入（不再静默跳过）——
        # 本用例改为「全部强制锚已在池」场景，断言不重复注入
        # （原意图保留：in-pool 成员不重复 enforce）。
        pool = {LAYER_CORE: [{"symbol": "510300"}, {"symbol": "159338"}],
                LAYER_DEFENSE: [{"symbol": "518880"}, {"symbol": "511090"}],
                LAYER_SATELLITE: [], LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        before = len(pool[LAYER_CORE])
        ensure_mandatory(pool, [{"symbol": "510300"}])
        assert len(pool[LAYER_CORE]) == before

    def test_noop_when_flat_empty(self):
        pool = {}
        ensure_mandatory(pool, [])
        assert pool == {}


class TestTruncateWithMandatoryProtection:
    def _items(self, symbols):
        return [{"symbol": s} for s in symbols]

    def test_mandatory_kept_after_truncate(self):
        balanced = self._items(["510300", "x1", "x2", "x3", "x4"])
        result = truncate_with_mandatory_protection(balanced, max_n=3)
        symbols = [e["symbol"] for e in result]
        assert "510300" in symbols
        assert len(symbols) == 4  # mandatory + max_n

    def test_no_mandatory_plain_truncate(self):
        balanced = self._items(["a", "b", "c", "d"])
        result = truncate_with_mandatory_protection(balanced, max_n=2)
        assert [e["symbol"] for e in result] == ["a", "b"]


class TestRecheckMandatoryAfterTruncate:
    def test_reinjects_missing(self):
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        flat = [{"symbol": "159338"}]
        recheck_mandatory_after_truncate(pool, flat, required_codes={"159338"})
        assert any(e["symbol"] == "159338" for layer in pool.values() for e in layer)

    def test_skips_existing(self):
        pool = {LAYER_CORE: [{"symbol": "510300"}], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        recheck_mandatory_after_truncate(pool, [{"symbol": "510300"}], required_codes={"510300"})
        assert len(pool[LAYER_CORE]) == 1

    def test_missing_code_not_in_flat_skipped(self):
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        # 510300 not in flat -> silently skipped (no crash)
        recheck_mandatory_after_truncate(pool, [{"symbol": "159338"}], required_codes={"510300"})
        assert all(len(layer) == 0 for layer in pool.values())

    def test_defense_reinject(self):
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        recheck_mandatory_after_truncate(pool, [{"symbol": "518880"}], required_codes={"518880"})
        assert any(e["symbol"] == "518880" for e in pool[LAYER_DEFENSE])

    def test_noop_when_flat_empty(self):
        pool = {}
        recheck_mandatory_after_truncate(pool, [], required_codes={"510300"})
        assert pool == {}


class TestBalanceByIndustry:
    def _item(self, symbol, segment, score):
        return {"symbol": symbol, "segment": segment, "composite_score": score}

    def test_returns_empty_for_empty(self):
        assert balance_by_industry([]) == []

    def test_short_list_passthrough(self):
        items = [self._item("a", "半导体", 1.0), self._item("b", "银行", 2.0)]
        assert balance_by_industry(items, max_n=10) == items

    def test_one_per_segment_first(self):
        items = [
            self._item("a1", "半导体", 5.0),
            self._item("a2", "半导体", 1.0),
            self._item("b1", "银行", 4.0),
        ]
        result = balance_by_industry(items, max_n=2)
        symbols = [e["symbol"] for e in result]
        # a1 (higher in 半导体) and b1 both selected; a2 excluded (same segment)
        assert "a1" in symbols and "b1" in symbols
        assert "a2" not in symbols

    def test_fills_remaining_by_score(self):
        items = [
            self._item("a1", "半导体", 1.0),
            self._item("a2", "半导体", 5.0),
            self._item("b1", "银行", 1.0),
        ]
        result = balance_by_industry(items, max_n=3)
        symbols = [e["symbol"] for e in result]
        # one per segment (a2, b1) then fill with next-highest (a1)
        assert set(symbols) == {"a2", "b1", "a1"}


class TestPctRank:
    def test_ties(self):
        assert pct_rank(30.0, [10.0, 30.0, 50.0]) == pytest.approx(0.5)
        assert pct_rank(50.0, [10.0, 30.0, 50.0]) == pytest.approx((2 + 0.5) / 3)
        assert pct_rank(100.0, [10.0, 30.0, 50.0]) == pytest.approx(1.0)
        assert pct_rank(1.0, []) == 0.0


class TestNormalizeRegime:
    def test_maps_variants_to_table_keys(self):
        # delegates to core/regime.normalize_regime
        assert normalize_regime("neutral") in ("neutral",)
        assert callable(normalize_regime)


class TestIsMarketHours:
    def test_returns_bool(self):
        assert isinstance(is_market_hours(), bool)


class TestComputeComposite:
    def _item(self, amount=1e9, scale=2000.0, factor_sum=0.0):
        return {
            "amount": amount,
            "fund_scale": scale,
            "factor_scores": {"technical": factor_sum, "momentum": 0.0,
                              "valuation": 0.0, "sentiment": 0.0},
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

    def test_default_helpers_used_when_not_injected(self):
        item = self._item(amount=1e8, scale=10.0, factor_sum=0.0)
        # no injection -> uses built-in is_market_hours/pct_rank/normalize_regime
        s = compute_composite(item, "satellite", "neutral")
        assert isinstance(s, float)

    def test_weights_tables_present(self):
        assert "core" in _LAYER_WEIGHTS
        assert "factor" in _BASE_WEIGHTS


def test_constants():
    assert ALL_LAYERS == [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE,
                          LAYER_OPPORTUNISTIC, LAYER_RESEARCH]
    assert "510300" in MANDATORY_CODES
