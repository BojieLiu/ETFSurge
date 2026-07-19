"""Twelve Data API fetcher — free tier (800 calls/day), no proxy needed in China.

API docs: https://twelvedata.com/docs
"""

from typing import Any
import time

from ..core.async_utils import run_in_thread
from ..config import settings

_API_BASE = "https://api.twelvedata.com"
_TIMEOUT = 10


def _get_apikey() -> str | None:
    key = settings.twelvedata_api_key
    if not key or key == "" or key.startswith("your_"):
        return None
    return key


def _request(path: str, params: dict[str, str]) -> dict[str, Any] | None:
    """Make a Twelve Data API request with timeout, return parsed JSON or None."""
    key = _get_apikey()
    if not key:
        return None
    params["apikey"] = key
    import urllib.request
    import json
    url = f"{_API_BASE}{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "error":
            return None
        return data
    except Exception:
        return None


def fetch_realtime(symbol: str) -> dict[str, Any] | None:
    """Fetch realtime quote for a symbol. Returns normalized dict or None.

    Args:
        symbol: Ticker symbol (SPY, AAPL, GOLD, CL, etc.)

    Returns:
        dict with keys: symbol, price, change_pct, change_amount,
            volume, high, low, open, previous_close
        None on any error.
    """
    def _p():
        data = _request("/quote", {"symbol": symbol})
        if not data or not data.get("close"):
            return None
        try:
            close = float(data["close"])
            prev = float(data.get("previous_close", 0) or 0)
            chg = close - prev
            chg_pct = round(chg / prev * 100, 2) if prev else 0.0
            return {
                "symbol": data.get("symbol", symbol),
                "price": close,
                "change_pct": chg_pct,
                "change_amount": round(chg, 2),
                "volume": int(float(data.get("volume", 0) or 0)),
                "high": float(data.get("high", 0) or 0),
                "low": float(data.get("low", 0) or 0),
                "open": float(data.get("open", 0) or 0),
                "previous_close": prev,
            }
        except (ValueError, TypeError, KeyError):
            return None
    return run_in_thread(_p, timeout=_TIMEOUT)


def fetch_history(symbol: str, days: int = 60) -> list[dict[str, Any]] | None:
    """Fetch daily K-line history for a symbol.

    Args:
        symbol: Ticker symbol.
        days: Number of trading days (max ~5000 on free tier).

    Returns:
        List of {date, open, high, low, close, volume} dicts, oldest first.
        None on any error.
    """
    def _p():
        data = _request("/time_series", {
            "symbol": symbol,
            "interval": "1day",
            "outputsize": str(min(days, 5000)),
        })
        if not data or "values" not in data:
            return None
        values = data["values"]
        if not values:
            return None
        # Twelve Data returns newest-first; reverse to oldest-first
        result = []
        for v in reversed(values):
            try:
                result.append({
                    "date": v["datetime"],
                    "open": float(v["open"]),
                    "high": float(v["high"]),
                    "low": float(v["low"]),
                    "close": float(v["close"]),
                    "volume": int(float(v.get("volume", 0) or 0)),
                })
            except (ValueError, TypeError, KeyError):
                continue
        return result
    return run_in_thread(_p, timeout=_TIMEOUT)
