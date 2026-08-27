from __future__ import annotations
"""
round36 B5-S4: reconcile 段单测——终态预算求解与残差显式报告。

覆盖两段：
- _reconcile_core_budget_topup（原 allocate 内联 O16 块）：核心层预算缺口按剩余
  容量占比补足，单只 ≤MAX_WEIGHT；容量不足时残差保留（不削超帽、不造假补满）。
- _reconcile_budget_shortfall（原 allocate 内联 U6 R1 块）：总预算缺口按
  factor_score 序均摊至非现金非强制标的，单只 ≤0.30；帽约束致残差时显式留残
  （负向断言：不得为凑 Σ 削减既有持仓或突破单只上限）。

符号 888888/777777 为虚构非强制标的（纯函数测试，无数据依赖）。
"""

import math

from app.engine.allocation_engine import (
    MAX_WEIGHT,
    _reconcile_budget_shortfall,
    _reconcile_core_budget_topup,
)


def _total(allocs: list[dict]) -> float:
    return sum(a.get("weight", 0.0) for a in allocs if a.get("symbol") != "CASH")


class TestReconcileCoreBudgetTopup:
    def test_fills_gap_by_capacity_proportions(self):
        """缺口按 (MAX_WEIGHT - 当前权重) 容量占比补足，总量收敛到层预算。"""
        allocs = [
            {"symbol": "A", "weight": 0.10},
            {"symbol": "B", "weight": 0.05},
        ]
        out = _reconcile_core_budget_topup(allocs, 0.50, "balanced")
        assert abs(_total(out) - 0.50) < 1e-6
        assert all(a["weight"] <= MAX_WEIGHT + 1e-9 for a in out)

    def test_residual_when_capacity_insufficient(self):
        """双持仓均已到帽 → 预算无法补满，残差显式保留且不得突破单只上限。"""
        allocs = [
            {"symbol": "A", "weight": 0.30},
            {"symbol": "B", "weight": 0.30},
        ]
        out = _reconcile_core_budget_topup(allocs, 0.90, "aggressive")
        assert _total(out) < 0.90 - 1e-6, "容量不足必须留残差，不得造假补满"
        assert all(a["weight"] <= MAX_WEIGHT + 1e-9 for a in out)

    def test_no_op_when_already_over_budget(self):
        """已超预算（钳制前遗留）→ 原样返回，不得反向削减。"""
        allocs = [{"symbol": "A", "weight": 0.45}]
        out = _reconcile_core_budget_topup(allocs, 0.40, "balanced")
        assert out[0]["weight"] == 0.45


class TestReconcileBudgetShortfall:
    def test_distributes_shortfall_evenly_with_cap(self):
        """缺口按层均摊；触及 0.30 帽的持仓不再多拿。"""
        allocs = [
            {"symbol": "888888", "weight": 0.28, "factor_score": 2.0, "layer": "satellite"},
            {"symbol": "777777", "weight": 0.12, "factor_score": 1.0, "layer": "satellite"},
        ]
        # 卫星预算 0.60 → 缺口 0.20，均摊 0.10/只：888888→0.30(触帽)、777777→0.22
        out = _reconcile_budget_shortfall(allocs, {"satellite": 0.60})
        by_sym = {a["symbol"]: a["weight"] for a in out}
        assert by_sym["888888"] == 0.30
        assert math.isclose(by_sym["777777"], 0.22, abs_tol=1e-9)

    def test_excludes_cash_and_mandatory_from_topup(self):
        """CASH 与强制锚不参与回补；帽约束致残差时显式留残。"""
        allocs = [
            {"symbol": "CASH", "weight": 0.20, "layer": "cash"},
            {"symbol": "510300", "weight": 0.05, "factor_score": 9.9, "layer": "core"},
            {"symbol": "888888", "weight": 0.10, "factor_score": 1.0, "layer": "satellite"},
            {"symbol": "777777", "weight": 0.15, "factor_score": 0.5, "layer": "satellite"},
        ]
        out = _reconcile_budget_shortfall(allocs, {"satellite": 1.0, "core": 0.50})
        by_sym = {a["symbol"]: a["weight"] for a in out}
        assert by_sym["CASH"] == 0.20, "CASH 权重不得被 top-up 改写"
        assert by_sym["510300"] == 0.05, "强制锚不参与回补（防推过 INV-6 钳制）"
        assert by_sym["888888"] == 0.30 and by_sym["777777"] == 0.30
        # 双双触帽后仍有残差未填——总量 < 预算（诚实留残而非伪造 Σ）
        assert _total(out) < 1.0 - 1e-6

    def test_small_shortfall_below_threshold_ignored(self):
        """缺口 ≤0.001 不触发回补（避免浮点噪声扰动）。"""
        allocs = [{"symbol": "888888", "weight": 0.1998, "factor_score": 1.0, "layer": "satellite"}]
        out = _reconcile_budget_shortfall(allocs, {"satellite": 0.20})
        assert out[0]["weight"] == 0.1998
