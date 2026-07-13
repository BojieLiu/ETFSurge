import asyncio
from fastapi import APIRouter, Query
from typing import Any

from ..fetchers.news_fetcher import (
    fetch_news_headlines,
    fetch_stock_news,
    fetch_research_reports,
    fetch_macro_news,
    fetch_global_news,
)

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.get("/headlines")
async def headlines() -> list[dict[str, Any]]:
    return await asyncio.to_thread(fetch_news_headlines)


@router.get("/macro")
async def macro() -> list[dict[str, Any]]:
    return await asyncio.to_thread(fetch_macro_news)


@router.get("/global")
async def global_news() -> list[dict[str, Any]]:
    return await asyncio.to_thread(fetch_global_news)


@router.get("/stock/{symbol}")
async def stock_news(symbol: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(fetch_stock_news, symbol)


@router.get("/research/{symbol}")
async def research(symbol: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(fetch_research_reports, symbol)
