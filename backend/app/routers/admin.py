"""Admin 工具路由 — token 用量监控等。"""

from fastapi import APIRouter, Query

from ..monitor.token_usage import token_store

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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
