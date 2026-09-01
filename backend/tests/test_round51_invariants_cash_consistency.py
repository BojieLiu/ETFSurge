"""round51 方案 A (R162): verify_allocation_invariants 补一致性/完整性断言.

背景 (round51 §4.2): 原 :61-83 只断言两个「上限」方向（层超配/总仓位越限）,
抓不到 R162 悬空——cash 行 ≠ 1−Σnon_cash 时 total<1 但两上限断言全 PASS。

补 3 条断言 (方案 A):
- ① abs(cash_row − (1−Σnon_cash)) ≤ 0.005 (R162 cash 一致性, 容差 0.005)
- ② 每标的 |target_amount − capital×weight| ≤ 1 (R163 派生字段同步)
- ③ Σtotal(含 cash) ≤ 1.0 + 0.01 (含 cash 的总仓位上限)

负向验收 (文档要求): 手工构造 design15 形态 (cash 悬空 GAP 0.05) 必 FAIL。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_allocation_invariants.py"
_spec = importlib.util.spec_from_file_location("_verify_alloc_inv", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_verify_alloc_inv", _mod)
_spec.loader.exec_module(_mod)

_check_design = _mod._check_design


def _design(etfs: list[dict], layer_budget: dict | None = None,
            capital: float = 500000.0, did: int = 15) -> dict:
    return {
        "id": did,
        "strategies": [{
            "id": "balanced",
            "capital": capital,
            "layer_budget": layer_budget or {"core": 0.50, "satellite": 0.22,
                                             "defense": 0.13},
            "etfs": etfs,
        }],
    }


# design15 balanced 实测形态 (round51 probe11): cash 行 0.23 vs 1−Σnon_cash=0.28
_DESIGN15_BALANCED = [
    {"symbol": "510300", "layer": "core", "weight": 0.45, "target_amount": 225000.0},
    {"symbol": "512890", "layer": "satellite", "weight": 0.22, "target_amount": 110000.0},
    {"symbol": "518880", "layer": "defense", "weight": 0.05, "target_amount": 25000.0},
    {"symbol": "CASH", "layer": "cash", "weight": 0.23,
     "selection_rationale": "流动性管理"},
]


class TestCashConsistency:
    """断言①: cash 行 == 1−Σnon_cash (R162)。"""

    def test_design15_gap_form_must_fail(self):
        """负向: design15 形态 (cash 悬空 GAP 0.05) 必 FAIL——旧实现全 PASS。"""
        violations = _check_design(_design(_DESIGN15_BALANCED))
        assert any("cash" in v.lower() for v in violations), \
            f"cash 悬空未被捕获: {violations}"

    def test_consistent_cash_passes(self):
        etfs = [dict(a) for a in _DESIGN15_BALANCED]
        etfs[-1]["weight"] = 0.28  # 对齐 1−Σnon_cash
        assert _check_design(_design(etfs)) == []

    def test_missing_cash_row_with_gap_under_1_passes_cash_check(self):
        """cash 行缺失本身不是悬空（可能被上游省略），但 Σnon_cash<1 时
        total 断言会捕获——这里验证无 cash 行不误报 cash 一致性。"""
        etfs = [a for a in _DESIGN15_BALANCED if a["symbol"] != "CASH"]
        violations = _check_design(_design(etfs))
        assert not any("cash row" in v.lower() and "missing" in v.lower()
                       for v in violations)


class TestTargetAmountSync:
    """断言②: |target_amount − capital×weight| ≤ 1 (R163)。"""

    def test_stale_target_amount_must_fail(self):
        """负向: target_amount 按旧权重 (0.28×500000=140000) 而 weight=0.22。"""
        etfs = [dict(a) for a in _DESIGN15_BALANCED]
        etfs[-1]["weight"] = 0.28
        etfs[1]["target_amount"] = 140000.0  # 旧权重 0.28×capital, weight 已 0.22
        violations = _check_design(_design(etfs))
        assert any("target_amount" in v for v in violations), \
            f"target_amount 脱节未被捕获: {violations}"

    def test_synced_target_amount_passes(self):
        etfs = [dict(a) for a in _DESIGN15_BALANCED]
        etfs[-1]["weight"] = 0.28
        etfs[1]["target_amount"] = 110000.0  # 0.22×500000
        assert _check_design(_design(etfs)) == []


class TestTotalWithCash:
    """断言③: Σtotal(含 cash) ≤ 1.0 + tol。"""

    def test_cash_overflow_must_fail(self):
        etfs = [dict(a) for a in _DESIGN15_BALANCED]
        etfs[-1]["weight"] = 0.33  # total = 0.72+0.33 = 1.05
        violations = _check_design(_design(etfs))
        assert any("total" in v.lower() for v in violations), \
            f"cash 溢出未被捕获: {violations}"

    def test_total_at_one_passes(self):
        etfs = [dict(a) for a in _DESIGN15_BALANCED]
        etfs[-1]["weight"] = 0.28
        assert _check_design(_design(etfs)) == []
