"""round36 §8-D1 可行性探针：设计管线分段耗时画像（只测不改）。

目的（docs/round36-B5-allocate-pipeline.md §8.2 R1 / §8.3-A 前置）：
    设计管线在事件循环内连续执行同步重活，冻结并发。本探针对真实管线
    （generate_enhanced_design，不含 LLM 报告段）做两级取证：
      1. 分段墙钟：对嫌疑调用点（factor matrix / allocate / 风控 /
         相关性两阶段 / regime）做 monkeypatch 计时累加；
      2. cProfile 函数级 top（cumtime），锁定 ≥0.5s 纯 CPU 段的 file:line。

用法（交易时段运行，数据源可达；单次探测克制原则）：
    cd backend && python scripts/probe_design_pipeline_profile.py

输出：backend/scripts/probe_design_pipeline_results.json
"""

from __future__ import annotations

import asyncio
import cProfile
import io
import json
import pstats
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT_PATH = Path(__file__).resolve().parent / "probe_design_pipeline_results.json"


async def main() -> int:
    import app.services.strategy_design as sd
    from app.services.market_data_hub import market_data_hub

    seg_times: dict[str, float] = defaultdict(float)
    seg_calls: dict[str, int] = defaultdict(int)
    originals: list[tuple[object, str, object]] = []

    def _wrap(obj: object, attr: str, label: str) -> None:
        fn = getattr(obj, attr)
        if not callable(fn):
            return

        def inner(*args, **kwargs):
            _t = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                seg_times[label] += time.monotonic() - _t
                seg_calls[label] += 1

        inner.__wrapped__ = fn  # type: ignore[attr-defined]
        setattr(obj, attr, inner)
        originals.append((obj, attr, fn))

    # 嫌疑点挂表（§8.2 R1：全部为循环上直跑的同步段）
    _wrap(market_data_hub, "get_factor_matrix", "hub.get_factor_matrix")
    _wrap(market_data_hub, "refresh", "await hub.refresh")
    _wrap(sd, "engine_allocate", "engine.allocate")
    _wrap(sd, "apply_risk_controls", "risk.apply_risk_controls")
    _wrap(sd, "_correlation_medians_for", "corr.medians(net+cpu)")
    _wrap(sd, "_correlation_matrix_for", "corr.matrix")
    _wrap(sd, "check_structure_reasonableness", "validate.structure_check")

    t0 = time.monotonic()
    prof = cProfile.Profile()
    prof.enable()
    try:
        result = await sd.generate_enhanced_design(capital=500000)
    finally:
        prof.disable()
        for obj, attr, fn in originals:
            setattr(obj, attr, fn)
    wall = time.monotonic() - t0

    stream = io.StringIO()
    stats = pstats.Stats(prof, stream=stream)
    stats.sort_stats("cumulative").print_stats(30)

    strategies = result.get("strategies", [])
    out = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wall_seconds": round(wall, 2),
        "pipeline_elapsed_seconds": (result.get("design_metadata") or {}).get("elapsed_seconds"),
        "strategies_count": len(strategies),
        "degradation": result.get("degradation", {}).get("mode"),
        "segments_seconds": {k: round(v, 3) for k, v in sorted(seg_times.items(), key=lambda kv: -kv[1])},
        "segment_calls": dict(seg_calls),
        "profile_top30_cumtime": stream.getvalue(),
        "loop_blocking_estimate_seconds": round(
            sum(v for k, v in seg_times.items() if not k.startswith("await")), 2
        ),
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[probe] wall={wall:.2f}s strategies={len(strategies)} degradation={out['degradation']}")
    print("[probe] segments (loop-blocking unless prefixed 'await'):")
    for k, v in sorted(seg_times.items(), key=lambda kv: -kv[1]):
        print(f"    {k:32s} {v:8.3f}s  x{seg_calls[k]}")
    print(f"[probe] results -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
