"""R142 选 A 实施: INV-3/5 严格单调放宽为非严格单调测试。

旧公式: 防御<平衡<进攻 (严格小于)
新公式: 防御<=平衡<=进攻 (非严格小于,相等不算违规)
倒挂 (> 反向) 仍报警; INV-6 现金压舱/防御限制保留.
"""
from __future__ import annotations

import pytest

from app.engine.allocation_engine import check_structure_reasonableness


def _mk_strat(pid, allocs):
    """构造策略 dict (id + allocations)."""
    return {"id": pid, "allocations": allocs}


def _count_layer(strat, layer):
    return sum(1 for a in strat["allocations"] if a.get("layer") == layer and a.get("symbol") != "CASH")


class TestR142NonStrictMonotonic:
    def test_equal_satellite_counts_no_warning(self):
        """R142: defensive=balanced=aggressive 卫星数都=2 (相等) → 不报警.
        旧公式会触发 inv3_satellite_not_monotonic; 新公式非严格单调允许相等.
        """
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.20},
                {"symbol": "518880", "layer": "satellite", "weight": 0.20},
                {"symbol": "CASH", "layer": "cash", "weight": 0.60},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.20},
                {"symbol": "518880", "layer": "satellite", "weight": 0.20},
                {"symbol": "CASH", "layer": "cash", "weight": 0.60},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.20},
                {"symbol": "518880", "layer": "satellite", "weight": 0.20},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
        ]
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv3_satellite_not_monotonic" not in types, (
            f"R142: 相等卫星数不应报警, 实际: {types}"
        )

    def test_equal_total_counts_no_warning(self):
        """R142: 三个方案总标的数都=2 (相等) → 不报警 INV-5."""
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.40},
            ]),
        ]
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv5_total_not_monotonic" not in types, (
            f"R142: 相等总标的数不应报警, 实际: {types}"
        )

    def test_inverted_satellite_still_warns(self):
        """R142: 倒挂 (defensive=1 < balanced=4 > aggressive=2) 仍报警.
        既不满足防御<=平衡<=进攻 (平衡<=进攻失败), 也满足不了旧严格单调.
        """
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.20},
                {"symbol": "CASH", "layer": "cash", "weight": 0.80},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.10},
                {"symbol": "518880", "layer": "satellite", "weight": 0.10},
                {"symbol": "159915", "layer": "satellite", "weight": 0.10},
                {"symbol": "512480", "layer": "satellite", "weight": 0.10},
                {"symbol": "CASH", "layer": "cash", "weight": 0.60},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.10},
                {"symbol": "518880", "layer": "satellite", "weight": 0.10},
                {"symbol": "CASH", "layer": "cash", "weight": 0.80},
            ]),
        ]
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv3_satellite_not_monotonic" in types, (
            f"R142: 倒挂必须仍报警, 实际: {types}"
        )

    def test_monotonic_satellite_no_warning(self):
        """R142: 严格单调递增 (1<2<3) → 不报警 (旧公式也通过)."""
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.10},
                {"symbol": "CASH", "layer": "cash", "weight": 0.90},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.10},
                {"symbol": "518880", "layer": "satellite", "weight": 0.10},
                {"symbol": "CASH", "layer": "cash", "weight": 0.80},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "satellite", "weight": 0.10},
                {"symbol": "518880", "layer": "satellite", "weight": 0.10},
                {"symbol": "159915", "layer": "satellite", "weight": 0.10},
                {"symbol": "CASH", "layer": "cash", "weight": 0.60},
            ]),
        ]
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv3_satellite_not_monotonic" not in types, (
            f"严格单调递增不应报警, 实际: {types}"
        )

    def test_inv6_cash_over_still_warns(self):
        """R142: INV-6 现金压舱是硬约束, 不放宽.
        aggressive 现金 0.25 > 0.10 clamp → 仍报警 inv6_aggressive_cash_over.
        """
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "518880", "layer": "core", "weight": 0.25},
                # 现金 0.25 > clamp 0.10
            ]),
        ]
        # 现金 = 1 - 0.75 = 0.25 (超 0.10 阈值)
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv6_aggressive_cash_over" in types, (
            f"INV-6 现金压舱必须仍生效, 实际: {types}"
        )

    def test_inv6_defense_over_still_warns(self):
        """R142: INV-6 防御权重硬约束保留.
        aggressive 防御权重 0.19 > 0.05 clamp → 仍报警 inv6_aggressive_defense_over.
        """
        strats = [
            _mk_strat("defensive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("balanced", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "CASH", "layer": "cash", "weight": 0.50},
            ]),
            _mk_strat("aggressive", [
                {"symbol": "510300", "layer": "core", "weight": 0.50},
                {"symbol": "518880", "layer": "defense", "weight": 0.10},
                {"symbol": "511090", "layer": "defense", "weight": 0.09},
                # 防御总 0.19 > 0.05
                {"symbol": "159915", "layer": "satellite", "weight": 0.20},
                {"symbol": "CASH", "layer": "cash", "weight": 0.11},
            ]),
        ]
        check_structure_reasonableness(strats, cross_profile_only=True)
        types = {
            w["type"]
            for w in strats[2].get("risk_metrics", {}).get("structure_warnings", [])
        }
        assert "inv6_aggressive_defense_over" in types, (
            f"INV-6 防御权重必须仍生效, 实际: {types}"
        )
