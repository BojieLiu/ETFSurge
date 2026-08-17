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
