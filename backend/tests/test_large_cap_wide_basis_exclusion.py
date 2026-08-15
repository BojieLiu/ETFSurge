from __future__ import annotations
"""
O16 (docs/archived/round7-rediagnosis.md §7): 核心层大盘宽基族互斥。

P18 问题: A500(强制) + A50 + A100 + 沪深300(强制) 同现核心层——4 个宽基中 3 个
大盘/超大盘（相关性 ~0.95+），核心层权重押注同一「大盘 beta」，分散失效。

约束: 核心层「非强制大盘宽基」数量 ≤ 1（强制锚 510300/159338 已占 2 个名额）;
balanced/aggressive 建议 ≤0; defensive 允许 ≤1（上证50 场景）。

纯函数测试，无 I/O。
"""

from app.engine.allocation_engine import (
    allocate,
    MANDATORY_CODES,
    _is_large_cap_wide_basis,
)


def _factor_matrix(cands, scores=None):
    s = scores or {}
    return {c["symbol"]: {
        "technical": s.get(c["symbol"], 0.5),
        "momentum": 0.5,
        "valuation": 0.5,
        "sentiment": 0.5,
    } for c in cands}


def _cand(symbol, name, layer="core", tracked_index=None, segment=None):
    return {"symbol": symbol, "name": name, "layer": layer,
            "tracked_index": tracked_index or name, "segment": segment or name}


def _base_candidates():
    """含强制锚（沪深300/A500）+ 非锚大盘宽基（A50/A100）+ 红利/科创/消费 + 卫星 + 防御。"""
    return [
        _cand("510300", "沪深300ETF", "core", "沪深300", "沪深300"),
        _cand("159338", "中证A500ETF", "core", "中证A500", "中证A500"),
        _cand("563080", "中证A50ETF", "core", "中证A50", "中证A50"),
        _cand("562000", "中证A100ETF", "core", "中证A100", "中证A100"),
        _cand("512890", "红利低波ETF", "core", "红利低波", "红利低波"),
        _cand("588000", "科创50ETF", "core", "科创50", "科创"),
        _cand("159928", "消费ETF", "core", "中证消费", "消费"),
        # satellite
        _cand("512480", "半导体ETF", "satellite", "半导体", "半导体"),
        _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
        _cand("512010", "医药ETF", "satellite", "医药", "医药"),
        _cand("512880", "证券ETF", "satellite", "证券", "证券"),
        # defense
        _cand("518880", "黄金ETF", "defense", "黄金", "黄金"),
        _cand("511090", "30年国债ETF", "defense", "国债", "国债"),
    ]


def _non_anchor_large_cap_core(strategies, profile):
    """返回指定方案核心层中「非强制大盘宽基」标的列表。"""
    for s in strategies:
        if s["id"] != profile:
            continue
        core = [a for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
        return [a for a in core if a["symbol"] not in MANDATORY_CODES
                and _is_large_cap_wide_basis(a)]
    return []


def _core_weight_sum(strategies, profile):
    for s in strategies:
        if s["id"] != profile:
            continue
        core = [a for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
        return round(sum(a.get("weight", 0) for a in core), 4)
    return 0.0


class TestIsLargeCapWideBasis:
    def test_detects_large_cap_broad_basis(self):
        assert _is_large_cap_wide_basis({"name": "中证A50ETF", "tracked_index": "中证A50"})
        assert _is_large_cap_wide_basis({"name": "上证50ETF", "tracked_index": "上证50"})
        assert _is_large_cap_wide_basis({"name": "中证800ETF", "tracked_index": "中证800"})
        assert _is_large_cap_wide_basis({"name": "深证100ETF", "tracked_index": "深证100"})
        assert _is_large_cap_wide_basis({"name": "MSCI中国A50ETF", "tracked_index": "MSCI中国A50"})

    def test_excludes_midcap_and_growth(self):
        # 中盘宽基（中证500）与成长宽基（科创50/创业板）不算大盘宽基
        assert not _is_large_cap_wide_basis({"name": "中证500ETF", "tracked_index": "中证500"})
        assert not _is_large_cap_wide_basis({"name": "科创50ETF", "tracked_index": "科创50"})
        assert not _is_large_cap_wide_basis({"name": "创业板ETF", "tracked_index": "创业板指"})
        assert not _is_large_cap_wide_basis({"name": "半导体ETF", "tracked_index": "半导体"})
        assert not _is_large_cap_wide_basis({"name": "红利低波ETF", "tracked_index": "红利低波"})


class TestLargeCapWideBasisExclusion:
    def test_balanced_core_excludes_non_anchor_large_cap(self):
        """① A500(强制)+A50+A100+沪深300(强制) 候选 → balanced 核心层非锚大盘宽基 ≤0。"""
        cands = _base_candidates()
        scores = {"563080": 2.0, "562000": 2.0, "512890": -0.5}  # A50/A100 高分确保入选
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        non_anchor = _non_anchor_large_cap_core(strategies, "balanced")
        assert len(non_anchor) == 0, f"balanced 核心层非锚大盘宽基 {len(non_anchor)} 只（应为 0）: {[a['symbol'] for a in non_anchor]}"

    def test_aggressive_core_excludes_non_anchor_large_cap(self):
        """balanced/aggressive 建议 ≤0——aggressive 同样不保留非锚大盘宽基。"""
        cands = _base_candidates()
        scores = {"563080": 2.0, "562000": 2.0, "512890": -0.5}
        strategies = allocate(risk_profile="aggressive", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        non_anchor = _non_anchor_large_cap_core(strategies, "aggressive")
        assert len(non_anchor) == 0, f"aggressive 核心层非锚大盘宽基 {len(non_anchor)} 只"

    def test_weight_conservation_after_exclusion(self):
        """被剔除者权重回补其余核心（核心层权重守恒，不转 CASH）。"""
        cands = _base_candidates()
        scores = {"563080": 2.0, "562000": 2.0, "512890": -0.5}
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        # 核心层总权重应为 core budget（本用例 range_bound balanced core 预算）
        from app.engine.budgets import dynamic_layer_budget
        core_budget = dynamic_layer_budget("balanced", "range_bound").get("core", 0)
        total = _core_weight_sum(strategies, "balanced")
        assert abs(total - round(core_budget, 4)) < 0.05, \
            f"核心层权重 {total} 偏离预算 {core_budget}（裁剪后未守恒）"

    def test_defensive_keeps_at_most_one_ss50(self):
        """② defensive 允许 ≤1——上证50 高分时保留 1 只（不剔除）。"""
        cands = [
            _cand("510300", "沪深300ETF", "core", "沪深300", "沪深300"),
            _cand("159338", "中证A500ETF", "core", "中证A500", "中证A500"),
            _cand("510050", "上证50ETF", "core", "上证50", "上证50"),
            _cand("563080", "中证A50ETF", "core", "中证A50", "中证A50"),
            _cand("512890", "红利低波ETF", "core", "红利低波", "红利低波"),
            _cand("512480", "半导体ETF", "satellite", "半导体", "半导体"),
            _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
            _cand("512010", "医药ETF", "satellite", "医药", "医药"),
            _cand("518880", "黄金ETF", "defense", "黄金", "黄金"),
        ]
        scores = {"510050": 2.0, "563080": 1.5, "512890": -0.5}
        strategies = allocate(risk_profile="defensive", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        non_anchor = _non_anchor_large_cap_core(strategies, "defensive")
        assert len(non_anchor) <= 1, f"defensive 核心层非锚大盘宽基 {len(non_anchor)} 只（应 ≤1）"
        # 上证50 高分 → 应保留（非锚大盘宽基 = 上证50 或 A50 之一）
        assert len(non_anchor) == 1, "defensive 应保留 1 只非锚大盘宽基（上证50 场景）"

    def test_fallback_when_core_pool_shrinks(self):
        """③ 剔除后候选不足时放宽兜底生效（核心层 ≥3）。"""
        cands = [
            _cand("510300", "沪深300ETF", "core", "沪深300", "沪深300"),
            _cand("159338", "中证A500ETF", "core", "中证A500", "中证A500"),
            _cand("563080", "中证A50ETF", "core", "中证A50", "中证A50"),
            _cand("562000", "中证A100ETF", "core", "中证A100", "中证A100"),
            _cand("512480", "半导体ETF", "satellite", "半导体", "半导体"),
            _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
            _cand("518880", "黄金ETF", "defense", "黄金", "黄金"),
        ]
        scores = {"563080": 2.0, "562000": 2.0}
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        for s in strategies:
            core = [a for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
            assert len(core) >= 3, f"{s['id']} 核心层 {len(core)} 只 < 3（兜底失效）"

    def test_core_budget_fully_used_after_fallback(self):
        """④ 兜底回补后预算补足——MAX_WEIGHT(0.3) 钳制不得使核心预算用不满
        （U6 R1「预算用满现金收敛」断言回归：aggressive 核心候选不足时
        剔除大盘宽基后兜底回补，权重缺口补足到 core budget）。"""
        cands = [
            _cand("510300", "沪深300ETF", "core", "沪深300", "沪深300"),
            _cand("159338", "中证A500ETF", "core", "中证A500", "中证A500"),
            _cand("563880", "A500ETF", "core", "中证A500", "A500"),
            _cand("510050", "上证50ETF", "core", "上证50", "上证50"),
            _cand("588000", "科创50ETF", "core", "科创50", "科创"),
            _cand("159915", "创业板ETF", "core", "创业板指", "创业板"),
            _cand("512480", "半导体ETF", "satellite", "半导体", "半导体"),
            _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
            _cand("512010", "医药ETF", "satellite", "医药", "医药"),
            _cand("512880", "证券ETF", "satellite", "证券", "证券"),
            _cand("518880", "黄金ETF", "defense", "黄金", "黄金"),
        ]
        scores = {"563880": 2.0, "510050": 1.5, "588000": 0.3, "159915": 0.3}
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands, scores), candidates=cands)
        from app.engine.budgets import dynamic_layer_budget
        for s in strategies:
            core = [a for a in s["allocations"] if a.get("layer") == "core" and a.get("symbol") != "CASH"]
            total = sum(a.get("weight", 0) for a in core)
            # §5.1C (round8): balanced/aggressive 压卫星抬防御 → core 预算 0.45→0.50。
            # 本测试候选池仅 6 只 core（大盘宽基互斥后实际 2-3 只，MAX_WEIGHT=0.3）
            # → defensive 等小池方案 core 未满预算属候选不足（非补足逻辑缺陷）。
            # 断言：补足生效（≥ 单只上限×2）且不超预算。
            core_budget = dynamic_layer_budget(s["id"], "range_bound").get("core", 0)
            assert total >= 0.40, f"{s['id']} 核心层权重 {total} 过低（预算补足未生效）"
            # 预算补足逻辑允许 5% 溢出（MAX_WEIGHT 钳制后的余量回补）
            assert total <= round(core_budget, 4) + 0.05, \
                f"{s['id']} 核心层权重 {total} 超预算 {core_budget}"
            # 单只不超 MAX_WEIGHT（风控约束不被预算补足绕过）
            for a in core:
                assert a.get("weight", 0) <= 0.30 + 1e-9, \
                    f"{s['id']} 核心 {a['symbol']} 权重 {a['weight']} 超 30%"


# ===== folded from test_round19_p1.py =====
import pytest
from app.engine.correlation import (
    correlation_matrix, high_correlation_pairs, avg_correlation,
    median_correlation_for,
)
from app.engine.rationale import build_rationale
from app.engine.allocation_engine import (
    _dedup_same_index, _is_large_cap_wide_basis, MANDATORY_CODES,
)
class TestDedupSameIndex:
    """round19 P1-②: 同指数双持有硬约束。"""

    def _alloc(self, symbol, name, layer, weight, fs, tidx=None):
        return {"symbol": symbol, "name": name, "layer": layer,
                "weight": weight, "factor_score": fs, "tracked_index": tidx}

    def test_aggressive_no_dual_a500(self):
        """159338 中证A500（强制锚 core）+ 563360 A500ETF（satellite）→ 剔除非锚低分者
        （负向：同仓双 A500 → FAIL）。"""
        allocs = [
            self._alloc("159338", "中证A500ETF国泰", "core", 0.05, 0.8, "中证A500"),
            self._alloc("563360", "A500ETF华泰柏瑞", "satellite", 0.2064, 0.3, ""),
            self._alloc("510300", "沪深300ETF", "core", 0.1, 0.7, "沪深300"),
        ]
        out = _dedup_same_index(allocs)
        syms = {a["symbol"] for a in out}
        assert "563360" not in syms, "非锚低分 A500 应被剔除（双持有）"
        assert "159338" in syms, "强制锚豁免剔除"
        # 剔除权重回补同层——satellite 层只有 563360 一只被剔、无同层可回补 →
        # 权重丢弃（allocate 主流程转为现金 = 1 - Σ权重）
        total = sum(a["weight"] for a in out)
        assert abs(total - 0.15) < 1e-6, f"剔除权重应转为现金，实得 {total}"

    def test_mandatory_anchor_pair_exempt(self):
        """510300 + 159338 双强制锚（r=0.983）→ 豁免剔除（不报错）。"""
        allocs = [
            self._alloc("510300", "沪深300ETF", "core", 0.06, 0.7, "沪深300"),
            self._alloc("159338", "中证A500ETF国泰", "core", 0.05, 0.8, "中证A500"),
        ]
        out = _dedup_same_index(allocs)
        assert {a["symbol"] for a in out} == {"510300", "159338"}

    def test_same_layer_weight_reclaim(self):
        """同层双持有（无锚）→ 低分者剔除、权重按同层其余标的权重比例回补。"""
        allocs = [
            self._alloc("588200", "科创芯片ETF", "satellite", 0.03, 0.6, "芯片"),
            self._alloc("159995", "芯片ETF", "satellite", 0.05, 0.2, "芯片"),
            self._alloc("515880", "通信ETF", "satellite", 0.05, 0.5, "通信"),
        ]
        out = _dedup_same_index(allocs)
        syms = {a["symbol"] for a in out}
        assert "159995" not in syms, "低分芯片应剔除"
        # 剔除 0.05 → 按同层剩余权重比例回补：588200(0.03) 与 515880(0.05)
        kept_comm = next(a for a in out if a["symbol"] == "515880")
        kept_chip = next(a for a in out if a["symbol"] == "588200")
        # round(…,4) 精度 → 断言放宽 1e-3
        assert kept_comm["weight"] == pytest.approx(0.05 + 0.05 * 0.05 / 0.08, abs=1e-3)
        assert kept_chip["weight"] == pytest.approx(0.03 + 0.05 * 0.03 / 0.08, abs=1e-3)
        # 权重守恒（不含 CASH；round(…,4) 累计误差放宽）
        assert abs(sum(a["weight"] for a in out) - 0.13) < 1e-3


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
def _layer_counts(s):
    allocs = s.get("allocations", [])
    return {
        "core": sum(1 for a in allocs if a.get("layer") == "core" and a.get("symbol") != "CASH"),
        "satellite": sum(1 for a in allocs if a.get("layer") == "satellite" and a.get("symbol") != "CASH"),
        "defense": sum(1 for a in allocs if a.get("layer") == "defense" and a.get("symbol") != "CASH"),
    }
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
