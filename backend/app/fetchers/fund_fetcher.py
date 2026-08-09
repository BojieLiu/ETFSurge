"""
天天基金 (EastMoney) OTC fund NAV fetcher.

Fetches unit net asset value (NAV) for Chinese OTC funds using the
EastMoney public API. No authentication required.

Endpoint: https://api.fund.eastmoney.com/f10/lsjz
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.async_utils import run_in_thread
# EM 源换 curl_cffi（round11 EM 根因路线 A：浏览器 TLS 指纹绕容器侧 EM 拦截）
from curl_cffi import requests as _cffi

logger = logging.getLogger(__name__)

_API_BASE = "https://api.fund.eastmoney.com/f10/lsjz"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
}
_TIMEOUT = 8


def _fetch_nav(symbol: str) -> dict[str, Any] | None:
    """Sync helper: call EastMoney API and parse NAV response."""
    url = f"{_API_BASE}?fundCode={symbol}&pageIndex=1&pageSize=1"
    try:
        resp = _cffi.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        data: dict[str, Any] = resp.json()
    except Exception as exc:
        logger.warning("[fund_fetcher] HTTP/JSON error for %s: %s", symbol, exc)
        return None

    # Navigate to the first record in LSJZList
    try:
        records = data.get("Data", {}).get("LSJZList", [])
        if not records:
            logger.warning("[fund_fetcher] %s: no LSJZList in response", symbol)
            return None
        record = records[0]
    except (AttributeError, IndexError, TypeError) as exc:
        logger.warning("[fund_fetcher] %s: unexpected response structure: %s", symbol, exc)
        return None

    # Extract unit NAV (DWJZ) and daily change % (JZZZL)
    try:
        nav_str = record.get("DWJZ")
        change_str = record.get("JZZZL")
        if not nav_str:
            logger.warning("[fund_fetcher] %s: missing DWJZ field", symbol)
            return None
        nav = float(nav_str)
        daily_change_pct = float(change_str) if change_str else 0.0
    except (ValueError, TypeError) as exc:
        logger.warning("[fund_fetcher] %s: parse error (DWJZ=%r, JZZZL=%r): %s",
                       symbol, record.get("DWJZ"), record.get("JZZZL"), exc)
        return None

    return {
        "nav": nav,
        "daily_change_pct": daily_change_pct,
    }


def fetch_fund_nav(symbol: str) -> dict[str, Any] | None:
    """Fetch OTC fund unit NAV from 天天基金.

    Args:
        symbol: Fund code, e.g. ``"110011"``.

    Returns:
        ``{"nav": float, "daily_change_pct": float}`` on success,
        or ``None`` on any error/timeout.

    All calls run through ``run_in_thread`` with 8s timeout.
    """
    return run_in_thread(_fetch_nav, symbol, timeout=_TIMEOUT, executor="long")
