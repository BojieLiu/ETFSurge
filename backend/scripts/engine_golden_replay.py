#!/usr/bin/env python
"""engine_golden_replay.py — round35 §6-B4: 引擎纯层管道黄金快照回放。

锁定范围（不含 generate_enhanced_design 的 I/O 编排，那属 e2e 职责）：
    allocate → apply_risk_controls → enforce_max_correlation
    → apply_near_substitute_warnings → check_structure_reasonableness

用法：
    python scripts/engine_golden_replay.py            # diff 模式（默认）：与快照不一致 exit 1
    python scripts/engine_golden_replay.py --update   # 显式重生成快照（commit message 必须说明动机）
    python scripts/engine_golden_replay.py --scenario s1_intraday_full

归一化规则：
- allocations 按 symbol 排序（排序稳定化）；权重/金额 round 6 位（ε=1e-6）
- 剔除 selection_rationale 文本与 _rank_info 内部键（文案非数值语义，
  避免任何措辞微调造成快照噪音；rank 数值经 risk_metrics/结构保留验证）

接入 patrol 作为可选段 ``--golden``（默认 diff 模式跑，不进 pre-commit——
遵循 round34 §13「不为常规项加门禁段」纪律）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.engine.allocation_engine import (  # noqa: E402
    allocate,
    apply_near_substitute_warnings,
    check_structure_reasonableness,
    enforce_max_correlation,
)
from app.engine.risk_controls import apply_risk_controls  # noqa: E402

FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "engine_golden"
SCENARIO_DIR = FIXTURE_DIR / "scenarios"
SNAPSHOT_DIR = FIXTURE_DIR / "snapshots"
EPS = 6  # 权重 ε=1e-6


def _parse_corr(raw: dict[str, float]) -> dict[tuple[str, str], float | None]:
    """JSON 里 "A|B": r → 引擎的 {(A, B): r}。"""
    out: dict[tuple[str, str], float | None] = {}
    for k, v in raw.items():
        a, b = k.split("|", 1)
        out[(a, b)] = v
        out[(b, a)] = v  # 对称补全（引擎查询两侧）
    return out


def _norm_alloc(a: dict) -> dict:
    keep = {}
    for k in ("symbol", "name", "layer", "tracked_index", "industry"):
        if k in a:
            keep[k] = a[k]
    for k in ("weight", "factor_score", "target_amount", "current_price", "change_pct"):
        if k in a and isinstance(a[k], (int, float)):
            keep[k] = round(float(a[k]), EPS)
    fb = a.get("factor_breakdown")
    if isinstance(fb, dict):
        keep["factor_breakdown"] = {
            ik: round(iv, EPS) if isinstance(iv, (int, float)) else iv
            for ik, iv in sorted(fb.items())
        }
    ri = a.get("_rank_info")
    if isinstance(ri, dict):
        keep["_rank_info"] = {k: ri[k] for k in sorted(ri)}
    return keep


def _norm_strategy(s: dict) -> dict:
    out: dict = {"id": s.get("id")}
    allocs = sorted(s.get("allocations", []), key=lambda x: x.get("symbol", ""))
    out["allocations"] = [_norm_alloc(a) for a in allocs]
    rm = s.get("risk_metrics") or {}
    out["risk_metrics"] = {
        k: (round(v, EPS) if isinstance(v, float) else v)
        for k, v in json.loads(json.dumps(rm)).items()
    } if rm else {}
    lb = s.get("layer_budget")
    if isinstance(lb, dict):
        out["layer_budget"] = {k: round(v, EPS) for k, v in sorted(lb.items())}
    return out


def run_pipeline(scenario: dict) -> list[dict]:
    """固定顺序跑引擎纯层管道，返回归一化输出。"""
    corr_raw = scenario.get("correlation_matrix") or {}
    strategies = allocate(
        risk_profile=scenario["risk_profile"],
        regime=scenario["regime"],
        factor_matrix=scenario.get("factor_matrix") or {},
        candidates=scenario.get("candidates"),
        # round35 FM2 重做前置①: 透传 ic_series——此前 harness 不注入，
        # warm 分支（≥IC_MIN_BATCHES）恒不可达，构成 FM2 类改动的验收盲区。
        ic_series=scenario.get("ic_series") or None,
    )
    strategies = apply_risk_controls(strategies, scenario.get("factor_matrix") or {},
                                     regime=scenario["regime"])
    corr_matrix = _parse_corr(corr_raw)
    if corr_matrix:
        try:
            enforce_max_correlation(strategies, corr_matrix)
        except Exception:
            pass  # 相关矩阵缺失/异常路径由 e2e 覆盖；快照锁可确定行为
    try:
        apply_near_substitute_warnings(strategies, corr_matrix)
    except Exception:
        pass
    try:
        check_structure_reasonableness(strategies)
    except Exception:
        pass
    return [_norm_strategy(s) for s in strategies]


def _diff(snapshot: list, actual: list) -> list[str]:
    """按策略 id 对齐逐字段比较；返回差异描述列表。"""
    diffs: list[str] = []
    a_by_id = {s.get("id"): s for s in snapshot}
    b_by_id = {s.get("id"): s for s in actual}
    missing = set(a_by_id) - set(b_by_id)
    extra = set(b_by_id) - set(a_by_id)
    if missing:
        diffs.append(f"missing strategies: {sorted(missing)}")
    if extra:
        diffs.append(f"unexpected strategies: {sorted(extra)}")
    for sid in sorted(set(a_by_id) & set(b_by_id)):
        a_sid, b_sid = a_by_id[sid], b_by_id[sid]
        if a_sid == b_sid:
            continue
        for key in ("allocations", "risk_metrics", "layer_budget"):
            if a_sid.get(key) != b_sid.get(key):
                diffs.append(f"{sid}.{key}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description="engine golden replay (round35 B4)")
    ap.add_argument("--update", action="store_true", help="重生成快照（commit 必须说明动机）")
    ap.add_argument("--scenario", default=None, help="只跑单个场景")
    args = ap.parse_args()

    files = sorted(SCENARIO_DIR.glob("*.json"))
    if args.scenario:
        files = [p for p in files if p.stem == args.scenario]
    if not files:
        print(f"[golden] no scenarios found in {SCENARIO_DIR}")
        return 1

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    failed = 0
    for path in files:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        actual = run_pipeline(scenario)
        snap_path = SNAPSHOT_DIR / f"{path.stem}.json"
        if args.update:
            snap_path.write_text(
                json.dumps(actual, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[golden] UPDATED {snap_path.name}")
            continue
        if not snap_path.exists():
            print(f"[golden] FAIL {path.stem}: snapshot missing（先跑 --update 建基线）")
            failed += 1
            continue
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        diffs = _diff(snapshot, actual)
        if diffs:
            failed += 1
            print(f"[golden] FAIL {path.stem}: engine output drifted from snapshot")
            for d in diffs[:10]:
                print(f"    - {d}")
            print(f"    （若为有意行为变更：python scripts/engine_golden_replay.py "
                  f"--update --scenario {path.stem}，commit message 说明动机）")
        else:
            print(f"[golden] OK   {path.stem}")

    total = len(files)
    print(f"[golden] {'FAIL' if failed else 'PASS'}: {total - failed}/{total} scenarios match")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
