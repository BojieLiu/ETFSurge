"""Alpha Vantage API fetcher — free tier (25 calls/day, 5 calls/min).

No proxy needed in China.
API docs: https://www.alphavantage.co/documentation/
"""

from typing import Any

from ..core.async_utils import run_in_thread
from ..config import settings

_API_BASE = "https://www.alphavantage.co/query"
_TIMEOUT = 10


def _get_apikey() -> str | None:
    key = settings.alphavantage_api_key
    if not key or key == "" or key.startswith("your_"):
        return None
    return key


def _request(params: dict[str, str]) -> dict[str, Any] | None:
    """Make an Alpha Vantage API request with timeout."""
    key = _get_apikey()
    if not key:
        return None
    import urllib.request
    import json
    params["apikey"] = key
    url = _API_BASE + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if "Error Message" in data or "Note" in data:
            return None
        return data
    except Exception:
        return None


def fetch_realtime(symbol: str) -> dict[str, Any] | None:
    """Fetch realtime quote from Alpha Vantage (GLOBAL_QUOTE).

    Args:
        symbol: Ticker symbol.

    Returns:
        Normalized dict or None.
    """
    def _p():
        data = _request({"function": "GLOBAL_QUOTE", "symbol": symbol})
        if not data or "Global Quote" not in data:
            return None
        gq = data["Global Quote"]
        try:
            close = float(gq.get("05. price", 0))
            prev = float(gq.get("08. previous close", 0) or 0)
            return {
                "symbol": symbol,
                "price": close,
                "change_pct": round(float(gq.get("10. change percent", "0").rstrip("%")), 2),
                "change_amount": round(float(gq.get("09. change", 0) or 0), 2),
                "volume": int(float(gq.get("06. volume", 0) or 0)),
                "previous_close": prev,
                "latest_trading_day": gq.get("07. latest trading day", ""),
            }
        except (ValueError, TypeError, KeyError):
            return None
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")


def fetch_daily(symbol: str, outputsize: str = "compact") -> list[dict[str, Any]] | None:
    """Fetch daily K-line history from Alpha Vantage (TIME_SERIES_DAILY).

    Args:
        symbol: Ticker symbol.
        outputsize: "compact" (latest 100 days) or "full" (up to 20 years).

    Returns:
        List of {date, open, high, low, close, volume} sorted oldest-first.
        None on error.
    """
    def _p():
        data = _request({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize,
        })
        if not data:
            return None
        series = data.get("Time Series (Daily)")
        if not series:
            return None
        result = []
        for date_str in sorted(series.keys()):
            day = series[date_str]
            try:
                result.append({
                    "date": date_str,
                    "open": float(day["1. open"]),
                    "high": float(day["2. high"]),
                    "low": float(day["3. low"]),
                    "close": float(day["4. close"]),
                    "volume": int(float(day.get("5. volume", 0) or 0)),
                })
            except (ValueError, TypeError, KeyError):
                continue
        return result
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")
