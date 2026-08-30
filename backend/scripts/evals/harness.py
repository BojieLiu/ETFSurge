"""金标集评估主入口（v7 §5.5 harness）。

流程：load goldens -> 逐题执行（工具调用或 plan 执行）-> rule_scorer 评分
-> 汇总 report。

题目执行器：
- quote/factor/format/refusal: 单工具调用（经 Executor 白名单执行器）
- multi_step: 执行 steps 数组（PlanStep 序列）经 AgentLoop

用法：
  cd backend && python -m scripts.evals.harness \
      --goldens scripts/evals/goldens --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.evals.scorers.rule_scorer import score_case  # noqa: E402


def load_goldens(golden_dir: Path, limit: int | None = None) -> list[dict]:
    """读全部 goldens/*.jsonl（P0: 10 条 demo）。"""
    cases: list[dict] = []
    for f in sorted(golden_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("//"):
                cases.append(json.loads(line))
    return cases[:limit] if limit else cases


async def run_single_tool(case: dict) -> dict:
    """单工具题：Executor 白名单执行器进程内直调 P0 handler。"""
    from app.agentic.executor import Executor
    from app.agentic.executor import load_all_tools

    registry = load_all_tools()
    allowed = {c for entry in registry.values() for c in _tools_of(entry)}
    ex = Executor(allowed_tools=allowed | {case["tool"]})
    return await ex.execute(case["tool"], case.get("arguments", {}))


def _tools_of(entry: dict) -> set[str]:
    """entry 形态兼容：{handler, server}（P1 load_all_tools）。"""
    return set(entry.get("tools", [])) if "tools" in entry else set()


async def run_multi_step(case: dict) -> dict:
    """多步题：PlanStep 序列经 AgentLoop（真护栏）执行。"""
    from app.agentic.agent_loop import AgentLoop, PlanStep
    from app.agentic.executor import Executor

    steps = [PlanStep(**s) for s in case.get("steps", [])]
    tools = {s.tool for s in steps}
    ex = Executor(allowed_tools=tools)
    loop = AgentLoop(planner=None, executor=ex, allowed_tools=tools,
                     profile=case.get("profile", "strategy_check"))
    report = await loop.run(steps, validate_output=True)
    return report.model_dump()


async def run_case(case: dict) -> dict:
    """执行一题 -> {payload, verdict, duration_ms}。"""
    t0 = time.monotonic()
    try:
        if case["type"] == "multi_step":
            payload = await run_multi_step(case)
        else:
            payload = await run_single_tool(case)
        verdict = score_case(case["type"], payload, case.get("expect", {}))
    except Exception as exc:  # noqa: BLE001
        payload = {"error": f"{type(exc).__name__}: {exc}"}
        verdict = "error"
    return {
        "id": case["id"],
        "type": case["type"],
        "question": case.get("question", ""),
        "verdict": verdict,
        "duration_ms": round((time.monotonic() - t0) * 1000, 1),
        "payload_sample": str(payload)[:200],
    }


async def run_all(cases: list[dict]) -> dict:
    """跑整批 -> 汇总 report dict。"""
    results = []
    for c in cases:
        results.append(await run_case(c))
    by_type: dict[str, dict[str, int]] = {}
    for r in results:
        t = by_type.setdefault(r["type"], {"pass": 0, "fail": 0, "error": 0, "total": 0})
        t[r["verdict"]] = t.get(r["verdict"], 0) + 1
        t["total"] += 1
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "pass")
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "by_type": by_type,
        "results": results,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evals harness (v7 §5.5)")
    parser.add_argument("--goldens", default="scripts/evals/goldens")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None, help="report json 输出路径")
    args = parser.parse_args(argv)

    cases = load_goldens(Path(args.goldens), args.limit)
    if not cases:
        print(f"[evals] no goldens found in {args.goldens}")
        return 2
    report = asyncio.run(run_all(cases))

    print(f"[evals] total={report['total']} passed={report['passed']} "
          f"pass_rate={report['pass_rate']}%")
    for t, stat in sorted(report["by_type"].items()):
        print(f"  {t:10s}: {stat['pass']}/{stat['total']} pass "
              f"({stat['fail']} fail, {stat['error']} error)")
    for r in report["results"]:
        if r["verdict"] != "pass":
            print(f"  FAIL {r['id']} ({r['type']}): {r['payload_sample'][:120]}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[evals] report -> {args.out}")
    return 0 if report["pass_rate"] >= 95.0 else 1


if __name__ == "__main__":
    sys.exit(main())
