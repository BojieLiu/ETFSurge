"""
Free US market data sources: Alpha Vantage + Finnhub.

Both require a free API key stored in environment variables:
  - ALPHAVANTAGE_API_KEY
  - FINNHUB_API_KEY

Each function is self-contained, returns None on any failure,
and uses the standard no_proxy + timeout pattern.
"""

from typing import Any
from ..utils.proxy import no_proxy

_ALPHAV_BASE = "https://www.alphavantage.co/query"
_FINNHUB_BASE = "https://finnhub.io/api/v1"

_TIMEOUT = 8


# ── helpers ──────────────────────────────────────────────────────


def _apikey(name: str) -> str | None:
    import os

    return os.environ.get(name) or None


# ── Alpha Vantage ────────────────────────────────────────────────


def fetch_alphav_realtime(symbol: str) -> dict[str, Any] | None:
    """Alpha Vantage 实时行情（5min 延迟的日内数据取最新一条）。

    免费限制：5 calls/min, 500 calls/day
    API key: ALPHAVANTAGE_API_KEY
    """
    key = _apikey("ALPHAVANTAGE_API_KEY")
    if not key:
        return None
    import requests

    try:
        with no_proxy():
            url = (
                f"{_ALPHAV_BASE}"
                f"?function=TIME_SERIES_INTRADAY"
                f"&symbol={symbol}"
                f"&interval=5min"
                f"&apikey={key}"
            )
            r = requests.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        series = data.get("Time Series (5min)")
        if not series:
            return None
        # 取最新一条（字典 key 按时间排序，取第一条）
        latest_key = sorted(series.keys(), reverse=True)[0]
        latest = series[latest_key]
        price = float(latest.get("4. close", 0) or 0)
        if not price:
            return None
        open_price = float(latest.get("1. open", 0) or 0)
        change_pct = round((price - open_price) / open_price * 100, 2) if open_price else 0.0
        return {
            "symbol": symbol.upper(),
            "name": "",
            "price": price,
            "change_pct": change_pct,
            "change_amount": round(price - open_price, 2),
            "volume": float(latest.get("5. volume", 0) or 0),
            "asset_type": "US",
        }
    except Exception:
        return None


def fetch_alphav_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """Alpha Vantage 没有批量接口，逐个调用。"""
    results = []
    for sym in symbols:
        item = fetch_alphav_realtime(sym)
        if item:
            results.append(item)
    return results


# ── Finnhub ──────────────────────────────────────────────────────


def fetch_finnhub_realtime(symbol: str) -> dict[str, Any] | None:
    """Finnhub 实时行情（quote 端点）。

    免费限制：60 calls/min
    API key: FINNHUB_API_KEY
    """
    key = _apikey("FINNHUB_API_KEY")
    if not key:
        return None
    import requests

    try:
        with no_proxy():
            url = f"{_FINNHUB_BASE}/quote?symbol={symbol}&token={key}"
            r = requests.get(url, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        quote = r.json()
        price = quote.get("c")
        if price is None or price == 0:
            return None
        prev_close = quote.get("pc", 0) or 0
        change = quote.get("d", 0) or 0
        change_pct = quote.get("dp", 0) or 0
        return {
            "symbol": symbol.upper(),
            "name": "",
            "price": float(price),
            "change_pct": round(float(change_pct), 2),
            "change_amount": round(float(change), 2),
            "volume": 0,
            "asset_type": "US",
        }
    except Exception:
        return None


def fetch_finnhub_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """Finnhub 也没有批量接口，逐个调用。"""
    results = []
    for sym in symbols:
        item = fetch_finnhub_realtime(sym)
        if item:
            results.append(item)
    return results
