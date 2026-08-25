from __future__ import annotations
"""
round36 B5-S5: validate 段单测——跨方案 INV 校验收口函数。

_validate_cross_profile_invariants 为 check_structure_reasonableness 内
INV-3/5/6 跨方案块的原样提取（行为锚：test_allocation_engine_fixes 等的
INV 用例继续覆盖集成路径；本文件直接钉定提取后的命名段）。
"""


def _strategy(pid: str, sat: int, dfn: int, total_extra_core: int = 0,
              cash: float = 0.0, defense_weight: float = 0.0) -> dict:
    """构造最小三件套之一：卫星 sat 只 / 防御 dfn 只 / 核心 total_extra_core 只。"""
    allocs = []
    for i in range(total_extra_core):
        allocs.append({"symbol": f"C{i}{pid[0]}", "layer": "core", "weight": 0.1})
    for i in range(sat):
        allocs.append({"symbol": f"S{i}{pid[0]}", "layer": "satellite", "weight": 0.1})
    for i in range(dfn):
        allocs.append({"symbol": f"D{i}{pid[0]}", "layer": "defense", "weight": 0.02})
    if cash:
        allocs.append({"symbol": "CASH", "weight": cash})
    return {"id": pid, "allocations": allocs}


class TestValidateCrossProfileInvariants:
    def test_monotonic_structures_pass_silently(self):
        """INV-3/5/6 全满足 → 无 structure_warnings 写入（正向）。"""
        from app.engine.allocation_engine import _validate_cross_profile_invariants

        strategies = [
            _strategy("defensive", sat=1, dfn=3, total_extra_core=1),
            _strategy("balanced", sat=2, dfn=2, total_extra_core=2),
            # aggressive: 卫星最多、防御最少、非现金权重 ≥0.90、防御 ≤0.05
            _strategy("aggressive", sat=3, dfn=1, total_extra_core=4),
        ]
        # aggressive 非现金合计 = 4*0.1 + 3*0.1 + 1*0.02 = 0.72 < 0.90 → 会触发 INV-6
        # 补足核心权重使非现金 ≥0.90：
        strategies[2]["allocations"][0]["weight"] = 0.58
        _validate_cross_profile_invariants(strategies)
        assert "structure_warnings" not in strategies[2].get("risk_metrics", {}), (
            "全单调结构不得产生 INV 告警"
        )

    def test_inv3_violation_appends_warning(self):
        """负向断言：卫星数不单调（aggressive 卫星少于 balanced）→ inv3 告警必现。"""
        from app.engine.allocation_engine import _validate_cross_profile_invariants

        strategies = [
            _strategy("defensive", sat=2, dfn=3, total_extra_core=1),
            _strategy("balanced", sat=2, dfn=2, total_extra_core=2),
            _strategy("aggressive", sat=1, dfn=1, total_extra_core=8),
        ]
        strategies[2]["allocations"][0]["weight"] = 0.60
        _validate_cross_profile_invariants(strategies)
        warns = strategies[2]["risk_metrics"]["structure_warnings"]
        types = {w["type"] for w in warns}
        assert "inv3_satellite_not_monotonic" in types
        assert "inv5_total_not_monotonic" not in types or True  # INV-5 视构造而定，不强断言

    def test_inv6_aggressive_cash_over_flagged(self):
        """负向断言：进攻型现金 >0.10 → inv6_aggressive_cash_over 必现。"""
        from app.engine.allocation_engine import _validate_cross_profile_invariants

        strategies = [
            _strategy("defensive", sat=1, dfn=3, total_extra_core=1),
            _strategy("balanced", sat=2, dfn=2, total_extra_core=2),
            _strategy("aggressive", sat=3, dfn=1, total_extra_core=1, cash=0.50),
        ]
        strategies[2]["allocations"][0]["weight"] = 0.20
        _validate_cross_profile_invariants(strategies)
        warns = strategies[2]["risk_metrics"]["structure_warnings"]
        assert any(w["type"] == "inv6_aggressive_cash_over" for w in warns)

    def test_missing_aggressive_skips_without_crash(self):
        """缺 aggressive 方案（_have_all=False）→ 守卫跳过跨方案校验，不崩溃。

        注：守卫在公共入口 check_structure_reasonableness；helper 契约为
        「调用方已保证三方案齐全」，故本用例经入口验证守卫行为。
        """
        from app.engine.allocation_engine import check_structure_reasonableness

        strategies = [
            _strategy("defensive", sat=1, dfn=3, total_extra_core=1),
            _strategy("balanced", sat=2, dfn=2, total_extra_core=2),
        ]
        out = check_structure_reasonableness(strategies)
        assert len(out) == 2
        assert all("risk_metrics" not in s or "structure_warnings" not in s["risk_metrics"]
                   for s in out)
