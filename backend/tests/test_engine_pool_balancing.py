"""Pure-function tests for engine/pool_balancing.py.

round35 T-P2/B-3 (§16.4-B-3): split out of the oversized
``test_engine_pure_functions.py`` (now deleted) into per-module files, plus
new edge cases (static-anchor injection without scan hit, cross-layer dedup
isolation, missing fund_scale handling, mandatory-exceeds-max truncation).
"""

from app.engine.budgets import MANDATORY_CODES  # round35 B1-F2: 真相源 budgets
from app.engine.pool_balancing import (
    ALL_LAYERS,
    LAYER_CORE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    LAYER_SATELLITE,
    assign_layer,
    balance_by_industry,
    deduplicate_by_index,
    ensure_mandatory,
    normalize_tracked_index,
    recheck_mandatory_after_truncate,
    truncate_with_mandatory_protection,
)


def _empty_pool():
    return {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
            LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}


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

    def test_both_empty_falls_to_research(self):
        # base→satellite、industry→unknown；unknown 分支先于 satellite 兜底命中
        assert assign_layer("", "") == LAYER_RESEARCH


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

    def test_unrelated_indices_untouched(self):
        assert normalize_tracked_index("科创50") == "科创50"
        assert normalize_tracked_index("中证A500") == "中证A500"


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

    # ── 新增边界 ──────────────────────────────────────────────

    def test_missing_fund_scale_treated_as_zero(self):
        """缺 scale 的条目 vs 有 scale 的同指数条目 → 后者胜（None/0 容错）。"""
        pool = {"core": [
            {"symbol": "A", "tracked_index": "沪深300"},              # no scale
            {"symbol": "B", "tracked_index": "沪深300", "fund_scale": 88},
        ]}
        result = deduplicate_by_index(pool)
        assert [e["symbol"] for e in result["core"]] == ["B"]

    def test_same_index_in_different_layers_both_kept(self):
        """去重是**层内**截面：跨层同名指数互不挤占。"""
        pool = {
            "core": [{"symbol": "A", "tracked_index": "沪深300", "fund_scale": 100}],
            "satellite": [{"symbol": "B", "tracked_index": "沪深300", "fund_scale": 50}],
        }
        result = deduplicate_by_index(pool)
        assert [e["symbol"] for e in result["core"]] == ["A"]
        assert [e["symbol"] for e in result["satellite"]] == ["B"]


class TestEnsureMandatory:
    def test_injects_missing_from_flat(self):
        pool = _empty_pool()
        flat = [{"symbol": "510300", "layer": "satellite"}]
        ensure_mandatory(pool, flat)
        core_codes = [e["symbol"] for e in pool[LAYER_CORE]]
        assert "510300" in core_codes

    def test_defense_codes_inject_to_defense(self):
        pool = _empty_pool()
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

    # ── 新增边界 ──────────────────────────────────────────────

    def test_static_anchor_injection_when_scan_misses_core_anchor(self):
        """R105 B'：扫描缺核心锚 → 静态元数据注入（带 name/tracked_index）。"""
        pool = _empty_pool()
        flat = [{"symbol": "510300"}]  # 159338 缺席
        ensure_mandatory(pool, flat)
        injected = next(e for e in pool[LAYER_CORE] if e["symbol"] == "159338")
        assert injected["name"] == "中证A500ETF"
        assert injected["tracked_index"] == "中证A500"
        assert injected["layer"] == LAYER_CORE

    def test_defense_anchor_missing_and_no_meta_not_fabricated(self):
        """防御锚缺扫且无静态元数据 → 只 WARNING，不伪造入池。"""
        pool = _empty_pool()
        flat = [{"symbol": "510300"}, {"symbol": "159338"}]  # 防御双锚缺席
        ensure_mandatory(pool, flat)
        assert all(len(layer) == 0 or all(
            e["symbol"] in ("510300", "159338") for e in layer
        ) for layer in pool.values())
        assert not any(
            e["symbol"] in ("518880", "511090")
            for layer in pool.values() for e in layer
        ), "无静态元数据的防御锚不得伪造注入"


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

    def test_all_mandatory_still_kept_even_if_exceeds_max(self):
        """强制标的数 > max_n 时一个不丢（保护优先于配额）。"""
        balanced = self._items(list(MANDATORY_CODES) + ["x1", "x2"])
        result = truncate_with_mandatory_protection(balanced, max_n=1)
        kept = {e["symbol"] for e in result}
        assert set(MANDATORY_CODES) <= kept


class TestRecheckMandatoryAfterTruncate:
    def test_reinjects_missing(self):
        pool = _empty_pool()
        flat = [{"symbol": "159338"}]
        recheck_mandatory_after_truncate(pool, flat, required_codes={"159338"})
        assert any(e["symbol"] == "159338" for layer in pool.values() for e in layer)

    def test_skips_existing(self):
        pool = {LAYER_CORE: [{"symbol": "510300"}], LAYER_SATELLITE: [], LAYER_DEFENSE: [],
                LAYER_OPPORTUNISTIC: [], LAYER_RESEARCH: []}
        recheck_mandatory_after_truncate(pool, [{"symbol": "510300"}], required_codes={"510300"})
        assert len(pool[LAYER_CORE]) == 1

    def test_missing_code_not_in_flat_skipped(self):
        pool = _empty_pool()
        # 510300 not in flat -> silently skipped (no crash)
        recheck_mandatory_after_truncate(pool, [{"symbol": "159338"}], required_codes={"510300"})
        assert all(len(layer) == 0 for layer in pool.values())

    def test_defense_reinject(self):
        pool = _empty_pool()
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

    # ── 新增边界 ──────────────────────────────────────────────

    def test_max_n_smaller_than_segment_count_truncates(self):
        """段落数超过 max_n：每段先各出一人，再按插入序截到 max_n（确定性）。"""
        items = [
            self._item("s1", "半导体", 9.0),
            self._item("s2", "银行", 8.0),
            self._item("s3", "医药", 7.0),
        ]
        result = balance_by_industry(items, max_n=2)
        assert len(result) == 2
        segments = {e["segment"] for e in result}
        assert len(segments) == 2, "截断结果仍应保持段落多样性"

    def test_missing_composite_score_defaults_to_zero(self):
        # 4 items > max_n=3：绕过 len<=max_n 直通短路，真正走进排序路径
        items = [
            {"symbol": "low", "segment": "银行"},                      # score 缺省 0
            self._item("high", "银行", 3.0),
            self._item("pad1", "医药", 1.0),
            self._item("pad2", "证券", 0.5),
        ]
        result = balance_by_industry(items, max_n=3)
        assert result[0]["symbol"] == "high", "缺 composite_score 视为 0 参与排序"
        assert "low" not in [e["symbol"] for e in result[:2]], (
            "同段内 low(0) 不应排到 high(3) 前面"
        )

    def test_missing_segment_falls_to_industry_field(self):
        items = [
            self._item("a", "半导体", 5.0),
            self._item("b", "", 4.0),
        ]
        items[1]["industry"] = "银行"
        result = balance_by_industry(items, max_n=3)
        assert {e["symbol"] for e in result} == {"a", "b"}


def test_constants():
    assert ALL_LAYERS == [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE,
                          LAYER_OPPORTUNISTIC, LAYER_RESEARCH]
    assert "510300" in MANDATORY_CODES
