from __future__ import annotations
"""
R140 (round38): 最终层预算校验测试——reconcile 均摊后每层总权重不得超过 budget。

背景：R131 cap 只在 _select_and_weight 返回时钳制卫星层；_reconcile_budget_shortfall
会把总预算缺口按 factor_score 均摊到非强制标的（含卫星层），可能推超层预算
（round38 实测 balanced 卫星 0.300 > 0.220、aggressive 0.350 > 0.300，且非CASH
总权重 >1.0 使 strategy_design 现金计算为负 → 总仓位 >1.0）。
R140 修复在 reconcile 之后做最终层预算校验，保证各层 ≤ budget、下游现金为正。

纯函数测试，无 I/O。
"""

from app.engine.allocation_engine import allocate


def _base_candidates():
    """含强制标的（510300/159338）+ 多只高分卫星 + 防御。"""
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
        # satellite（6 只，全高分 → 触发超配）
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "segment": "半导体"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
         "tracked_index": "新能源", "segment": "新能源"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
         "tracked_index": "医药", "segment": "医药"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        {"symbol": "513090", "name": "香港证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        {"symbol": "512170", "name": "医疗ETF", "layer": "satellite",
         "tracked_index": "医疗", "segment": "医疗"},
        # defense
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "segment": "黄金"},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "tracked_index": "国债", "segment": "国债"},
    ]


def _extreme_factor_matrix(cands):
    """卫星全高分（0.95），其余 0.5——触发卫星层超配 + reconcile 均摊推超。"""
    return {
        c["symbol"]: (
            {"technical": 0.95, "momentum": 0.95, "valuation": 0.95, "sentiment": 0.95}
            if c["layer"] == "satellite"
            else {"technical": 0.5, "momentum": 0.5, "valuation": 0.5, "sentiment": 0.5}
        )
        for c in cands
    }


class TestR140FinalLayerBudget:
    """R140: reconcile 之后每层总权重 ≤ budget + 严格容差。"""

    def test_satellite_layer_never_exceeds_budget_after_reconcile(self):
        """三套方案卫星层总权重 ≤ budget（容差 0.001，覆盖 reconcile 残差）。

        修复前（round38 实证）：balanced 0.300>0.220、aggressive 0.350>0.300。
        修复后卫星层总权重不得超预算。
        """
        cands = _base_candidates()
        fm = _extreme_factor_matrix(cands)
        for profile in ("defensive", "balanced", "aggressive"):
            strategies = allocate(risk_profile=profile, regime="bullish",
                                  factor_matrix=fm, candidates=cands)
            for s in strategies:
                if s["id"] != profile:
                    continue
                lb = s["layer_budget"]
                sat = [a for a in s["allocations"]
                       if a.get("layer") == "satellite" and a.get("symbol") != "CASH"]
                sat_total = sum(a.get("weight", 0.0) for a in sat)
                budget = lb.get("satellite", 0.0)
                assert sat_total <= budget + 0.001, (
                    f"R140: {profile} 卫星层 Σweight={sat_total:.4f} > budget {budget:.4f} + 0.001"
                )

    def test_core_layer_never_exceeds_budget_after_reconcile(self):
        """核心层总权重 ≤ budget + 0.001（探针实测 balanced core 0.5089 > 0.50）。"""
        cands = _base_candidates()
        fm = _extreme_factor_matrix(cands)
        for profile in ("defensive", "balanced", "aggressive"):
            strategies = allocate(risk_profile=profile, regime="bullish",
                                  factor_matrix=fm, candidates=cands)
            for s in strategies:
                if s["id"] != profile:
                    continue
                lb = s["layer_budget"]
                core = [a for a in s["allocations"]
                        if a.get("layer") == "core" and a.get("symbol") != "CASH"]
                core_total = sum(a.get("weight", 0.0) for a in core)
                budget = lb.get("core", 0.0)
                assert core_total <= budget + 0.001, (
                    f"R140: {profile} 核心层 Σweight={core_total:.4f} > budget {budget:.4f} + 0.001"
                )

    def test_total_non_cash_never_exceeds_one(self):
        """总非CASH权重 ≤ 1.0（保证 strategy_design 现金计算为正，总仓位 ≤ 1.0）。"""
        cands = _base_candidates()
        fm = _extreme_factor_matrix(cands)
        for profile in ("defensive", "balanced", "aggressive"):
            strategies = allocate(risk_profile=profile, regime="bullish",
                                  factor_matrix=fm, candidates=cands)
            for s in strategies:
                if s["id"] != profile:
                    continue
                non_cash = sum(a.get("weight", 0.0) for a in s["allocations"]
                               if a.get("symbol") != "CASH")
                assert non_cash <= 1.0 + 1e-6, (
                    f"R140: {profile} 总非CASH权重={non_cash:.4f} > 1.0"
                )

    def test_mandatory_floor_preserved_after_cap(self):
        """层预算缩放不得破坏强制锚 5% 地板（510300/159338 权重 ≥ 0.05）。"""
        cands = _base_candidates()
        fm = _extreme_factor_matrix(cands)
        strategies = allocate(risk_profile="balanced", regime="bullish",
                              factor_matrix=fm, candidates=cands)
        for s in strategies:
            if s["id"] != "balanced":
                continue
            for a in s["allocations"]:
                if a.get("symbol") in ("510300", "159338"):
                    assert a.get("weight", 0) >= 0.05, (
                        f"R140: 强制锚 {a['symbol']} 权重 {a.get('weight')} < 5% 地板"
                    )
