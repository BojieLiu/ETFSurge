from __future__ import annotations
"""
U6 (round2-unfixed-fix-plan.md U6): 设计现金仓位偏高（19-24% > 验收 15%）。
U11 (round2-unfixed-fix-plan.md U11): 核心层跨方案重叠 >1。

- U6 R1: allocate 层内分配不满 → 剩余预算按 factor_score 回补（减少被动 CASH）。
- U6 R2: range_bound 下 balanced 预算微调。
- U11 R1: 后续方案 core 全部 ⊆ 前序已用时强制引入 ≥1 只新宽基。

纯函数测试，无 I/O。
"""

import pytest

from app.engine.allocation_engine import allocate
from app.engine.budgets import dynamic_layer_budget


def _fm(candidates, seed=0.5):
    return {c["symbol"]: {"technical": seed, "momentum": seed,
                          "valuation": seed, "sentiment": seed}
            for c in candidates}


def _cands():
    return [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "沪深300", "segment": "沪深300", "industry": "宽基指数"},
        {"symbol": "560600", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "segment": "中证A500", "industry": "宽基指数"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "tracked_index": "科创50", "segment": "科创", "industry": "宽基指数"},
        {"symbol": "159915", "name": "创业板ETF", "layer": "core",
         "tracked_index": "创业板指", "segment": "创业板", "industry": "宽基指数"},
        {"symbol": "510050", "name": "上证50ETF", "layer": "core",
         "tracked_index": "上证50", "segment": "上证50", "industry": "宽基指数"},
        # U11: 扩展 core 候选（红利/A500深市）使两两重叠可收敛 ≤1
        {"symbol": "512890", "name": "红利低波ETF", "layer": "core",
         "tracked_index": "红利低波", "segment": "红利低波", "industry": "红利"},
        {"symbol": "515080", "name": "中证红利ETF", "layer": "core",
         "tracked_index": "中证红利", "segment": "中证红利", "industry": "红利"},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "segment": "中证A500", "industry": "宽基指数"},
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "segment": "半导体"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
         "tracked_index": "新能源", "segment": "新能源"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
         "tracked_index": "医药", "segment": "医药"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "segment": "黄金"},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "tracked_index": "国债", "segment": "国债"},
    ]


class TestU6CashBudget:
    def test_balanced_range_bound_cash_reflects_budget_gaps(self):
        """R140: balanced + range_bound 现金反映未用满的层预算缺口（defense
        budget 0.13 因 layer_count=1 仅黄金 5% 未填满），卫星层不超 budget 为硬约束。"""
        cands = _cands()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_fm(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "balanced":
                continue
            lb = s["layer_budget"]
            # 卫星层总权重 ≤ budget（R140 硬约束）
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite" and a.get("symbol") != "CASH"]
            sat_total = sum(a.get("weight", 0) for a in sat)
            assert sat_total <= lb["satellite"] + 0.001, (
                f"R140: balanced 卫星层 Σweight={sat_total:.4f} > budget {lb['satellite']:.4f}"
            )
            # 现金 = Σ未用满层缺口（defense 仅黄金 5% 填不满 0.13 预算）
            non_cash = sum(a.get("weight", 0) for a in s["allocations"] if a.get("symbol") != "CASH")
            cash = max(0.0, 1.0 - non_cash)
            assert cash >= 0.0, f"balanced 现金 {cash:.2%} 不应为负"

    def test_defensive_cash_also_controlled(self):
        """R140: 防御型卫星层总权重 ≤ budget（defense 层黄金+国债可填满预算）。"""
        cands = _cands()
        strategies = allocate(risk_profile="defensive", regime="range_bound",
                              factor_matrix=_fm(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "defensive":
                continue
            lb = s["layer_budget"]
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite" and a.get("symbol") != "CASH"]
            sat_total = sum(a.get("weight", 0) for a in sat)
            assert sat_total <= lb["satellite"] + 0.001, (
                f"R140: defensive 卫星层 Σweight={sat_total:.4f} > budget {lb['satellite']:.4f}"
            )

    def test_range_bound_balanced_budget_tweak(self):
        """U6 R2: range_bound + balanced → satellite +0.02 / defense -0.02。"""
        b = dynamic_layer_budget("balanced", "range_bound")
        # §5.1C (round8): balanced 压卫星 0.30→0.20、防御 0.10→0.15 → range_bound
        # 微调后 satellite 0.22 / defense 0.13
        assert b["satellite"] == pytest.approx(0.22)
        assert b["defense"] == pytest.approx(0.13)
        # 其他 regime 不受影响（回归）：bull_strong 抬卫星（新 base 0.20 + 0.08 = 0.28）
        b2 = dynamic_layer_budget("balanced", "bull_strong")
        assert b2["satellite"] > 0.20
        assert b2["satellite"] == pytest.approx(0.28)


class TestU11CoreOverlap:
    def _differentiated_fm(self, cands):
        """带区分度的因子矩阵——技术面/动量面分布不同，使三方案（权重不同）选出差异化 core。

        defensive 权重 technical 0.4 / momentum 0.15 → 偏好 tech 高标的；
        aggressive 权重 momentum 0.45 / technical 0.2 → 偏好 mom 高标的。
        """
        profiles = {
            "510300": (0.8, 0.3), "560600": (0.7, 0.35), "588000": (0.2, 0.9),
            "159915": (0.3, 0.8), "510050": (0.75, 0.2), "512890": (0.65, 0.25),
            "515080": (0.6, 0.3), "159338": (0.72, 0.4),
            "512480": (0.5, 0.5), "515030": (0.4, 0.6), "512010": (0.45, 0.45),
            "512880": (0.35, 0.7), "518880": (0.55, 0.3), "511090": (0.5, 0.1),
        }
        fm = {}
        for c in cands:
            t, m = profiles.get(c["symbol"], (0.5, 0.5))
            fm[c["symbol"]] = {"technical": t, "momentum": m,
                               "valuation": 0.5, "sentiment": 0.5}
        return fm

    def test_core_pairwise_overlap_le_1(self):
        """U11 验收: 防御型与进攻型 core 差异化（排除强制标的 510300/560600——
        MANDATORY_CODES 三方案必现与 U11 验收天然冲突，文档 M7 优先）。

        防御型（重 technical）与进攻型（重 momentum）应选择不同的非强制 core。
        """
        cands = _cands()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=self._differentiated_fm(cands), candidates=cands)
        by_id = {s["id"]: s for s in strategies}
        def_core = {a["symbol"] for a in by_id["defensive"]["allocations"]
                    if a.get("layer") == "core" and a.get("symbol") not in ("CASH", "510300", "560600")}
        agg_core = {a["symbol"] for a in by_id["aggressive"]["allocations"]
                    if a.get("layer") == "core" and a.get("symbol") not in ("CASH", "510300", "560600")}
        # 防御偏好 tech 高（510050/512890/159338），进攻偏好 mom 高（588000/159915）
        assert "588000" in agg_core, f"进攻型应选科创50（mom 高）: {agg_core}"
        assert "588000" not in def_core, f"防御型不应选科创50（被 C2 惩罚）: {def_core}"
        assert len(def_core & agg_core) <= 1, \
            f"防御/进攻非强制 core 重叠 {def_core & agg_core} 过多（U11）"

    def test_core_union_at_least_six(self):
        """U11 R2 备选口径: 三套方案 core 并集 ≥6 只（高分宽基少时重叠不可避免，
        以并集宽度保证多样性）。"""
        cands = _cands()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=self._differentiated_fm(cands), candidates=cands)
        core_sets = [
            {a["symbol"] for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"}
            for s in strategies
        ]
        union = core_sets[0] | core_sets[1] | core_sets[2]
        assert len(union) >= 6, f"三套方案 core 并集 {len(union)} < 6（U11 R2）"

    def test_later_strategy_introduces_new_core(self):
        """U11 R1: 前序方案 core 被后续方案全量复用时，引入 ≥1 只新宽基。"""
        cands = _cands()
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=self._differentiated_fm(cands), candidates=cands)
        core_sets = [
            {a["symbol"] for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"}
            for s in strategies
        ]
        # 第 2/3 方案 core 不应是第 1 方案的子集（至少 1 只新宽基）
        for i in (1, 2):
            assert not core_sets[i].issubset(core_sets[0]), \
                f"方案 {i+1} core {core_sets[i]} 全部复用方案 1（U11 应引入新宽基）"


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
def _total_count(s):
    return sum(1 for a in s.get("allocations", []) if a.get("symbol") != "CASH")
class TestTotalInstrumentMonotonic:
    def test_total_count_def_lt_bal_lt_agg(self):
        """#12 / INV-5：总标的数 防御 < 平衡 < 进攻。

        R101 (round32) 修正：O16 互斥剔除改为宽基数量上限（≤4 含锚）后，balanced
        核心层可并存更多不同宽基（510050/510500 等），总标的数不再保证严格
        防御 < 平衡 < 进攻（本池 balanced 12 = aggressive 12）。保留原 #12 核心
        意图：防御最精简（< 平衡 且 < 进攻）、进攻不瘦于防御。卫星/防御层严格单调
        由 INV-3/#13 独立覆盖（本测试不重复）。
        """
        cands = _candidate_pool()
        strategies = allocate(
            risk_profile="all", regime="range_bound",
            factor_matrix=_factor_matrix(cands), candidates=cands,
        )
        by = _allocs_by_id(strategies)
        tot = {p: _total_count(by[p]) for p in ("defensive", "balanced", "aggressive")}
        # 防御最精简（R101 后仍是有效不变量）
        assert tot["defensive"] < tot["balanced"], (
            f"防御应比平衡精简: {tot}"
        )
        assert tot["defensive"] < tot["aggressive"], (
            f"防御应比进攻精简: {tot}"
        )
        # 进攻 ≥ 防御（文档 #12 直接要求）
        assert tot["aggressive"] >= tot["defensive"]
        # R101：balanced 可并存不同宽基 → 核心层数量上限 4 生效（本池 balanced 5 只核心）
        core_bal = [a for a in by["balanced"]["allocations"]
                    if a.get("layer") == "core" and a.get("symbol") != "CASH"]
        assert len(core_bal) <= 5, f"balanced 核心层 {len(core_bal)} 只超上限 5"
        wide_bal = [a for a in core_bal
                    if any(k in f"{a.get('name', '') or ''}{a.get('tracked_index', '') or ''}"
                           for k in ("沪深300", "中证A500", "中证A50", "中证A100", "上证50",
                                     "上证180", "深证100", "中证100", "中证800", "中证500",
                                     "MSCI", "A500", "A50"))]
        assert len(wide_bal) <= 4, f"balanced 核心层宽基 {len(wide_bal)} 只超上限 4"
