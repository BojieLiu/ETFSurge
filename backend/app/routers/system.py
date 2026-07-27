"""System routes — warmup status, startup diagnostics, etc."""

import time
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/system", tags=["system"])


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
    return {
        "warmup": warmup,
        "all_done": all_done,
        "elapsed_seconds": round(elapsed, 1),
    }
