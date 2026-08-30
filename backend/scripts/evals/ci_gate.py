"""Evals CI 门禁（v7 §5.5 验收口径）。

阻断项（exit 1）：
- 总通过率 >= 95%
- 拒答题零幻觉 = 100%（refusal 类全 pass）
- 格式合规 = 100%（format 类全 pass）
非阻断（warn）：
- 多步推理完成率 >= 80%

用法：cd backend && python -m scripts.evals.ci_gate
CI 集成：pre-commit / patrol L 段可调用（后端无关，纯进程内）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .harness import load_goldens, run_all


def check(report: dict) -> tuple[bool, list[str]]:
    """按 §5.5 验收口径检查 report。返回 (ok, blocking_messages)。"""
    blocking: list[str] = []
    by_type = report.get("by_type", {})

    if report.get("pass_rate", 0) < 95.0:
        blocking.append(
            f"overall pass_rate {report.get('pass_rate')}% < 95%")
    for t, gate in (("refusal", "拒答零幻觉 100%"), ("format", "格式合规 100%")):
        stat = by_type.get(t)
        if stat and stat["total"] > 0 and stat["pass"] < stat["total"]:
            blocking.append(
                f"{gate} 阻断: {t} {stat['pass']}/{stat['total']}")
    ms = by_type.get("multi_step")
    if ms and ms["total"] > 0:
        rate = ms["pass"] / ms["total"] * 100
        if rate < 80.0:
            print(f"[warn] 多步推理完成率 {rate:.0f}% < 80%（非阻断）")
    return (not blocking), blocking


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    golden_dir = Path(args[0]) if args else Path("scripts/evals/goldens")
    cases = load_goldens(golden_dir)
    if not cases:
        print(f"[ci_gate] no goldens in {golden_dir}")
        return 2

    import asyncio
    report = asyncio.run(run_all(cases))
    ok, blocking = check(report)

    print(f"[ci_gate] total={report['total']} pass_rate={report['pass_rate']}%")
    for msg in blocking:
        print(f"  BLOCK: {msg}")
    # CI 证据落盘（供 patrol / 简历指标位引用）
    out = Path("logs/evals_last_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"[ci_gate] report -> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
