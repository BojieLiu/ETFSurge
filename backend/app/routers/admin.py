"""Admin 工具路由 — token 用量监控 / 数据源健康 / 事件记录等。"""

from fastapi import APIRouter, Query

from ..monitor.token_usage import token_store
from ..monitor.source_events import source_event_store
from ..services.source_registry import registry

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Token Usage (existing) ──────────────────────────────────────


@router.get("/token-usage")
async def get_token_usage():
    """返回 DeepSeek token 使用统计（按 function 聚合 + 时间窗口）。"""
    return await token_store.summary()


@router.get("/token-usage/timeseries")
async def get_token_timeseries(
    granularity: str = Query("day", description="聚合粒度: hour / day / month"),
    days: int = Query(30, description="按天时: 最近 N 天", ge=1, le=365),
    months: int = Query(12, description="按月时: 最近 N 月", ge=1, le=60),
    hours: int = Query(48, description="按小时时: 最近 N 小时", ge=1, le=720),
):
    """返回 DeepSeek token 按小时/天/月的时间序列，供前端图表展示。"""
    if granularity == "month":
        return {
            "granularity": "month",
            "series": await token_store.timeseries(days=months, granularity="month"),
        }
    if granularity == "hour":
        return {
            "granularity": "hour",
            "hours": hours,
            "series": await token_store.timeseries(granularity="hour", hours=hours),
        }
    return {
        "granularity": "day",
        "days": days,
        "series": await token_store.timeseries(days=days, granularity="day"),
    }


@router.get("/token-usage/failures")
async def get_token_failures(
    limit: int = Query(50, description="返回最近 N 条失败记录", ge=1, le=200),
):
    """返回最近失败的 DeepSeek 调用记录（含错误信息）。"""
    return {"failures": await token_store.recent_failures(limit=limit)}


# ── Source Health Monitoring (new) ──────────────────────────────


@router.get("/sources/health")
async def get_sources_health():
    """返回所有注册数据源的当前健康状态概览。"""
    states = registry.get_states()
    import time
    now = time.time()
    result = []
    for name, h in states.items():
        import threading
        # Access health state via thread-safe snapshot
        with h._lock:
            result.append({
                "name": name,
                "available": now >= h._cool_until,
                "failures": h._failures,
                "cooldown_remaining": max(0.0, h._cool_until - now),
                "failure_threshold": h.failure_threshold,
                "cooldown_secs": h.cooldown,
            })
    return result


@router.get("/sources/events/timeline")
async def get_source_events_timeline(
    hours: float = Query(1, description="回溯小时数", ge=0.1, le=168),
):
    """返回数据源事件的时间线（按分钟聚合成功/失败计数）。"""
    return await source_event_store.timeline(hours=hours)


@router.get("/sources/events/failures")
async def get_source_events_failures(
    limit: int = Query(10, description="返回最近 N 条失败事件", ge=1, le=100),
):
    """返回最近的数据源失败事件。"""
    return await source_event_store.recent_failures(limit=limit)


@router.get("/sources/circuit-breakers")
async def get_source_circuit_breakers():
    """返回所有注册数据源的熔断器状态。"""
    return registry.circuit_breaker_status()
