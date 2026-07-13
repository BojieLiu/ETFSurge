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


def fetch_index_realtime(symbol: str) -> dict[str, Any] | None:
    """获取全球指数(港股/美股/日经/韩国)实时点位与涨跌幅。

    优先使用近期历史 K 线计算(比 ticker.info 对指数更可靠)，失败返回 None。
    """
    try:
        with no_proxy():
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d")
        if df is None or len(df) == 0:
            return None
        closes = df["Close"].dropna()
        if len(closes) < 1:
            return None
        price = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
        change_pct = ((price - prev) / prev * 100) if prev else 0
        return {
            "symbol": symbol,
            "price": price,
            "change_pct": round(float(change_pct), 2),
            "asset_type": "index",
        }
    except Exception:
        return None
