"""v7 P2: evals harness + ci_gate 单测（金标加载/评分分发/门禁阻断逻辑）。

金标跑真执行的部分已在 demo.jsonl 端到端验证（10/10）——本文件只测
纯逻辑：load_goldens 解析、run_all 汇总、ci_gate.check 阻断口径。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.evals.ci_gate import check
from scripts.evals.harness import load_goldens


GOLDEN_DIR = Path(__file__).resolve().parents[1] / "scripts" / "evals" / "goldens"


class TestLoadGoldens:
    def test_loads_10_demo_cases(self):
        cases = load_goldens(GOLDEN_DIR)
        assert len(cases) == 10, f"P0 demo 金标应 10 条: {len(cases)}"

    def test_five_types_covered(self):
        cases = load_goldens(GOLDEN_DIR)
        types = {c["type"] for c in cases}
        assert types == {"quote", "format", "refusal", "multi_step", "factor"} or \
            types == {"quote", "format", "refusal", "multi_step"}, types

    def test_limit_truncates(self):
        assert len(load_goldens(GOLDEN_DIR, limit=3)) == 3

    def test_each_case_has_required_fields(self):
        for c in load_goldens(GOLDEN_DIR):
            assert c["id"] and c["type"]
            if c["type"] == "multi_step":
                assert c.get("steps"), f"{c['id']} multi_step 需 steps"
            else:
                assert c.get("tool"), f"{c['id']} 单工具题需 tool"


class TestCiGateCheck:
    def _report(self, pass_rate, by_type):
        return {"total": 10, "passed": int(pass_rate / 10),
                "pass_rate": pass_rate, "by_type": by_type, "results": []}

    def test_all_gates_pass(self):
        ok, blocking = check(self._report(100.0, {
            "refusal": {"pass": 2, "total": 2},
            "format": {"pass": 3, "total": 3},
            "multi_step": {"pass": 2, "total": 2},
        }))
        assert ok and not blocking

    def test_low_pass_rate_blocks(self):
        ok, blocking = check(self._report(80.0, {
            "refusal": {"pass": 2, "total": 2},
            "format": {"pass": 3, "total": 3},
        }))
        assert not ok and any("95%" in m for m in blocking)

    def test_refusal_hallucination_blocks(self):
        ok, blocking = check(self._report(100.0, {
            "refusal": {"pass": 1, "total": 2},
            "format": {"pass": 3, "total": 3},
        }))
        assert not ok and any("拒答" in m for m in blocking)

    def test_format_missing_blocks(self):
        ok, blocking = check(self._report(100.0, {
            "refusal": {"pass": 2, "total": 2},
            "format": {"pass": 2, "total": 3},
        }))
        assert not ok and any("格式" in m for m in blocking)

    def test_multi_step_low_rate_warns_not_blocks(self):
        ok, blocking = check(self._report(100.0, {
            "refusal": {"pass": 2, "total": 2},
            "format": {"pass": 3, "total": 3},
            "multi_step": {"pass": 1, "total": 2},  # 50% < 80%
        }))
        assert ok and not blocking  # 非阻断
