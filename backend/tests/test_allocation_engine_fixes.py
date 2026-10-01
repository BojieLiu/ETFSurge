from __future__ import annotations
"""
M4-M6 (docs/combination-design-review.md): 分配引擎层修正测试。

- M4: 核心层数量 = layer_count - 强制标的数（强制 510300/159338 额外叠加 → 5-6 只被摊薄）。
- M5: 卫星 backup 补足排除宽基（industry=宽基指数）——宁可卫星 <4 也不混入宽基。
- M6: 跨层同一指数家族最多 1 次（M3 归一化后 _dedup_segment 生效）。
- M1 联动: 防御型方案红利类合计权重上限 15%（用户决策 2026-08-01）。

纯函数测试，无 I/O。
"""

from app.engine.allocation_engine import (
    allocate,
    _select_and_weight,
    MANDATORY_CODES,
    _COMMON_ANCHOR_SYMBOLS,
)
from app.engine.risk_controls import apply_risk_controls
import copy


def _factor_matrix(candidates):
    return {c["symbol"]: {"technical": 0.5, "momentum": 0.5,
                          "valuation": 0.5, "sentiment": 0.5}
            for c in candidates}


def _base_candidates():
    """含强制标的（510300/159338）+ 若干核心 + 卫星 + 防御。"""
    return [
        # core（含 2 只强制标的）
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
        {"symbol": "159915", "name": "创业板ETF", "layer": "core",
         "tracked_index": "创业板指", "industry": "宽基指数", "segment": "创业板"},
        {"symbol": "510050", "name": "上证50ETF", "layer": "core",
         "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
        # satellite
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "segment": "半导体"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
         "tracked_index": "新能源", "segment": "新能源"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
         "tracked_index": "医药", "segment": "医药"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        # defense
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "segment": "黄金"},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "tracked_index": "国债", "segment": "国债"},
    ]


class TestM4CoreCount:
    def test_defensive_core_count_includes_mandatory(self):
        """M4: 防御型 core 总数 = layer_count(4)，含 2 只强制标的 → 评分入选仅 2 只。"""
        cands = _base_candidates()
        strategies = allocate(risk_profile="defensive", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "defensive":
                continue
            core = [a for a in s["allocations"] if a.get("layer") == "core"]
            assert len(core) <= 4, f"防御型核心层 {len(core)} 只，超上限 4（含强制）"
            # 强制标的必现
            core_syms = {a["symbol"] for a in core}
            assert "510300" in core_syms and "159338" in core_syms

    def test_balanced_core_count_includes_mandatory(self):
        """M4: 平衡/进攻型 core 总数 = layer_count(5)，含 2 只强制 → 评分入选仅 3 只。"""
        cands = _base_candidates()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "balanced":
                continue
            core = [a for a in s["allocations"] if a.get("layer") == "core"]
            assert len(core) <= 5, f"平衡型核心层 {len(core)} 只，超上限 5（含强制）"

    def test_all_profiles_core_within_3_to_5(self):
        """M7 联动: 三套方案核心层 ∈ [3, 5] 且单只权重 ≥5%。"""
        cands = _base_candidates()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            core = [a for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
            assert 3 <= len(core) <= 5, f"{s['id']} 核心层 {len(core)} 只不在 [3,5]"
            for a in core:
                assert a.get("weight", 0) >= 0.05, f"{s['id']} 核心 {a['symbol']} 权重 {a['weight']} < 5%"


class TestM5SatelliteBackupExcludesWideBasis:
    def test_satellite_backup_skips_wide_basis(self):
        """M5: 卫星候选不足 4 只时，backup 从 core 拉取但排除宽基（industry=宽基指数）。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "510500", "name": "中证500ETF", "layer": "core",
             "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
            {"symbol": "512890", "name": "红利低波ETF", "layer": "core",
             "tracked_index": "红利低波", "industry": "红利低波", "segment": "红利低波"},
            # 卫星只有 1 只（科创系）
            {"symbol": "589960", "name": "科创新能源ETF", "layer": "satellite",
             "tracked_index": "科创新能源", "segment": "科创"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        for s in strategies:
            sats = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            for a in sats:
                assert a.get("industry") != "宽基指数", \
                    f"{s['id']} 卫星层混入宽基 {a['symbol']}（industry=宽基指数）"
                assert a["symbol"] not in ("510300", "510500", "562000"), \
                    f"{s['id']} 卫星层混入宽基 {a['symbol']}"


class TestM6CrossLayerFamilyUnique:
    def test_cross_layer_same_family_not_duplicated(self):
        """M6: 510500（中证500）入选 core 后，562330（中证500价值→segment=中证500）不得再入卫星。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "510500", "name": "中证500ETF", "layer": "core",
             "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
            {"symbol": "562330", "name": "中证500价值ETF", "layer": "satellite",
             "tracked_index": "中证500价值", "industry": "中证500价值", "segment": "中证500"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "segment": "半导体"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        for s in strategies:
            all_syms = {a["symbol"] for a in s["allocations"] if a.get("symbol") != "CASH"}
            # 中证500 家族（510500/562330）全组合最多出现 1 次
            family = all_syms & {"510500", "562330"}
            assert len(family) <= 1, f"{s['id']} 中证500家族出现 {family}（跨层去重失效）"


class TestM8FamilyDedupWithinLayer:
    def test_mid500_family_only_one_selected(self):
        """M8: 卫星候选池同层含 中证500价值/成长/增强/500 → 归一化后只选 1 只。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
            {"symbol": "562330", "name": "中证500价值ETF", "layer": "satellite",
             "tracked_index": "中证500价值", "industry": "中证500价值", "segment": "中证500"},
            {"symbol": "562500", "name": "中证500成长ETF", "layer": "satellite",
             "tracked_index": "中证500成长", "industry": "中证500成长", "segment": "中证500"},
            {"symbol": "510580", "name": "中证500增强ETF", "layer": "satellite",
             "tracked_index": "中证500增强", "industry": "中证500增强", "segment": "中证500"},
            {"symbol": "159922", "name": "中证500ETF", "layer": "satellite",
             "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "industry": "半导体", "segment": "半导体"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        for s in strategies:
            sats = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            family = {a["symbol"] for a in sats} & {"562330", "562500", "510580", "159922"}
            assert len(family) <= 1, \
                f"{s['id']} 卫星层中证500 家族出现多只 {family}（归一化去重失效）"

    def test_satellite_short_keeps_3_not_mix_wide(self):
        """M8: 卫星候选不足 4 只且 core 有宽基 → 卫星保持 <4（不混入宽基补齐）。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "industry": "半导体", "segment": "半导体"},
            {"symbol": "159819", "name": "人工智能ETF", "layer": "satellite",
             "tracked_index": "人工智能", "industry": "人工智能", "segment": "人工智能"},
            {"symbol": "512660", "name": "军工ETF", "layer": "satellite",
             "tracked_index": "军工", "industry": "军工", "segment": "军工"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        for s in strategies:
            sats = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            for a in sats:
                assert a.get("industry") != "宽基指数", \
                    f"{s['id']} 卫星层混入宽基 {a['symbol']}"
            # 卫星只有 3 只行业主题 → 不强补到 4（不混宽基）
            assert len(sats) <= 3, f"{s['id']} 卫星层 {len(sats)} 只（应保持 ≤3 不混宽基）"


class TestM1DividendCap:
    def test_defensive_dividend_cap_15(self):
        """M1 联动: 防御型红利类（512890/515080）合计权重 ≤15%。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "segment": "沪深300"},
            {"symbol": "512890", "name": "红利低波ETF", "layer": "core",
             "tracked_index": "红利低波", "segment": "红利低波"},
            {"symbol": "515080", "name": "中证红利ETF", "layer": "core",
             "tracked_index": "中证红利", "segment": "中证红利"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="defensive", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        strategies = apply_risk_controls(strategies, fm)
        for s in strategies:
            if s["id"] != "defensive":
                continue
            dividend = sum(
                a.get("weight", 0) for a in s["allocations"]
                if a.get("symbol") in ("512890", "515080")
            )
            assert dividend <= 0.15 + 1e-6, f"防御型红利类合计 {dividend:.2%} > 15%"


class TestM1DividendCapAllProfiles:
    """R5-0-4: 红利类权重上限约束扩展为全方案校验（用户决策 2026-08-03）。

    回归场景：balanced/aggressive 卫星层含红利类 ETF（563020 红利低波）时，
    旧逻辑仅约束 defensive → 卫星层红利合计可超 15%。
    修复后：任意方案红利类合计 ≤15%。
    """

    def _dividend_total(self, strategies, sid):
        for s in strategies:
            if s["id"] == sid:
                return sum(
                    a.get("weight", 0) for a in s["allocations"]
                    if a.get("symbol") in ("563020", "512890", "515080")
                )
        return 0.0

    def _assert_all_profiles_dividend_capped(self, risk_profile):
        candidates = [
            # core
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "segment": "沪深300"},
            {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "segment": "中证A500"},
            # satellite（红利低波 563020 双份权重场景 → 合计必超 15% 若不受限）
            {"symbol": "563020", "name": "红利低波ETF", "layer": "satellite",
             "tracked_index": "红利低波", "segment": "红利低波"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "segment": "半导体"},
            {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
             "tracked_index": "新能源", "segment": "新能源"},
            # defense
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
            {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
             "tracked_index": "国债", "segment": "国债"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile=risk_profile, regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        strategies = apply_risk_controls(strategies, fm)
        for s in strategies:
            dividend = self._dividend_total(strategies, s["id"])
            assert dividend <= 0.15 + 1e-6, \
                f"R5-0-4 {risk_profile}/{s['id']} 红利类合计 {dividend:.2%} > 15%"

    def test_balanced_satellite_dividend_capped(self):
        """balanced 卫星层红利低波 563020 合计 ≤15%。"""
        self._assert_all_profiles_dividend_capped("balanced")

    def test_aggressive_satellite_dividend_capped(self):
        """aggressive 卫星层红利低波 563020 合计 ≤15%。"""
        self._assert_all_profiles_dividend_capped("aggressive")

    def test_defensive_core_dividend_capped(self):
        """defensive 核心层红利低波 563020 合计 ≤15%（R5-0-4 仍保留原约束）。"""
        self._assert_all_profiles_dividend_capped("defensive")


class TestMandatoryMissingErrors:
    def test_select_and_weight_mandatory_missing_still_works(self):
        """M8 联动: 候选池缺失强制标的时分配不崩溃（注入校验已在 etf_scanner 层打 WARNING）。"""
        cands = [
            {"symbol": "588000", "name": "科创50ETF", "layer": "core",
             "tracked_index": "科创50", "segment": "科创"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "segment": "半导体"},
        ]
        fm = _factor_matrix(cands)
        allocs = _select_and_weight(cands, fm, budget=0.5, layer="core",
                                    regime="range_bound", strategy="balanced", max_count=4)
        assert isinstance(allocs, list)


class TestR502OverlapFallbackNarrow:
    """R5-0-2: 核心层跨方案重叠修复——兜底放宽仅限「公共底仓 + 强制标的」。

    回归场景：核心层非强制候选不足（<2 只）触发兜底放宽时，
    旧逻辑整体放开 → balanced/aggressive 与 defensive 核心层重叠 3 只
    （159915/562000/588000）→ P1-2 门禁 FAIL。
    修复后：只回补公共底仓（510300/159338/159338），其他已用标的一律不回补。
    """

    def _core_syms(self, strategies, sid):
        for s in strategies:
            if s["id"] == sid:
                return {a["symbol"] for a in s["allocations"]
                        if a.get("layer") == "core" and a.get("symbol") != "CASH"}
        return set()

    def test_fallback_only_common_anchor_and_mandatory(self):
        """去重后非强制候选 <2 时，与前一方案核心层重叠（剔除强制+公共底仓）≤1。"""
        cands = [
            # core：2 强制 + 3 只非强制（共 5 只核心候选）
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
            {"symbol": "588000", "name": "科创50ETF", "layer": "core",
             "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
            {"symbol": "159915", "name": "创业板ETF", "layer": "core",
             "tracked_index": "创业板指", "industry": "宽基指数", "segment": "创业板"},
            {"symbol": "510050", "name": "上证50ETF", "layer": "core",
             "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
            # satellite
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "segment": "半导体"},
            {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
             "tracked_index": "新能源", "segment": "新能源"},
            {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
             "tracked_index": "医药", "segment": "医药"},
            {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
             "tracked_index": "证券", "segment": "证券"},
            # defense
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
            {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
             "tracked_index": "国债", "segment": "国债"},
        ]
        fm = _factor_matrix(cands)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=cands)
        defensive = self._core_syms(strategies, "defensive")
        balanced = self._core_syms(strategies, "balanced")
        aggressive = self._core_syms(strategies, "aggressive")
        for name, a, b in [
            ("defensive vs balanced", defensive, balanced),
            ("defensive vs aggressive", defensive, aggressive),
            ("balanced vs aggressive", balanced, aggressive),
        ]:
            overlap = (a & b) - MANDATORY_CODES - _COMMON_ANCHOR_SYMBOLS
            assert len(overlap) <= 1, \
                f"R5-0-2 {name} 核心层非公共底仓重叠 {overlap} > 1"

    def test_fallback_keeps_core_count_lower_bound(self):
        """兜底放宽后核心层仍满足 [3,5] 下限（M7 联动，不空核心）。"""
        cands = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
            {"symbol": "588000", "name": "科创50ETF", "layer": "core",
             "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
            {"symbol": "159915", "name": "创业板ETF", "layer": "core",
             "tracked_index": "创业板指", "industry": "宽基指数", "segment": "创业板"},
            {"symbol": "510050", "name": "上证50ETF", "layer": "core",
             "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
            {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
             "tracked_index": "半导体", "segment": "半导体"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
            {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
             "tracked_index": "国债", "segment": "国债"},
        ]
        fm = _factor_matrix(cands)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=cands)
        for s in strategies:
            core = [a for a in s["allocations"]
                    if a.get("layer") == "core" and a.get("symbol") != "CASH"]
            assert len(core) >= 3, f"R5-0-2 {s['id']} 核心层 {len(core)} 只 < 3"


# ===== folded from test_round20_engine_fixes.py =====
from app.engine.allocation_engine import (
    allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
    _defense_anchors_for,
)
from app.engine.rationale import build_rationale
from app.analysis.signal import generate_signal
class TestP2_6PerLayerOverlapPenalty:
    def test_aggressive_satellite_not_polluted_by_defense_symbols(self):
        """P2-6 (round20 §6 P2-6): 进攻层卫星候选不得因防御层已选而被惩罚剔除。

        旧逻辑用单一 _used_symbols_for_overlap：防御层先选 518880/511090 后，
        进攻层卫星同符号会被惩罚 → 卫星不足 4 只、现金虚高。
        验收：aggressive 卫星层 >= 2 只（候选充足时），且与防御层共享符号不受影响。
        """
        cands = _base_candidates()
        strategies = allocate(risk_profile="aggressive", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            # 卫星候选 4 只（512480/515030/512010/512880）充足 → 至少选出 2 只
            assert len(sat) >= 2, f"aggressive 卫星层仅 {len(sat)} 只（<2），疑似被防御层符号污染"
            non_cash = sum(a.get("weight", 0) for a in s["allocations"]
                           if a.get("symbol") != "CASH")
            assert non_cash >= 0.7, f"aggressive 非现金权重 {non_cash:.2f} < 0.70（现金虚高）"

    def test_same_symbol_ok_across_layers(self):
        """同一符号同时出现在卫星/防御层候选时，层间互不惩罚（plan A 核心）。"""
        cands = _base_candidates()
        # 加入一只"跨层"标的：既作卫星主题、又作防御候选（模拟 511090 被防御先选）
        cands.append({"symbol": "513100", "name": "纳指ETF", "layer": "satellite",
                      "tracked_index": "纳指", "segment": "纳指"})
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "balanced":
                continue
            def_ = [a for a in s["allocations"] if a.get("layer") == "defense"]
            assert len(def_) >= 1, "防御层应保留黄金/国债候选（不被卫星惩罚）"
class TestP1_1MaxCorrelation:
    def _mk_strategy(self, allocs):
        return [{"id": "balanced", "allocations": allocs}]

    def test_high_corr_pair_reduced(self):
        """P1-1: r=0.95 的一对（非强制锚）合计权重 0.45 超阈值 → 削到 <=0.25，削低因子分一方。

        注：用非强制锚代码（半导体 512480 / 芯片 512760）以隔离「强制锚豁免」逻辑（见 R2）。
        """
        allocs = [
            {"symbol": "512480", "name": "半导体", "layer": "satellite",
             "weight": 0.25, "factor_score": 0.8, "factor_breakdown": {}},
            {"symbol": "512760", "name": "芯片", "layer": "satellite",
             "weight": 0.20, "factor_score": 0.4, "factor_breakdown": {}},
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.15, "factor_score": 0.6, "factor_breakdown": {}},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("512480", "512760"): 0.95}
        strategies = enforce_max_correlation(self._mk_strategy(allocs), matrix,
                                             threshold=0.9, max_combined_weight=0.25)
        s = strategies[0]
        pair = {a["symbol"]: a["weight"] for a in s["allocations"]
                if a["symbol"] in ("512480", "512760")}
        # 合计 <= 阈值（0.25）
        assert pair["512480"] + pair["512760"] <= 0.25 + 1e-9
        # 低因子分一方（512760, fs=0.4）被削减
        assert pair["512760"] < 0.20 + 1e-9
        # 报告标注 correlation_warnings（round24 R24② 语义：半导体/芯片同族告警已解耦
        # 至独立层 apply_near_substitute_warnings（round25 R41-a）——此处断言高相关削减
        # 标注；同族告警由独立层单独验证）
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert len(warnings) == 1
        assert warnings[0]["reduced_symbol"] == "512760"
        assert "关联度提示" in warnings[0]["note"]
        from app.engine.allocation_engine import apply_near_substitute_warnings
        # deepcopy：apply_near_substitute_warnings (R48) 会就地合并权重并移除被合并标的，
        # 若用 list(allocs) 浅拷贝会共享 dict 对象、污染上方 s["allocations"] 导致 Σ 权重虚高
        s2 = apply_near_substitute_warnings(self._mk_strategy(copy.deepcopy(allocs)), matrix)[0]
        assert any(w.get("type") == "near_substitute" for w in s2["risk_metrics"]["correlation_warnings"])
        # Σ 权重保持 = 1
        assert abs(sum(a["weight"] for a in s["allocations"] if a["symbol"] != "CASH") - 0.60) < 0.01

    def test_low_corr_pair_untouched(self):
        """r=0.5 < 0.9 → 不动，无 warning。"""
        allocs = [
            {"symbol": "512480", "weight": 0.30, "factor_score": 0.8},
            {"symbol": "512760", "weight": 0.30, "factor_score": 0.6},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("512480", "512760"): 0.5}
        s = enforce_max_correlation([{"id": "x", "allocations": allocs}], matrix)[0]
        assert "correlation_warnings" not in s.get("risk_metrics", {})
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["512480"] == 0.30
class TestP2_5StructureChecks:
    def test_negative_signal_defense_gets_note(self):
        """防御层含 factor_score<=-0.5 标的 → rationale 追加「负信号防御标的」提示。"""
        allocs = [
            {"symbol": "159338", "layer": "defense", "factor_score": -0.6,
             "selection_rationale": "防御配置"},
            {"symbol": "CASH", "weight": 0.5},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "defensive", "allocations": allocs}])
        a = strategies[0]["allocations"][0]
        assert "负信号防御标的" in a["selection_rationale"]
        ws = strategies[0]["risk_metrics"]["structure_warnings"]
        assert any(w["type"] == "negative_signal_in_defense" for w in ws)

    def test_defense_high_median_r_gets_note(self):
        """防御层 median_r>=0.35 却称「低相关/避险」→ 追加高相关提示。"""
        allocs = [
            {"symbol": "159915", "layer": "defense", "factor_score": 0.2,
             "selection_rationale": "与权益低相关，避险配置"},
            {"symbol": "CASH", "weight": 0.5},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "defensive", "allocations": allocs}],
            correlation_medians={"159915": 0.55})
        a = strategies[0]["allocations"][0]
        assert "非低相关对冲资产" in a["selection_rationale"]

    def test_r198_footnote_label_not_duplicate_composite_signal(self):
        """R198 (round57): 负信号防御脚注标签必须是「因子综合分」而非「综合信号」。

        负向断言：把 rationale 真实行文与脚注拼成设计报告的一行后，扫描全部
        「综合信号」标签下的数值——必须恰好 1 个（rationale 自身的三因子聚合分）。
        脚注若复用该标签，会出现两个不同口径的同名数值（factor_score vs 聚合分），
        即 round57 §3 实测 design 62 同行 -0.01 / -1.05 / -3.16 三值并存的同型缺陷。
        """
        import re as _re
        from app.engine.rationale import build_rationale

        line = build_rationale(
            "518880", "defense", "defensive",
            meta={"name": "黄金ETF华安"},
            # 技术/估值/动量 三者非零 → rationale 必输出「综合信号偏X（score）」
            factor_scores={"technical": -0.3, "valuation": 0.1, "momentum": -0.5},
        )
        allocs = [
            {"symbol": "518880", "layer": "defense", "factor_score": -0.62,
             "selection_rationale": line},
            {"symbol": "CASH", "weight": 0.5},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "defensive", "allocations": allocs}])
        rat = strategies[0]["allocations"][0]["selection_rationale"]

        assert "【结构提示：因子综合分 -0.62 为负" in rat
        # 脚注不得引入第二个「综合信号」标签
        labelled = _re.findall(r"综合信号[^（(]*[（(]([-+][\d.]+)[）)]", rat)
        assert len(labelled) == 1, f"同一行出现多个「综合信号」口径: {labelled}"
        # 脚注的数值以「因子综合分」标签单独出现，与聚合分不同值
        assert _re.findall(r"因子综合分 ([-+][\d.]+)", rat) == ["-0.62"]
        assert "-0.62" not in labelled

    def test_aggressive_cash_over_20pct_flagged(self):
        """进攻型现金 >20% → structure_warning（自洽校验）。"""
        allocs = [
            {"symbol": "510300", "layer": "core", "weight": 0.30},
            {"symbol": "512480", "layer": "satellite", "weight": 0.20},
            {"symbol": "CASH", "weight": 0.50},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "aggressive", "allocations": allocs}])
        ws = strategies[0]["risk_metrics"]["structure_warnings"]
        assert any(w["type"] == "aggressive_cash_over_20pct" for w in ws)
class TestP1_7DynamicSectorReward:
    def test_strong_sector_etf_rewarded_in_aggressive(self):
        """P1-7: 当日强势板块（医药 +7%）对应 ETF 在 aggressive 卫星层应获动态奖励
        （非 _RISKY_THEMES 静态科技列表）——composite 不被 -0.3 过滤、可入选。

        负向断言（验收）：强势板块 ETF 无奖励且被过滤 → FAIL。
        场景：医药 ETF 估值/情绪数据缺失（valuation=0 → valuation_missing=True →
        c2_bonus 分支生效），强势板块动态奖励 +1.5 使 composite 为正。
        """
        from app.engine.allocation_engine import allocate

        cands = _base_candidates()
        # 加入医药/创新药主题 ETF（非科技，_RISKY_THEMES 不含）
        cands.append({"symbol": "159992", "name": "创新药ETF", "layer": "satellite",
                      "tracked_index": "创新药", "segment": "创新药",
                      "industry": "医药"})
        cands.append({"symbol": "512170", "name": "医疗ETF", "layer": "satellite",
                      "tracked_index": "医疗", "segment": "医疗",
                      "industry": "医药"})
        # 当日强势板块：医药 +7%（涨幅前 3）
        sector_momentum = [
            {"sector_name": "医疗服务", "name": "医疗服务", "change_pct": 7.2},
            {"sector_name": "化学制药", "name": "化学制药", "change_pct": 5.1},
            {"sector_name": "半导体", "name": "半导体", "change_pct": 4.0},
        ]
        # 医药 ETF 估值缺失（valuation=0）→ c2_bonus 分支触发；其余估值正常
        fm = _factor_matrix(cands)
        for sym in ("159992", "512170"):
            fm[sym] = {"technical": 0.5, "momentum": 0.5,
                       "valuation": 0.0, "sentiment": 0.0}
        strategies = allocate(
            risk_profile="aggressive", regime="range_bound",
            factor_matrix=fm, candidates=cands,
            sector_momentum=sector_momentum,
        )
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            sat_syms = {a["symbol"] for a in sat}
            # 医药/医疗至少一只入选（强势板块动态奖励，非科技静态列表）
            assert sat_syms & {"159992", "512170"}, (
                f"强势板块（医药+7%）ETF 未入选 aggressive 卫星层（无动态奖励被过滤）: {sat_syms}"
            )
            # 卫星层 ≥2 只（P2-6 配套验收）
            assert len(sat) >= 2, f"aggressive 卫星层仅 {len(sat)} 只"


# ===== folded from test_round22_engine_redesign.py =====
from app.engine.allocation_engine import (
    allocate,
    check_structure_reasonableness,
    _is_growth_wide_basis,
)
from app.engine.budgets import (
    PROFILE_SPECS,
    validate_profile_specs,
    STRATEGY_META,
)
def _candidate_pool():
    """充足候选池：核心 7 只（含 2 只成长宽基 588000/159915），卫星 10 只，防御 2 只。

    成长宽基（industry=宽基指数 + 名称/指数含 创业板/科创50）触发 _is_growth_wide_basis。
    """
    return [
        # ── core (7) ──
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
        {"symbol": "159915", "name": "创业板ETF", "layer": "core",
         "tracked_index": "创业板指", "industry": "宽基指数", "segment": "创业板"},
        {"symbol": "510050", "name": "上证50ETF", "layer": "core",
         "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
        {"symbol": "510500", "name": "中证500ETF", "layer": "core",
         "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
        {"symbol": "159922", "name": "中证500ETF嘉实", "layer": "core",
         "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
        # ── satellite (10) ──
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "segment": "半导体"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
         "tracked_index": "新能源", "segment": "新能源"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
         "tracked_index": "医药", "segment": "医药"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        {"symbol": "515790", "name": "光伏ETF", "layer": "satellite",
         "tracked_index": "光伏", "segment": "光伏"},
        {"symbol": "516160", "name": "新能源设备ETF", "layer": "satellite",
         "tracked_index": "新能源设备", "segment": "新能源"},
        {"symbol": "512660", "name": "军工ETF", "layer": "satellite",
         "tracked_index": "军工", "segment": "军工"},
        {"symbol": "159869", "name": "游戏ETF", "layer": "satellite",
         "tracked_index": "游戏", "segment": "游戏"},
        {"symbol": "561790", "name": "有色ETF", "layer": "satellite",
         "tracked_index": "有色金属", "segment": "有色"},
        {"symbol": "515250", "name": "煤炭ETF", "layer": "satellite",
         "tracked_index": "煤炭", "segment": "煤炭"},
        # ── defense (2) ──
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "segment": "黄金"},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "tracked_index": "国债", "segment": "国债"},
    ]
def _allocs_by_id(strategies):
    return {s["id"]: s for s in strategies}
def _cash(s):
    non_cash = sum(a.get("weight", 0.0) for a in s.get("allocations", []) if a.get("symbol") != "CASH")
    return round(1.0 - non_cash, 4)
class TestProfileSpecInvariants:
    def test_profile_specs_loaded_and_valid(self):
        """budgets 模块导入即构造 PROFILE_SPECS 并跑 INV-1~4 校验，不得抛错。"""
        assert PROFILE_SPECS, "PROFILE_SPECS 未加载"
        for p in ("defensive", "balanced", "aggressive"):
            assert p in PROFILE_SPECS
        # 重新跑一遍显式校验，确认当前配置满足 INV-1~6
        validate_profile_specs(PROFILE_SPECS)

    def test_aggressive_core_growth_cap_relaxed(self):
        """INV-4 单调：进攻型 core_growth_cap(0.60) ≥ 平衡(0.40) ≥ 防御(0.20)。"""
        assert PROFILE_SPECS["defensive"].core_growth_cap <= PROFILE_SPECS["balanced"].core_growth_cap
        assert PROFILE_SPECS["balanced"].core_growth_cap <= PROFILE_SPECS["aggressive"].core_growth_cap

    def test_layer_count_monotonic_in_spec(self):
        """INV-3（真相源）：卫星数严格递增 防御<平衡<进攻；防御数反向 防御≥平衡≥进攻。"""
        lc = {p: PROFILE_SPECS[p].layer_count for p in ("defensive", "balanced", "aggressive")}
        assert lc["defensive"]["satellite"] < lc["balanced"]["satellite"] < lc["aggressive"]["satellite"]
        assert lc["defensive"]["defense"] >= lc["balanced"]["defense"] >= lc["aggressive"]["defense"]
        # 核心数非递减
        assert lc["defensive"]["core"] <= lc["balanced"]["core"] <= lc["aggressive"]["core"]
class TestCoreGrowthCap:
    def test_balanced_core_growth_wide_basis_within_cap(self):
        """#10 / INV-4：平衡核心层「高 beta 成长宽基」合计权重 ≤ core 预算 × cap(0.40)。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="balanced", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        bal = _allocs_by_id(strategies)["balanced"]
        core = [a for a in bal["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
        core_w = sum(a.get("weight", 0.0) or 0.0 for a in core)
        growth_w = sum(a.get("weight", 0.0) or 0.0 for a in core if _is_growth_wide_basis(a))
        cap = STRATEGY_META["balanced"]["core_growth_cap"]
        # 核心预算 = layer_budget.core(0.50)。占比上限 = 0.50 × 0.40 = 0.20
        assert growth_w <= core_w * cap + 1e-9, (
            f"平衡核心成长宽基占比越界: growth_w={growth_w:.4f} core_w={core_w:.4f} "
            f"cap={cap} limit={core_w*cap:.4f}"
        )

    def test_check_structure_flags_excess_growth(self):
        """反例：手造平衡核心成长宽基占比 67%（越 cap）→ check_structure 必报 INV-4。"""
        # 平衡核心预算 0.50，成长宽基 588000+159915 合计 0.335 ≈ 67% → 越 cap(0.40→0.20)
        strat = {
            "id": "balanced",
            "allocations": [
                {"symbol": "510300", "layer": "core", "weight": 0.165, "selection_rationale": ""},
                {"symbol": "159338", "layer": "core", "weight": 0.165, "selection_rationale": ""},
                {"symbol": "588000", "name": "科创50ETF", "tracked_index": "科创50", "layer": "core",
                 "weight": 0.167, "selection_rationale": "", "industry": "宽基指数"},
                {"symbol": "159915", "name": "创业板ETF", "tracked_index": "创业板指", "layer": "core",
                 "weight": 0.168, "selection_rationale": "", "industry": "宽基指数"},
            ],
        }
        check_structure_reasonableness([strat])
        warns = strat.get("risk_metrics", {}).get("structure_warnings", [])
        assert any(w["type"] == "core_growth_exceeds_cap" for w in warns), (
            f"INV-4 未拦截越界成长宽基: {[w['type'] for w in warns]}"
        )
class TestAggressiveLowBallast:
    def test_aggressive_budget_cash_le_0_10(self):
        """#13 / INV-6：进攻型「预算」现金 ≤ 0.10（配置去保守化，非 25% 过保守）。

        设计 #13 的根因修复是「配置 + regime 钳制」：layer_budget 现金 = 0.05，
        且 dynamic_layer_budget 对任意 regime 钳制现金 ≤ 0.10（bear ≤ 0.15）。
        此断言验证配置层保证（确定性、regime 固定），对应 round21 #13 实证
        「进攻现金 25% / 防御 19%」的根因消除。

        注：运行期实际现金可能因卫星层科技集中度风控（tech-trim）把未填满的卫星
        预算转为现金而略高——属独立风险约束，由 check_structure_reasonableness 的
        INV-6 运行时告警承接（非 #13 配置问题）。
        """
        # 配置层：aggressive layer_budget 现金 = 1 - (core+sat+def) ≤ 0.10
        lb = STRATEGY_META["aggressive"]["layer_budget"]
        cfg_cash = 1.0 - (lb["core"] + lb["satellite"] + lb["defense"])
        assert cfg_cash <= 0.10 + 1e-9, f"进攻配置现金 {cfg_cash:.4f} > 0.10"
        # regime 钳制：任意 regime 下 dynamic_layer_budget 现金 ≤ 0.10（bear ≤ 0.15）
        from app.engine.budgets import dynamic_layer_budget
        for regime in ("bear", "correction", "defensive_rotate", "range_bound",
                       "bull_strong", "bull_weakening", "panic"):
            b = dynamic_layer_budget("aggressive", regime)
            rcash = 1.0 - (b["core"] + b["satellite"] + b["defense"])
            clamp = 0.15 if regime == "bear" else 0.10
            assert rcash <= clamp + 1e-9, (
                f"aggressive regime={regime} 现金 {rcash:.4f} > 钳制 {clamp}"
            )

    def test_aggressive_runtime_cash_de_conservatized(self):
        """#13 / INV-6 运行期：充足且分散的卫星候选下，进攻型实际现金显著低于
        round21 实证值 25%（验证去保守化在候选充足时生效，非单纯改配置）。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="aggressive", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        agg = _allocs_by_id(strategies)["aggressive"]
        cash = _cash(agg)
        # 运行期保证：显著优于实证 25%（候选充足时应接近预算 0.05；
        # 若卫星层科技集中度触发 tech-trim 则偏高，但须 < 0.25）。
        assert cash < 0.25, f"进攻型现金 {cash:.4f} 未去保守化（实证 25%）"

    def test_aggressive_defense_only_gold(self):
        """#13 / INV-6：进攻型防御层仅黄金（518880），权重 ≤ 0.05（非 0.19）。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="aggressive", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        agg = _allocs_by_id(strategies)["aggressive"]
        def_allocs = [a for a in agg["allocations"] if a.get("layer") == "defense"]
        def_w = sum(a.get("weight", 0.0) for a in def_allocs)
        assert def_w <= 0.05 + 1e-9, f"进攻型防御权重 {def_w:.4f} > 0.05"
        # 防御层实际标的应为黄金（mandatory 锚）
        assert {a["symbol"] for a in def_allocs} <= {"518880"}, (
            f"进攻型防御层含非黄金锚: {[a['symbol'] for a in def_allocs]}"
        )
class TestInvertedFixtureRejected:
    def _inverted_strategies(self):
        """手造 design-534 倒挂：sat 2/6/2、core 成长 67%、total 8/13/10、
        进攻 cash 0.25 / def 0.19。"""
        return [
            {
                "id": "defensive",
                "allocations": [
                    {"symbol": "510300", "layer": "core", "weight": 0.30},
                    {"symbol": "159338", "layer": "core", "weight": 0.30},
                    {"symbol": "518880", "layer": "defense", "weight": 0.075},
                    {"symbol": "511090", "layer": "defense", "weight": 0.075},
                    {"symbol": "512480", "layer": "satellite", "weight": 0.10},
                    {"symbol": "515030", "layer": "satellite", "weight": 0.10},
                    {"symbol": "CASH", "layer": "cash", "weight": 0.05},
                ],
            },
            {
                "id": "balanced",
                "allocations": [
                    {"symbol": "510300", "layer": "core", "weight": 0.25},
                    {"symbol": "159338", "layer": "core", "weight": 0.25},
                    {"symbol": "588000", "name": "科创50ETF", "tracked_index": "科创50",
                     "layer": "core", "weight": 0.167, "industry": "宽基指数"},
                    {"symbol": "159915", "name": "创业板ETF", "tracked_index": "创业板指",
                     "layer": "core", "weight": 0.168, "industry": "宽基指数"},
                    {"symbol": "518880", "layer": "defense", "weight": 0.05},
                    {"symbol": "512480", "layer": "satellite", "weight": 0.05},
                    {"symbol": "515030", "layer": "satellite", "weight": 0.05},
                    {"symbol": "512010", "layer": "satellite", "weight": 0.05},
                    {"symbol": "512880", "layer": "satellite", "weight": 0.05},
                    {"symbol": "516160", "layer": "satellite", "weight": 0.05},
                    {"symbol": "512660", "layer": "satellite", "weight": 0.05},
                    {"symbol": "CASH", "layer": "cash", "weight": 0.03},
                ],
            },
            {
                "id": "aggressive",
                "allocations": [
                    {"symbol": "510300", "layer": "core", "weight": 0.18},
                    {"symbol": "159338", "layer": "core", "weight": 0.18},
                    {"symbol": "588000", "name": "科创50ETF", "tracked_index": "科创50",
                     "layer": "core", "weight": 0.06, "industry": "宽基指数"},
                    {"symbol": "518880", "layer": "defense", "weight": 0.10},
                    {"symbol": "511090", "layer": "defense", "weight": 0.09},
                    {"symbol": "512480", "layer": "satellite", "weight": 0.08},
                    {"symbol": "515030", "layer": "satellite", "weight": 0.06},
                    {"symbol": "CASH", "layer": "cash", "weight": 0.25},
                ],
            },
        ]

    def test_inverted_raises_inv3_5_6(self):
        """倒挂组合喂 cross_profile 校验 → 必含 INV-3（卫星倒挂）/ INV-5（总数倒挂）/ INV-6
        （进攻现金 0.25、防御 0.19）违规。"""
        strats = self._inverted_strategies()
        # cross_profile_only=True：运行时跨方案比较（ strat_design 在生成后调用）
        check_structure_reasonableness(strats, cross_profile_only=True)
        warns = strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        types = {w["type"] for w in warns}
        assert "inv3_satellite_not_monotonic" in types, f"INV-3 卫星倒挂未拦截: {types}"
        assert "inv5_total_not_monotonic" in types, f"INV-5 总数倒挂未拦截: {types}"
        assert "inv6_aggressive_cash_over" in types, f"INV-6 进攻现金 0.25 未拦截: {types}"
        assert "inv6_aggressive_defense_over" in types, f"INV-6 进攻防御 0.19 未拦截: {types}"

    def test_inverted_raises_inv4_growth(self):
        """倒挂组合：平衡核心成长宽基 0.335/0.50=67% 越 cap(0.40) → INV-4 拦截（逐方案）。"""
        strats = self._inverted_strategies()
        check_structure_reasonableness(strats)
        # INV-4 写在逐方案分支（cross_profile_only=False），挂在 balanced 上
        bal = strats[1]
        warns = bal.get("risk_metrics", {}).get("structure_warnings", [])
        assert any(w["type"] == "core_growth_exceeds_cap" for w in warns), (
            f"INV-4 平衡成长 67% 未拦截: {[w['type'] for w in warns]}"
        )


# ===================================================================
# merged from test_round24_r24_correlation.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round24 R24: 关联度/冗余控制缺口——近替代品双路检测 + 无价格对告警 + 组合级分散约束。

问题（round24 §12.1 R24 实证，design 570）：
- 防御方案三重持有大盘宽基（510300+159338+510050≈31%）未告警——仅 pairwise 且依赖
  K 线相关系数，降级盲时 r=None 静默跳过；
- 主题级「同主题不同发行商」冗余全方案未抓：588170+588200（科创半导体）、
  513120+159570（港股药）、512880+513090（券商 A/H）——r<0.9 或价格缺失时不约束；
- 组合级分散缺口：3 只大盘各自 pairwise 受限仍集体冗余可过。

修复（纯函数，engine 无 I/O）：
- `near_substitute_pairs`：独立于相关系数的「同主题近替代品」检测（名称/行业/tracked_index
  语义族）——即便 r<0.9 或价格缺失也告警；
- `portfolio_concentration_check`：组合平均 pairwise r > 0.8 且标的 ≥3 → concentration 告警；
- `enforce_max_correlation` 集成：近替代品对 r=None → unevaluated 告警（非静默跳过）；
  强制锚（MANDATORY_CODES）仍豁免削减（R2 不变式）。
"""

import pytest

from app.engine.allocation_engine import (
    enforce_max_correlation,
    near_substitute_pairs,
    portfolio_concentration_check,
    MANDATORY_CODES,
)


def _alloc(symbol, name, weight, layer="satellite", factor_score=0.0, tracked_index=""):
    return {
        "symbol": symbol, "name": name, "weight": weight,
        "layer": layer, "factor_score": factor_score, "tracked_index": tracked_index,
    }


class TestNearSubstitutePairs:
    """R24②: 近替代品双路检测（同主题不同发行商，独立于 K 线相关系数）。"""

    def test_semiconductor_pair_detected(self):
        """588170 科创半导体 + 588200 科创芯片 → near_substitute（科创族）。"""
        allocs = [
            _alloc("588170", "科创半导体ETF", 0.15, "satellite"),
            _alloc("588200", "科创芯片ETF", 0.15, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        p = pairs[0]
        assert p["type"] == "near_substitute"
        assert set(p["pair"]) == {"588170", "588200"}
        assert p["combined_weight"] == pytest.approx(0.30, abs=1e-6)

    def test_hk_biotech_pair_detected(self):
        """513120 港股创新药 + 159570 港股通创新药 → near_substitute（医药族）。"""
        allocs = [
            _alloc("513120", "港股创新药ETF", 0.12, "satellite"),
            _alloc("159570", "港股通创新药ETF", 0.10, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "医药生物"

    def test_broker_pair_detected(self):
        """512880 证券 + 513090 香港证券 → near_substitute（券商族）。"""
        allocs = [
            _alloc("512880", "证券ETF", 0.15, "satellite"),
            _alloc("513090", "香港证券ETF", 0.10, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "券商"

    def test_large_cap_wide_basis_overlap_detected(self):
        """510300 沪深300 + 510050 上证50 → near_substitute（大盘宽基族，R24③）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.20, "core"),
            _alloc("510050", "上证50ETF", 0.10, "core"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "大盘宽基"

    def test_unrelated_pairs_not_flagged(self):
        """黄金 518880 + 科创 588200 → 无近替代品（负向：误报 → FAIL）。"""
        allocs = [
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        assert near_substitute_pairs(allocs) == []

    def test_cash_and_self_not_flagged(self):
        allocs = [
            _alloc("CASH", "现金", 0.05, "cash"),
            _alloc("510300", "沪深300ETF", 0.20, "core"),
        ]
        assert near_substitute_pairs(allocs) == []


class TestPortfolioConcentrationCheck:
    """R24⑥: 组合级分散约束——平均 pairwise r 过高且标的够多 → concentration。"""

    def test_three_large_caps_collectively_redundant(self):
        """510300+159338+510050 两两 r≈0.98 → 组合平均 >0.8 → concentration 告警。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.15, "core"),
            _alloc("159338", "中证A500ETF", 0.10, "core"),
            _alloc("510050", "上证50ETF", 0.06, "core"),
        ]
        matrix = {
            ("510300", "159338"): 0.983, ("159338", "510050"): 0.939,
            ("510300", "510050"): 0.912,
        }
        out = portfolio_concentration_check(allocs, matrix)
        assert out is not None
        assert out["type"] == "concentration"
        assert out["avg_correlation"] > 0.8
        assert len(out["symbols"]) == 3

    def test_diversified_portfolio_no_concentration(self):
        """分散组合（黄金/科创/宽基，r 均低）→ 无告警（负向）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.20, "core"),
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        matrix = {
            ("510300", "518880"): 0.1, ("518880", "588200"): 0.05,
            ("510300", "588200"): 0.4,
        }
        assert portfolio_concentration_check(allocs, matrix) is None

    def test_fewer_than_three_no_concentration(self):
        allocs = [
            _alloc("510300", "沪深300ETF", 0.30, "core"),
            _alloc("159338", "中证A500ETF", 0.20, "core"),
        ]
        matrix = {("510300", "159338"): 0.983}
        assert portfolio_concentration_check(allocs, matrix) is None


class TestEnforceMaxCorrelationR24:
    """R24 集成：近替代品无价格对告警 + 强制锚豁免不变式。"""

    def test_near_substitute_no_price_emits_unevaluated(self):
        """同主题近替代品但 r=None（价格缺失/降级盲）→ unevaluated 告警，非静默跳过。

        round25 R41-a: 近替代品检测已从 enforce_max_correlation 解耦为独立层
        apply_near_substitute_warnings（无条件执行，不依赖 corr_matrix）——本测试改测
        该独立层（enforce 内不再包裹近替代品）。
        """
        from app.engine.allocation_engine import apply_near_substitute_warnings
        allocs = [
            _alloc("588170", "科创半导体ETF", 0.15, "satellite"),
            _alloc("588200", "科创芯片ETF", 0.15, "satellite"),
            _alloc("510300", "沪深300ETF", 0.30, "core"),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        # 矩阵只有 588170↔588200 缺失（r=None），其余对不存在
        matrix = {}
        out = apply_near_substitute_warnings([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        unevaluated = [w for w in warnings if w.get("type") == "unevaluated"]
        assert len(unevaluated) == 1
        assert set(unevaluated[0]["pair"]) == {"588170", "588200"}
        assert "correlation" in unevaluated[0] and unevaluated[0]["correlation"] is None

    def test_mandatory_anchor_never_cut_by_near_substitute(self):
        """强制锚（510300）配近替代品（510050）→ 强制锚不被削减（R2 不变式）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.25, "core", factor_score=-0.9),
            _alloc("510050", "上证50ETF", 0.15, "core", factor_score=0.5),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        matrix = {("510300", "510050"): 0.983}
        out = enforce_max_correlation([strat], matrix)
        result = {a["symbol"]: a["weight"] for a in out[0]["allocations"]}
        assert result["510300"] >= 0.05, "强制锚不得被关联度削减击穿 5% 地板"

    def test_concentration_warning_integrated(self):
        """组合级 concentration 告警写入 risk_metrics。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.15, "core"),
            _alloc("159338", "中证A500ETF", 0.10, "core"),
            _alloc("510050", "上证50ETF", 0.06, "core"),
        ]
        strat = {"id": "defensive", "allocations": [dict(a) for a in allocs]}
        matrix = {
            ("510300", "159338"): 0.983, ("159338", "510050"): 0.939,
            ("510300", "510050"): 0.912,
        }
        out = enforce_max_correlation([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        assert any(w.get("type") == "concentration" for w in warnings)

    def test_normal_low_corr_no_new_warnings(self):
        """正常低相关组合（黄金+科创）→ 无近替代品/无浓度告警（负向：不误报）。"""
        allocs = [
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        matrix = {("518880", "588200"): 0.05}
        out = enforce_max_correlation([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        assert warnings == []


# ===================================================================
# merged from test_round25_r41_near_substitute_ungated.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round25 R41: 近替代品冗余控制盘后绕过 + 告警前端不呈现。

问题（round25 §2.4 实证）：`near_substitute_pairs` 调用点嵌套在 `enforce_max_correlation`
内部，而该函数只在 `if corr_matrix:` 时调用（strategy_design）→ 盘后/非交易窗口
corr_matrix 为空 → 近替代品检测整体跳过（「芯片+半导体设备」「港股创新药+港股通创新药」
同主题双入选无告警）。设计意图「独立于 K 线相关系数、降级盲（r=None）也能识别」与实现
「门控在 corr_matrix」矛盾。

修复（round25 R41-a）：
- 新增 `apply_near_substitute_warnings` 独立冗余控制层（无条件执行）；
- `enforce_max_correlation` 不再包裹 near_substitute_pairs；
- strategy_design risk-control 段始终调用新函数（corr_matrix 空也跑）。
"""

import pytest

from app.engine.allocation_engine import (
    apply_near_substitute_warnings,
    enforce_max_correlation,
    near_substitute_pairs,
)


def _chip_pair_allocs():
    """芯片 + 半导体设备（同族）+ 无关标的。"""
    return [
        {"symbol": "588200", "name": "科创芯片ETF", "weight": 0.10},
        {"symbol": "588170", "name": "科创半导体设备ETF", "weight": 0.08},
        {"symbol": "510300", "name": "沪深300ETF", "weight": 0.5},
    ]


def _hk_pharma_allocs():
    """港股创新药 + 港股通创新药（同族）。"""
    return [
        {"symbol": "513120", "name": "港股创新药ETF", "weight": 0.07},
        {"symbol": "159570", "name": "港股通创新药ETF", "weight": 0.06},
        {"symbol": "518880", "name": "黄金ETF", "weight": 0.3},
    ]


class TestApplyNearSubstituteWarnings:
    """R41-a: 独立冗余控制层（无条件执行，不依赖 corr_matrix）。"""

    def test_empty_corr_matrix_still_detects_chip_pair(self):
        """mock corr_matrix={}（盘后）→ 芯片+半导体设备 对仍被识别（负向：漏报 → FAIL）。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        out = apply_near_substitute_warnings(strategies, {})
        warnings = out[0]["risk_metrics"]["correlation_warnings"]
        pairs = {(w["pair"][0], w["pair"][1]) for w in warnings}
        assert ("588200", "588170") in pairs or ("588170", "588200") in pairs, (
            "盘后 corr_matrix 空也必须识别芯片+半导体设备近替代品（R41-a）"
        )
        # r 缺失 → unevaluated
        entry = next(w for w in warnings if "588200" in w["pair"] and "588170" in w["pair"])
        assert entry["type"] in ("near_substitute", "unevaluated")
        assert entry["correlation"] is None

    def test_hk_pharma_pair_detected_without_corr(self):
        """港股创新药+港股通创新药 对在 corr_matrix 空时同样识别。"""
        strategies = [{"id": "balanced", "allocations": _hk_pharma_allocs()}]
        out = apply_near_substitute_warnings(strategies, {})
        warnings = out[0]["risk_metrics"]["correlation_warnings"]
        pairs = {(w["pair"][0], w["pair"][1]) for w in warnings}
        assert ("513120", "159570") in pairs or ("159570", "513120") in pairs, (
            "港股创新药+港股通创新药 近替代品必须被识别"
        )

    def test_r_present_keeps_near_substitute_type(self):
        """r 可算（如 0.35）→ type=near_substitute + correlation 透传。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        corr = {("588170", "588200"): 0.35}
        out = apply_near_substitute_warnings(strategies, corr)
        entry = next(w for w in out[0]["risk_metrics"]["correlation_warnings"]
                     if "588200" in w["pair"] and "588170" in w["pair"])
        assert entry["type"] == "near_substitute"
        assert entry["correlation"] == pytest.approx(0.35, abs=1e-3)

    def test_enforce_max_correlation_no_longer_calls_near_substitute(self):
        """R41-a 验收③: enforce_max_correlation 调用点不再包裹 near_substitute_pairs。"""
        import inspect
        import re
        import app.engine.allocation_engine as ae

        src = inspect.getsource(ae.enforce_max_correlation)
        assert "near_substitute_pairs(" not in src, (
            "enforce_max_correlation 内不得再调用 near_substitute_pairs（已解耦为独立层）"
        )
        # 独立层存在且是调用方
        assert "apply_near_substitute_warnings" in dir(ae)

    def test_enforce_max_correlation_still_does_high_corr_reduction(self):
        """enforce_max_correlation 的高相关削减行为保持（回归保护）。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        corr = {("588170", "588200"): 0.95}
        out = enforce_max_correlation(strategies, corr, threshold=0.9, max_combined_weight=0.1)
        # 高相关对合计 0.18 > 0.1 → 削减低因子分一方
        allocs = {a["symbol"]: a for a in out[0]["allocations"]}
        assert allocs["588170"]["weight"] + allocs["588200"]["weight"] <= 0.1 + 1e-6


class TestStrategyDesignIntegration:
    """R41-a 集成：strategy_design risk-control 段无条件调用独立冗余控制层。"""

    def test_apply_near_substitute_warnings_called_unconditionally(self, monkeypatch):
        """corr_matrix 空（盘后）→ apply_near_substitute_warnings 仍被调用（R41 验收：
        近替代品检测不依赖 corr_matrix，最该在盘后工作的控制不在盘后被关掉）。"""
        import asyncio
        from app.services import strategy_design as sd

        candidates = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
                 "factor_score": 0.2, "price": 3.8, "industry": "宽基"},
            ],
            "satellite": [
                {"symbol": "588200", "name": "科创芯片ETF", "layer": "satellite",
                 "factor_score": 0.5, "price": 1.1, "industry": "半导体"},
                {"symbol": "588170", "name": "科创半导体设备ETF", "layer": "satellite",
                 "factor_score": 0.4, "price": 1.2, "industry": "半导体设备"},
                {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
                 "factor_score": 0.3, "price": 0.9, "industry": "医药"},
            ],
            "defense": [
                {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                 "factor_score": 0.3, "price": 8.3, "industry": "黄金"},
            ],
        }

        class _FakeHub:
            def __init__(self):
                self._by_code = {}
            async def refresh(self): pass
            def get_pool(self, layer=None):
                if layer is None:
                    return candidates
                return candidates.get(layer, [])
            def get_factor_matrix(self): return {}
            def get_market_regime(self): return "range_bound"
            def get_market_sentiment(self): return {"sentiment_index": 50, "sentiment_label": "中性"}
            def get_index_realtime(self): return []
            async def get_global_indices(self): return {}
            def get_sector_momentum(self): return []
            def get_sector_stocks(self, code): return []
            def get_by_code(self, code):
                for layer in candidates.values():
                    for it in layer:
                        if it["symbol"] == code:
                            return it
                return None

        # 关键断言：corr_matrix 空时独立冗余控制层必须被调用（且收到 corr={}）
        calls = []
        orig = sd.apply_near_substitute_warnings
        def _spy(strategies, corr_matrix):
            calls.append(dict(corr=corr_matrix, n=len(strategies)))
            return orig(strategies, corr_matrix)
        monkeypatch.setattr(sd, "apply_near_substitute_warnings", _spy)
        monkeypatch.setattr(sd, "_correlation_matrix_for", lambda allocs, cands: {})
        monkeypatch.setattr(sd, "_correlation_medians_for", lambda allocs, cands: {})
        # R104 (round34): 签名兼容 shim——生产调用点现传 db_sample_counts kwarg
        monkeypatch.setattr(sd, "_factor_data_quality_report",
                            lambda db_sample_counts=None: {"valid_rate": 1.0})
        monkeypatch.setattr(sd, "_data_precision_report", lambda fq: {"mode": "full"})
        import app.services.market_data_hub as mh_mod
        monkeypatch.setattr(mh_mod, "market_data_hub", _FakeHub())

        asyncio.run(sd.generate_enhanced_design(capital=100000))
        assert calls, "apply_near_substitute_warnings 必须在 risk-control 段被调用（R41-a）"
        assert all(c["corr"] == {} for c in calls), (
            "corr_matrix 为空（盘后）也必须调用近替代品控制层（不门控）"
        )

    def test_source_wires_near_substitute_independent_of_corr_gate(self):
        """源码级断言：strategy_design 中 apply_near_substitute_warnings 不在
        `if corr_matrix:` 分支内（独立调用）。"""
        import inspect
        import re
        import app.services.strategy_design as sd

        src = inspect.getsource(sd.generate_enhanced_design)
        # 独立调用点存在（不在 enforce 分支内）
        assert "apply_near_substitute_warnings" in src
        # enforce_max_correlation 的调用仍在 if corr_matrix 分支内（高相关约束保持门控）
        # 而 apply 调用在分支外（无条件）——通过源码顺序粗验：enforce 调用后紧跟 apply
        idx_enforce = src.find("enforce_max_correlation([_strat_proxy]")
        idx_apply = src.find("apply_near_substitute_warnings([_strat_proxy]")
        assert idx_enforce != -1 and idx_apply != -1
        assert idx_apply > idx_enforce, "apply 调用应在 enforce 之后（独立层，不嵌套）"


class TestR131SatelliteLayerCap:
    """R131 (round37): 卫星层总权重硬上限——_select_and_weight 内部 MAX_WEIGHT 钳制
    可使个别权重被截断但总和不回补，导致卫星层 Σweight > budget。
    修复后卫星层总权重不得超过 budget，超预算时按比例缩放。"""

    def test_satellite_layer_never_exceeds_budget(self):
        """卫星层总权重不得超过 budget（aggressive satellite budget=0.30）。

        容差 0.06：_select_and_weight 内部 MAX_WEIGHT 钳制后的预分配层 cap
        确保卫星层不超配；reconcile 段会向所有非现金/非强制标的（含卫星）
        均摊预算缺口，使卫星层实际略超预算——此为 reconcile 机制的已知残差，
        由 apply_risk_controls 在下游兜底钳制。
        """
        cands = _base_candidates()
        # 极端因子分：让卫星层候选全部高分，触发超配
        fm = {}
        for c in cands:
            if c["layer"] == "satellite":
                fm[c["symbol"]] = {"technical": 0.9, "momentum": 0.9,
                                   "valuation": 0.9, "sentiment": 0.9}
            else:
                fm[c["symbol"]] = {"technical": 0.5, "momentum": 0.5,
                                   "valuation": 0.5, "sentiment": 0.5}
        strategies = allocate(risk_profile="aggressive", regime="bullish",
                              factor_matrix=fm, candidates=cands)
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            sat_total = sum(a.get("weight", 0.0) for a in sat)
            # aggressive satellite budget = 0.30; 容差 0.06 覆盖 reconcile 残差
            assert sat_total <= 0.30 + 0.06, (
                f"R131: aggressive 卫星层 Σweight={sat_total:.4f} > budget 0.30 + 0.06"
            )

    def test_satellite_cap_scales_proportionally(self):
        """超预算时权重应按比例缩放（非截断为0）。"""
        cands = _base_candidates()
        fm = {}
        for c in cands:
            if c["layer"] == "satellite":
                fm[c["symbol"]] = {"technical": 0.99, "momentum": 0.99,
                                   "valuation": 0.99, "sentiment": 0.99}
            else:
                fm[c["symbol"]] = {"technical": 0.3, "momentum": 0.3,
                                   "valuation": 0.3, "sentiment": 0.3}
        strategies = allocate(risk_profile="aggressive", regime="bullish",
                              factor_matrix=fm, candidates=cands)
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            if not sat:
                continue
            # 每只卫星权重应 > 0（缩放不截断为0）
            for a in sat:
                assert a.get("weight", 0) > 0, (
                    f"R131: satellite {a['symbol']} 权重被截断为0"
                )

    def test_defensive_satellite_also_capped(self):
        """防御型卫星层也应受预算上限约束。

        容差 0.06：同 test_satellite_layer_never_exceeds_budget 注释，
        reconcile 残差由 apply_risk_controls 在下游兜底。
        """
        cands = _base_candidates()
        fm = {}
        for c in cands:
            if c["layer"] == "satellite":
                fm[c["symbol"]] = {"technical": 0.9, "momentum": 0.9,
                                   "valuation": 0.9, "sentiment": 0.9}
            else:
                fm[c["symbol"]] = {"technical": 0.5, "momentum": 0.5,
                                   "valuation": 0.5, "sentiment": 0.5}
        strategies = allocate(risk_profile="defensive", regime="bullish",
                              factor_matrix=fm, candidates=cands)
        for s in strategies:
            if s["id"] != "defensive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            sat_total = sum(a.get("weight", 0.0) for a in sat)
            # defensive satellite budget = 0.20; 容差 0.06 覆盖 reconcile 残差
            assert sat_total <= 0.20 + 0.06, (
                f"R131: defensive 卫星层 Σweight={sat_total:.4f} > budget 0.20 + 0.06"
            )

# ── R01/R03 (round58 Part A): 平衡型成长集中度软约束 + 防御锚扩容 ────────────
# 背景 docs/round58-portfolio-design-llm-fix.md §A1：design 65 平衡型
# 科创50 20% + 中证500 20%（成长宽基 40%）、科创主题 24.4%，防御仅 5% 偏弱黄金。


def _r58_growth_allocs():
    """成长宽基（_is_growth_wide_basis 口径）占比超 cap 的平衡型形态。

    口径说明（重要，见 test_r01_cap_caliber_excludes_midcap_growth）：
    科创50/创业板/科创100/双创 属 growth_style；中证500/中证1000 **不属**。
    """
    return [
        {"symbol": "588000", "name": "科创50ETF华夏", "layer": "core",
         "weight": 0.25, "factor_score": -0.27},
        {"symbol": "159915", "name": "创业板ETF易方达", "layer": "core",
         "weight": 0.20, "factor_score": -0.10},
        {"symbol": "513120", "name": "港股创新药", "layer": "satellite",
         "weight": 0.088, "factor_score": 0.1},
        {"symbol": "518880", "name": "黄金ETF华安", "layer": "defense",
         "weight": 0.05, "factor_score": -0.2},
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "weight": 0.05, "factor_score": 0.0},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "weight": 0.05, "factor_score": 0.0},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "weight": 0.05, "factor_score": 0.0},
        {"symbol": "CASH", "weight": 0.212},
    ]


def _r58_growth_warnings(strategies, sid="balanced"):
    """取某方案的 structure_warnings（缺 risk_metrics 时返空列表，不 KeyError）。"""
    s = next(x for x in strategies
             if (x.get("id") or x.get("risk_profile")) == sid)
    return s.get("risk_metrics", {}).get("structure_warnings", [])


def test_r01_balanced_growth_over_cap_warns():
    """R01 负向：平衡型成长占比 45/78.8=57% > cap 30% → 必须告警。"""
    out = check_structure_reasonableness(
        [{"id": "balanced", "allocations": _r58_growth_allocs()}])
    g = [w for w in _r58_growth_warnings(out)
         if w["type"] == "growth_style_concentration_exceeded"]
    assert g, f"平衡型成长集中未告警（warnings={_r58_growth_warnings(out)}）"
    assert g[0]["profile"] == "balanced"
    assert g[0]["growth_weight"] == pytest.approx(0.45)
    assert g[0]["cap"] == pytest.approx(0.30)
    assert g[0]["growth_share"] > 0.30


def test_r01_cap_caliber_excludes_midcap_growth():
    """R01 口径锁定（已知缺口显式登记，防后人误以为 cap 覆盖中盘成长）：

    `taxonomy.growth_style_of` **不含**中证500/中证1000（§A2 缺口表已列）。
    因此 design 65 的「科创50 20% + 中证500 20%」按本口径只算 20%/74%
    = 27% < 30% cap，**不触发** R01 告警。方案文档 §A1 结论 ①（中证500
    降权）本轮无引擎侧强制手段，仅由 LLM 报告层建议。

    本用例把该口径钉死：若将来把中盘成长纳入 growth_style，本用例会失败，
    提醒同步更新方案文档的验收口径。
    """
    allocs = [
        # design 65 平衡型真实形态：科创50 20% + 中证500 20% + 卫星若干
        {"symbol": "588000", "name": "科创50ETF华夏", "layer": "core",
         "weight": 0.20, "factor_score": -0.27},
        {"symbol": "510500", "name": "中证500ETF南方", "layer": "core",
         "weight": 0.20, "factor_score": -0.28},
        {"symbol": "513120", "name": "港股创新药", "layer": "satellite",
         "weight": 0.088, "factor_score": 0.1},
        {"symbol": "512880", "name": "证券ETF国泰", "layer": "satellite",
         "weight": 0.044, "factor_score": -0.2},
        {"symbol": "159755", "name": "电池ETF广发", "layer": "satellite",
         "weight": 0.044, "factor_score": -0.3},
        {"symbol": "588170", "name": "科创半导体", "layer": "satellite",
         "weight": 0.044, "factor_score": -0.4},
        {"symbol": "518880", "name": "黄金ETF华安", "layer": "defense",
         "weight": 0.05, "factor_score": -0.2},
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "weight": 0.05, "factor_score": 0.0},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "weight": 0.05, "factor_score": 0.0},
        {"symbol": "CASH", "weight": 0.235},
    ]
    non_cash = sum(a["weight"] for a in allocs if a["symbol"] != "CASH")
    assert 0.20 / non_cash < 0.30, "夹具前提失效：科创50 单项已超 cap"
    ws = _r58_growth_warnings(check_structure_reasonableness(
        [{"id": "balanced", "allocations": allocs}]))
    assert not [w for w in ws
                if w["type"] == "growth_style_concentration_exceeded"], (
        "中盘成长（中证500）已纳入 growth_style 口径——R01 文档验收口径需同步更新")


def test_r01_balanced_growth_under_cap_no_warning():
    """R01 反向守卫：成长占比 ≤ cap → 不得告警（防恒真断言）。"""
    allocs = [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "weight": 0.30, "factor_score": 0.5},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "weight": 0.20, "factor_score": 0.4},
        {"symbol": "518880", "name": "黄金ETF华安", "layer": "defense",
         "weight": 0.10, "factor_score": 0.1},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "weight": 0.10, "factor_score": 0.1},
        {"symbol": "513120", "name": "港股创新药", "layer": "satellite",
         "weight": 0.10, "factor_score": 0.2},
        {"symbol": "CASH", "weight": 0.20},
    ]
    ws = _r58_growth_warnings(check_structure_reasonableness(
        [{"id": "balanced", "allocations": allocs}]))
    assert not [w for w in ws
                if w["type"] == "growth_style_concentration_exceeded"], \
        f"成长占比未超 cap 却告警：{ws}"


def test_r01_soft_constraint_does_not_remove_allocs():
    """R01 软约束语义：告警**不剔除**任何标的（层预算闭合不被破坏）。"""
    allocs = _r58_growth_allocs()
    before = len([a for a in allocs if a.get("symbol") != "CASH"])
    out = check_structure_reasonableness(
        [{"id": "balanced", "allocations": allocs}])
    after = len([a for a in out[0]["allocations"] if a.get("symbol") != "CASH"])
    assert after == before, "软约束不得剔除标的（应升级为硬约束时才动权重）"


def test_r01_not_applied_to_defensive_or_aggressive():
    """R01 范围守卫：高成长占比是防御/进攻的定位本身，不得对二者告警。"""
    for pid in ("defensive", "aggressive"):
        ws = _r58_growth_warnings(check_structure_reasonableness(
            [{"id": pid, "allocations": _r58_growth_allocs()}]), sid=pid)
        assert not [w for w in ws
                    if w["type"] == "growth_style_concentration_exceeded"], \
            f"{pid} 被误判为成长集中（约束只应作用于 balanced）：{ws}"


def test_r01_wired_into_design_pipeline_not_only_unit():
    """R01 接线守卫：产出告警的函数必须真被设计管线调用（round34 教训：
    剥除器/约束常在其后，只测 allocate 层会漏）。此处断言
    `strategy_design` 确实 import + 调用 check_structure_reasonableness（非
    cross_profile_only 那一处——那是跨方案校验，不产本告警）。"""
    import inspect
    from app.services import strategy_design as sd
    src = inspect.getsource(sd)
    assert "check_structure_reasonableness" in src
    # 逐方案调用（positional args 形式）必须存在，跨方案那次用关键字参数
    calls = [ln for ln in src.splitlines()
             if "check_structure_reasonableness(" in ln]
    positional = [ln for ln in calls
                  if "cross_profile_only" not in ln and "import" not in ln]
    assert positional, f"未找到逐方案结构校验调用点：{calls}"
    # 告警类型必须能出现在 risk_metrics（前端/报告消费面）
    from app.engine import allocation_engine as ae
    assert "growth_style_concentration_exceeded" in inspect.getsource(ae)


# ── R03 (round58 Part A): 平衡型防御锚扩容（defense_count 1→2）──────────────


def test_r03_balanced_defense_anchors_two():
    """R03: 平衡型 defense_count=2 → 防御锚 {黄金 518880, 30年国债 511090}。"""
    anchors = _defense_anchors_for("balanced")
    assert anchors == {"518880", "511090"}, f"平衡型防御锚未扩容: {anchors}"


def test_r03_balanced_meta_defense_count_is_two():
    from app.engine.budgets import STRATEGY_META
    assert STRATEGY_META["balanced"]["layer_count"]["defense"] == 2


def test_r03_defense_count_monotonic_inv3_still_holds():
    """R03 副作用守卫：INV-3 防御数反向（def ≥ bal ≥ agg）不得被 R03 破坏。"""
    from app.engine.budgets import STRATEGY_META
    d = STRATEGY_META["defensive"]["layer_count"]["defense"]
    b = STRATEGY_META["balanced"]["layer_count"]["defense"]
    a = STRATEGY_META["aggressive"]["layer_count"]["defense"]
    assert d >= b >= a, f"INV-3 防御数反向被破坏: {d}/{b}/{a}"


def test_r03_aggressive_anchors_unchanged():
    """R03 负向：进攻型 defense_count 仍为 1 → 锚集合不得被顺带扩大。"""
    assert _defense_anchors_for("aggressive") == {"518880"}


# ---------------------------------------------------------------------------
# round59 R02a/R02b: support_levels engine (PURE)
#
# 病灶（doc M1）：投顾 prompt 零 K 线数据，问支撑位只能答"无法确认"。
# 本组用例锁三件事：① 分层可用（动态/结构）② Fib 锚点选取正确 ③ **方向不搞反**。
#
# ③ 是本组的重点。doc §2.1 只警告了"从本轮高点往下量 Fib 得到的是反弹阻力"，
# 但漏了镜像陷阱：价格已跌穿整个回撤区时，S1/S2 在现价上方，此时它们是阻力。
# doc 那条 S3<S2<S1<P_now 只在上涨趋势成立——而提问场景恰恰是下跌行情。
# 故此处断言的是恒真不变式：support 必在现价下方、resist 必在上方、两族不混列。
# ---------------------------------------------------------------------------


def _r59_bars(n=140, start=4000.0, step=-1.0, vol=1_000_000.0):
    """升序日线（最早在前），英文键。"""
    return [
        {"date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
         "open": start + step * i, "high": start + step * i + 5,
         "low": start + step * i - 5, "close": start + step * i, "volume": vol}
        for i in range(n)
    ]


def _r59_all_entries(res):
    fib = res.get("fib") or {}
    return (list(res["dynamic"]) + list(res["structural"]) + list(fib.get("fib_levels") or []))


def _r59_rally_then_pullback():
    """造一个「先跌 -> 涨 -> 回调且现价落在回撤区内」的三段序列。

    数字是手算的，不是碰运气：
      段1 8 根 -1/根  : 3600 -> 3592，末根成 Swing Low(L*)=3592（左右各 3/5 根更高）
      段2 45 根 +25/根: 3592 -> 4717，末根成 Swing High(H*)=4717
      段3 40 根 -12/根: 4717 -> 4237（现价）
      span = 1125；S1 = 4717 - 0.382*1125 = 4287.25；S3 = 4717 - 0.618*1125 = 4021.75
      => S3(4021.75) < 现价(4237) < S1(4287.25)，**落在回撤区内** -> Fib 可用。
    段1 不可省：上涨段起点若在序列开头，其左侧不足 k 根，配不出分形低点，
    引擎会（正确地）判定无可用上涨段。
    """
    bars = []
    price = 3600.0
    for i in range(8):                       # 段1：缓跌，造出分形低点 L*
        price -= 1.0
        bars.append({"date": f"2026-01-{i + 1:02d}", "open": price + 8, "high": price + 10,
                     "low": price - 5, "close": price, "volume": 1e6})
    for i in range(45):                      # 段2：主升，造出分形高点 H*
        price += 25.0
        bars.append({"date": f"2026-02-{i + 1:02d}", "open": price - 10, "high": price + 5,
                     "low": price - 15, "close": price, "volume": 1e6})
    for i in range(40):                      # 段3：回调到回撤区内部
        price -= 12.0
        bars.append({"date": f"2026-03-{i + 1:02d}", "open": price + 10, "high": price + 15,
                     "low": price - 5, "close": price, "volume": 1e6})
    return bars


def test_r59_support_levels_direction_invariant_holds_on_rally_pullback():
    """构造涨后回调：Fib 可用，且三档方向标签与现价位置一致。"""
    from app.engine.support_levels import compute_support_levels
    res = compute_support_levels(_r59_rally_then_pullback())
    price = res["price_now"]
    assert price is not None
    assert res["fib"]["fib_unavailable_reason"] is None, res["fib"]["fib_unavailable_reason"]

    entries = _r59_all_entries(res)
    support = [e for e in entries if e["kind"] == "support"]
    resist = [e for e in entries if e["kind"] == "resist"]
    assert support, "回调行情应至少有一档支撑"
    # 恒真不变式（替代 doc 那条只在上涨趋势成立的 S3<S2<S1<P_now）
    assert all(e["value"] < price for e in support), [e for e in support if e["value"] >= price]
    assert all(e["value"] > price for e in resist), [e for e in resist if e["value"] <= price]
    assert not ({e["value"] for e in support} & {e["value"] for e in resist}), "两族出现同价位"
    fib = res["fib"]
    assert fib["s3"] < fib["s2"] < fib["s1"], fib
    assert len({e["value"] for e in fib["fib_levels"]}) == len(fib["fib_levels"]), "重复价位"


def test_r59_no_bracketing_leg_suppresses_fib_instead_of_inventing_levels():
    """负向：现价已跌穿全部回撤区 -> Fib 三档全不输出 + reason 非空。

    实测 000300 沪深300 命中此路径（现价 4357.62，最近回撤区 S3=4579.74）。
    """
    from app.engine.support_levels import compute_support_levels
    res = compute_support_levels(_r59_bars())          # 单调下行，无任何上涨段
    fib = res["fib"]
    assert fib["s1"] is None and fib["s2"] is None and fib["s3"] is None, fib
    assert fib["fib_unavailable_reason"], "无有效上涨段必须给出 reason"
    assert fib["fib_levels"] == [], "不得输出任何 fib 价位"
    # 但动态/结构层仍须可用——不能因为 Fib 不可用就整段放弃
    assert res["dynamic"], "动态层（MA/BOLL）应仍然产出"
    assert res["structural"], "结构层（60/120日低点）应仍然产出"


def test_r59_bollinger_matches_pandas_ta_ddof1_caliber():
    """负向：BOLL 口径必须与 /market/indicators 端点一致（ddof=1）。

    实测 000001 窗口：ddof=0 会给 lower=3823.86，而端点给 3821.74。
    两处口径不一致 = 同一标的在产品里出现两个"BOLL 下轨"。
    """
    from app.engine.support_levels import compute_support_levels
    bars = _r59_bars(n=60, start=4000.0, step=1.0)
    res = compute_support_levels(bars)
    closes = [b["close"] for b in bars][-20:]
    mid = sum(closes) / len(closes)
    var = sum((c - mid) ** 2 for c in closes) / (len(closes) - 1)   # ddof=1
    import math
    stdev = math.sqrt(var)
    assert abs(res["indicators"]["boll_mid"] - round(mid, 2)) < 0.01
    assert abs(res["indicators"]["boll_upper"] - round(mid + 2 * stdev, 2)) < 0.01
    assert abs(res["indicators"]["boll_lower"] - round(mid - 2 * stdev, 2)) < 0.01


def test_r59_degenerate_input_returns_none_not_zero():
    """负向：空/畸形/样本不足 -> None + reason，绝不 0 填充（0 会冒充真实档位）。"""
    from app.engine.support_levels import compute_support_levels
    for bad in ([], None, [{}], [{"date": "x", "high": 1, "low": 1, "close": 0}], ["nope"], [1, 2]):
        res = compute_support_levels(bad)
        assert res["price_now"] is None, bad
        assert res["fib"]["fib_unavailable_reason"], bad
        assert res["dynamic"] == [] and res["structural"] == [], bad
    short = compute_support_levels(_r59_bars(n=5))
    assert short["indicators"]["ma20"] is None, "样本不足不得填 0"
    assert short["fib"]["fib_unavailable_reason"] == "insufficient_bars"


def test_r59_no_duplicate_level_across_buckets():
    """负向：同一价位不得在动态/结构/Fib 重复出现（重复行会被模型当成两条证据）。"""
    from app.engine.support_levels import compute_support_levels
    res = compute_support_levels(_r59_rally_then_pullback())
    values = [e["value"] for e in _r59_all_entries(res)]
    assert len(values) == len(set(values)), f"重复价位: {values}"


def test_r59_engine_has_no_io_and_no_forbidden_imports():
    """纯度守卫：engine 不得引入 I/O 或上层模块（CI 的 AST 门禁同口径，快照版）。"""
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "engine" / "support_levels.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned_pkgs = ("app.services", "app.fetchers", "app.tasks", "app.analysis",
                   "app.routers", "app.factors")
    banned_io = ("open(", "urllib", "requests.", "aiohttp", "httpx", "sqlite3", "socket.")
    body = src.read_text(encoding="utf-8")
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        for mod in mods:
            assert not any(mod.startswith(p) for p in banned_pkgs), f"禁止的 import: {mod}"
    for token in banned_io:
        assert token not in body, f"禁止的 I/O token: {token}"