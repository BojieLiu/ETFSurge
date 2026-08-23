"""
天天基金 (EastMoney) OTC fund NAV fetcher.

Fetches unit net asset value (NAV) for Chinese OTC funds using the
EastMoney public API. No authentication required.

Endpoint: https://api.fund.eastmoney.com/f10/lsjz
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from ..core.async_utils import run_in_thread

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
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data: dict[str, Any] = json.loads(raw)
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

    R106 (round34): 入口形态守卫——非纯 6 位数字（如映射脏值「黄金9999」、None、
    7 位码）直接返回 None，fail-fast 不发无效请求。旧实现 URL 含原始中文 → ascii
    编码异常 → WARNING 每 60-120s 周期重放（round34 §4.4）。
    """
    if not (isinstance(symbol, str) and symbol.isdigit() and len(symbol) == 6):
        logger.debug("[fund_fetcher] skip non-code symbol %r", symbol)
        return None
    return run_in_thread(_fetch_nav, symbol, timeout=_TIMEOUT, executor="long")
