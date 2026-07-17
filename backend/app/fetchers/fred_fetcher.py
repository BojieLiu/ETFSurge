"""
FRED (Federal Reserve Economic Data) fetcher.

Official St. Louis Fed REST API for US macro data.
Free tier: 120 requests/minute. No proxy needed in China.

FRED series IDs used:
  VIXCLS   - CBOE Volatility Index
  DGS10    - 10-Year Treasury Constant Maturity Rate
  DFF      - Effective Federal Funds Rate
  CPIAUCSL - Consumer Price Index for All Urban Consumers
  PAYEMS   - Total Nonfarm Payrolls
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
_API_KEY = settings.fred_api_key

_TIMEOUT = 15


async def _fetch_series(series_id: str) -> float | None:
    """Fetch the most recent observation for a FRED series.

    Returns the value as float, or None on any error.
    """
    if not _API_KEY:
        logger.warning("FRED_API_KEY not configured")
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.get(
                _API_BASE,
                params={
                    "series_id": series_id,
                    "api_key": _API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
            )
        if resp.status_code != 200:
            logger.warning("FRED API error %d for %s", resp.status_code, series_id)
            return None
        data = resp.json()
        observations = data.get("observations", [])
        if not observations:
            logger.warning("FRED %s: no observations", series_id)
            return None
        value_str = observations[0].get("value", ".")
        if value_str == ".":
            logger.debug("FRED %s: value not available (.)", series_id)
            return None
        return float(value_str)
    except Exception as e:
        logger.warning("FRED %s fetch failed: %s", series_id, e)
        return None


async def fetch_vix() -> float | None:
    """VIX恐慌指数 (VIXCLS)"""
    return await _fetch_series("VIXCLS")


async def fetch_us_10y() -> float | None:
    """美债10Y收益率 % (DGS10)"""
    return await _fetch_series("DGS10")


async def fetch_fed_rate() -> float | None:
    """联邦基金利率 % (DFF)"""
    return await _fetch_series("DFF")


async def fetch_cpi() -> float | None:
    """消费者物价指数 (CPIAUCSL)"""
    return await _fetch_series("CPIAUCSL")


async def fetch_nfp() -> float | None:
    """非农就业人数 (PAYEMS, 千人)"""
    return await _fetch_series("PAYEMS")
