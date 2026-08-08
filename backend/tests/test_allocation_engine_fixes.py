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
