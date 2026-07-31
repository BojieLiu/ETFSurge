from fastapi import APIRouter, Query
from typing import Any

from ..core.async_utils import run_sync
from ..fetchers.news_fetcher import fetch_research_reports
from ..services.market_data_hub import market_data_hub

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("/headlines")
async def headlines() -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_headlines, timeout=30)


@router.get("/macro")
async def macro() -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_macro)


@router.get("/global")
async def global_news() -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_global)


@router.get("/stock/{symbol}")
async def stock_news(symbol: str) -> list[dict[str, Any]]:
    return await run_sync(market_data_hub.get_news_stock, symbol)


@router.get("/research/{symbol}")
async def research(symbol: str) -> list[dict[str, Any]]:
    return await run_sync(fetch_research_reports, symbol)
