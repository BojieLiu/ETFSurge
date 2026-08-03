"""System routes — warmup status, startup diagnostics, etc."""

import time
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _get_profiler_records() -> list:
    """PROFILE_WARMUP=1 时返回 WarmupProfiler 分段耗时记录，否则空列表。"""
    try:
        from ..profiling.warmup_profiler import get_warmup_profiler
        return list(get_warmup_profiler().records)
    except Exception:
        return []


@router.get("/warmup")
async def get_warmup_status(request: Request):
    """Return the status of each background warmup task.

    Frontend polls this endpoint after page load to determine
    whether the backend has finished initializing its data caches.
    """
    warmup = getattr(request.app.state, "warmup", {})
    startup_ts = getattr(request.app.state, "_startup_ts", time.time())
    elapsed = time.time() - startup_ts
    all_done = all(v.get("done", False) for v in warmup.values())
    # R6-F2 (round6 §十 R6-03): total_elapsed（毫秒）= profiler 分段耗时求和，
    # 与 warmup_timing.json 口径一致——verify_e2e A01 门禁读 total_elapsed，
    # 此前端点只返回 elapsed_seconds → 门禁恒走"未启用"分支恒 PASS。
    records = _get_profiler_records()
    total_elapsed = round(sum(r.duration_ms for r in records), 1) if records else 0
    return {
        "warmup": warmup,
        "all_done": all_done,
        "elapsed_seconds": round(elapsed, 1),
        "total_elapsed": total_elapsed,
    }
