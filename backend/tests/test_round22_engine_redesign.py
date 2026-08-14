"""
round22 引擎重构（docs/archived/design-portfolio-engine-redesign.md / docs/archived/engine-refactor-spec-round22.md）
验收测试 —— TDD 负向断言（反例能失败，正例断言真实引擎输出）。

设计 §6 口径：所有测试 pin regime="range_bound"（dynamic_layer_budget≈恒等，断言确定）。
覆盖 round21 #10–#14 + round22 INV-3/4/5/6：
- #10 / INV-4: 平衡核心「高 beta 成长宽基」占比 ≤ core_growth_cap(0.40)
- #11 / INV-3: 卫星数 防御 < 平衡 < 进攻（单调，消除倒挂）
- #12 / INV-5: 总标的数 防御 < 平衡 < 进攻（单调）
- #13 / INV-6: 进攻型 现金 ≤0.10 且 防御层权重 ≤0.05（去保守化，仅黄金压舱）
- 反例 fixture：构造 design-534 式倒挂输出喂 check_structure_reasonableness → 必被
  INV-3/4/5/6 拦截（断言返回对应 structure_warning，旧倒挂组合不得静默通过）。

纯函数测试，无 I/O（allocate / check_structure_reasonableness 均为纯函数）。
"""

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


def _factor_matrix(candidates):
    return {
        c["symbol"]: {
            "technical": 0.6,
            "momentum": 0.6,
            "valuation": 0.5,
            "sentiment": 0.5,
            "composite": 0.55,
        }
        for c in candidates
    }


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


def _layer_counts(s):
    allocs = s.get("allocations", [])
    return {
        "core": sum(1 for a in allocs if a.get("layer") == "core" and a.get("symbol") != "CASH"),
        "satellite": sum(1 for a in allocs if a.get("layer") == "satellite" and a.get("symbol") != "CASH"),
        "defense": sum(1 for a in allocs if a.get("layer") == "defense" and a.get("symbol") != "CASH"),
    }


def _total_count(s):
    return sum(1 for a in s.get("allocations", []) if a.get("symbol") != "CASH")


def _cash(s):
    non_cash = sum(a.get("weight", 0.0) for a in s.get("allocations", []) if a.get("symbol") != "CASH")
    return round(1.0 - non_cash, 4)


# ─── Phase 0: ProfileSpec 加载期 INV 校验（fail-fast）────────────────────

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


# ─── #10 / INV-4: 平衡核心成长宽基占比上限 ────────────────────────────

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


# ─── #11 / INV-3: 卫星数单调（消除倒挂）──────────────────────────────

class TestLayerCountMonotonic:
    def test_satellite_count_def_lt_bal_lt_agg(self):
        """#11 / INV-3：卫星数 防御 < 平衡 < 进攻（候选充足时严格单调）。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="all", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        by = _allocs_by_id(strategies)
        sat = {p: _layer_counts(by[p])["satellite"] for p in ("defensive", "balanced", "aggressive")}
        assert sat["defensive"] < sat["balanced"] < sat["aggressive"], (
            f"卫星数未单调: {sat}"
        )

    def test_defense_count_reverse_monotonic(self):
        """#13/INV-3：防御数反向 防御(2) ≥ 平衡(1) = 进攻(1)。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="all", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        by = _allocs_by_id(strategies)
        d = {p: _layer_counts(by[p])["defense"] for p in ("defensive", "balanced", "aggressive")}
        assert d["defensive"] >= d["balanced"] >= d["aggressive"], f"防御数未反向单调: {d}"


# ─── #12 / INV-5: 总标的数单调 ───────────────────────────────────────

class TestTotalInstrumentMonotonic:
    def test_total_count_def_lt_bal_lt_agg(self):
        """#12 / INV-5：总标的数 防御 < 平衡 < 进攻。"""
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="all", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        by = _allocs_by_id(strategies)
        tot = {p: _total_count(by[p]) for p in ("defensive", "balanced", "aggressive")}
        assert tot["defensive"] < tot["balanced"] < tot["aggressive"], (
            f"总标的数未单调: {tot}"
        )
        # 进攻 ≥ 防御（文档 #12 直接要求）
        assert tot["aggressive"] >= tot["defensive"]


# ─── #13 / INV-6: 进攻型去保守化（低压舱）────────────────────────────

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


# ─── 反例 fixture：design-534 式倒挂组合必被 INV-3/4/5/6 拦截 ──────────

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
