from typing import Any

from ..utils.proxy import no_proxy


def fetch_us_etf_realtime(symbol: str) -> dict[str, Any] | None:
    try:
        with no_proxy():
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            fast = ticker.fast_info
        price = getattr(fast, "last_price", None) or info.get("currentPrice") or info.get("regularMarketPrice", 0)
        prev_close = info.get("regularMarketPreviousClose", price)
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
        return {
            "symbol": symbol,
            "name": info.get("shortName", info.get("longName", symbol)),
            "price": float(price),
            "change_pct": round(float(change_pct), 2),
            "change_amount": float(price - prev_close),
            "volume": float(info.get("volume", 0)),
            "turnover": float(info.get("marketCap", 0)),
            "asset_type": "US",
        }
    except Exception:
        return None


def fetch_history(symbol: str, period: str = "1mo") -> list[dict[str, Any]]:
    try:
        with no_proxy():
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
        df = df.reset_index()
        return df.to_dict(orient="records")
    except Exception:
        return []
