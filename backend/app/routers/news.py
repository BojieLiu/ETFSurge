from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.async_utils import run_sync
from ..services.market_data_hub import market_data_hub

router = APIRouter(prefix="/api/v1/news", tags=["news"])

# F31 (round23 §2.4 A4): 冷启动/数据源熔断时 bucket 条数过少 → 响应头标记 partial，
# 前端提示「数据刷新中（部分数据）」而非静默上屏残缺列表（半成品不静默上屏）。
PARTIAL_THRESHOLD = 5


def _with_partial_flag(body: list[dict[str, Any]]) -> JSONResponse:
    """条数 < PARTIAL_THRESHOLD 视为不完整（正常 headlines/macro 均 ≥10 条）。"""
    partial = len(body) < PARTIAL_THRESHOLD
    return JSONResponse(
        content=body,
        headers={"X-News-Partial": "true" if partial else "false"},
    )


@router.get("/headlines")
async def headlines() -> JSONResponse:
    items = await run_sync(market_data_hub.get_news_headlines, timeout=30)
    return _with_partial_flag(items or [])


@router.get("/macro")
async def macro() -> JSONResponse:
    items = await run_sync(market_data_hub.get_news_macro)
    return _with_partial_flag(items or [])


@router.get("/global")
async def global_news() -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_global)


@router.get("/stock/{symbol}")
async def stock_news(symbol: str) -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_stock, symbol)


@router.get("/research/{symbol}")
async def research(symbol: str) -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_research_reports, symbol)
