"""Finnhub API fetcher — free tier (60 calls/min), no proxy needed in China.

API docs: https://finnhub.io/docs/api
"""

from typing import Any

from ..core.async_utils import run_in_thread
from ..config import settings

_API_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 10


def _get_apikey() -> str | None:
    key = settings.finnhub_api_key
    if not key or key == "" or key.startswith("your_"):
        return None
    return key


def _request(path: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Make a Finnhub API request with timeout, return parsed JSON or None."""
    key = _get_apikey()
    if not key:
        return None
    import urllib.request
    import json
    url = f"{_API_BASE}{path}?token={key}"
    if params:
        url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def fetch_realtime(symbol: str) -> dict[str, Any] | None:
    """Fetch realtime quote from Finnhub.

    Args:
        symbol: Ticker symbol (SPY, AAPL, 0700.HK for HK stocks, ^IXIC for indices).

    Returns:
        Normalized dict or None.
    """
    def _p():
        data = _request("/quote", {"symbol": symbol})
        if not data or data.get("c") is None:
            return None
        try:
            close = float(data["c"])
            prev = float(data.get("pc", 0) or 0)
            return {
                "symbol": symbol,
                "price": close,
                "change_pct": round(float(data.get("dp", 0) or 0), 2),
                "change_amount": round(close - prev, 2),
                "high": float(data.get("h", 0) or 0),
                "low": float(data.get("l", 0) or 0),
                "open": float(data.get("o", 0) or 0),
                "previous_close": prev,
            }
        except (ValueError, TypeError, KeyError):
            return None
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")


def fetch_candles(symbol: str, resolution: str = "D") -> list[dict[str, Any]] | None:
    """Fetch candlestick K-line data from Finnhub.

    Args:
        symbol: Ticker symbol.
        resolution: "D" (daily), "W" (weekly), "M" (monthly), or minute int.

    Returns:
        List of {date, open, high, low, close, volume} sorted oldest-first.
        None on error.
    """
    def _p():
        import time as _time
        now = int(_time.time())
        start = now - 365 * 86400  # 1 year back
        data = _request("/stock/candle", {
            "symbol": symbol,
            "resolution": resolution,
            "from": str(start),
            "to": str(now),
        })
        if not data or data.get("s") != "ok":
            return None
        timestamps = data.get("t", [])
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])
        if not timestamps:
            return None
        from datetime import datetime
        result = []
        for i in range(len(timestamps)):
            try:
                result.append({
                    "date": datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d"),
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": int(float(volumes[i])),
                })
            except (ValueError, TypeError, IndexError):
                continue
        return result
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")
