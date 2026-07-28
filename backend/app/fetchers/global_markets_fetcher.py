"""Global Markets Fetcher -- consolidated module."""

from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ..core.async_utils import run_in_thread
from ..utils.proxy import no_proxy
from ..config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# --- em_global_fetcher.py: EM Global Index ---

# Map East Money symbols → (our_symbol, region, display_name)
EM_SYMBOL_MAP: dict[str, tuple[str, str, str]] = {
    # A股
    "000001": ("000001", "A股", "上证指数"),
    "399001": ("399001", "A股", "深证成指"),
    "399006": ("399006", "A股", "创业板指"),
    "000300": ("000300", "A股", "沪深300"),
    "000688": ("000688", "A股", "科创50"),
    # 港股
    "HSI":    ("^HSI",   "港股", "恒生指数"),
    "HSCEI":  ("^HSCE",  "港股", "恒生国企指数"),
    # 亚太
    "N225":   ("^N225",  "日经", "日经225"),
    "KS11":   ("^KS11",  "韩国", "韩国综合指数"),
    # 美股
    "SPX":    ("^GSPC",  "美股", "标普500"),
    "NDX":    ("^IXIC",  "美股", "纳斯达克"),  # EM uses NDX not IXIC
    "DJIA":   ("^DJI",   "美股", "道琼斯"),
    # 欧洲
    "FTSE":   ("^FTSE",  "欧洲", "英国富时100"),  # EM uses FTSE not UKX
    "GDAXI":  ("^GDAXI", "欧洲", "德国DAX"),
    "FCHI":   ("^FCHI",  "欧洲", "法国CAC40"),  # EM uses FCHI not CAC
    "SX5E":   ("^STOXX50E", "欧洲", "欧洲斯托克50"),
}

def fetch_all() -> dict[str, list[dict[str, Any]]]:
    """Fetch all global index quotes from East Money.

    Returns:
        Dict keyed by region (A股, 港股, 美股, 日经, 韩国, 欧洲),
        each value being a list of normalized index entries.
    """
    import akshare as ak

    try:
        with no_proxy():
            df = ak.index_global_spot_em()
    except Exception as e:
        logger.warning("[em_global] index_global_spot_em failed: %s", e)
        return {}
    if df is None or df.empty:
        logger.warning("[em_global] index_global_spot_em returned empty")
        return {}

    sym_col = df.columns[1]    # symbol (ASCII, e.g. 'GDAXI')
    price_col = df.columns[3]  # 最新价
    chg_amount_col = df.columns[4]  # 涨跌额
    chg_pct_col = df.columns[5]     # 涨跌幅

    from collections import defaultdict
    regions: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for _, row in df.iterrows():
        em_sym = str(row[sym_col]).strip()
        matched = EM_SYMBOL_MAP.get(em_sym)
        if not matched:
            continue

        our_sym, region, display_name = matched
        price = row[price_col]
        chg_pct = row[chg_pct_col]
        chg_amount = row[chg_amount_col]

        entry = {
            "symbol": our_sym,
            "name": display_name,
            "region": region,
            "asset_type": "index",
            "price": float(price) if price is not None and price != "-" else None,
            "change_pct": float(chg_pct) if chg_pct is not None and chg_pct != "-" else None,
            "change_amount": float(chg_amount) if chg_amount is not None and chg_amount != "-" else None,
            "available": True,
        }
        regions[region].append(entry)

    return dict(regions)


def _fetch_tencent_hk_indices() -> dict[str, dict[str, Any]]:
    """Fetch HK index quotes via Tencent (QQ) finance API.

    More real-time and accurate than Sina for HSTECH.
    API format: http://qt.gtimg.cn/q=hk{symbol}
    Returns dict keyed by our symbol, empty dict on failure.
    """
    import urllib.request
    import json as _json

    TENCENT_SYMBOL_MAP: dict[str, str] = {
        "HSI": "^HSI",
        "HSCEI": "^HSCE",
        "HSTECH": "^HSTECH",
    }
    DISPLAY_NAMES: dict[str, str] = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
        "^HSTECH": "恒生科技指数",
    }

    codes = list(TENCENT_SYMBOL_MAP.keys())
    qstr = ",".join(f"hk{c}" for c in codes)
    url = f"http://qt.gtimg.cn/q={qstr}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("gbk").strip()
    except Exception:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 33:
            continue
        raw_code = parts[2].strip()
        our_sym = TENCENT_SYMBOL_MAP.get(raw_code)
        if not our_sym:
            continue

        price_str = parts[3].strip()
        prev_close_str = parts[4].strip()
        change_str = parts[31].strip()
        change_pct_str = parts[32].strip()

        try:
            price = float(price_str) if price_str else None
            prev_close = float(prev_close_str) if prev_close_str else None
            change_amt = float(change_str) if change_str else None
            change_pct = float(change_pct_str) if change_pct_str else None
        except (ValueError, TypeError):
            continue

        if price is None or price == 0:
            continue

        result[our_sym] = {
            "symbol": our_sym,
            "name": DISPLAY_NAMES.get(our_sym, ""),
            "region": "港股",
            "asset_type": "index",
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amt,
            "available": True,
        }

    return result


def fetch_hk_indices() -> dict[str, dict[str, Any]]:
    """Fetch Hong Kong index quotes — Tencent (QQ) preferred, Sina HK fallback.

    Tencent API has real-time timestamps and is more accurate for HSTECH.
    Sina HK covers the same symbols as a backup.

    Returns:
        Dict keyed by ``our_symbol`` (e.g. ``^HSTECH``) → normalized entry.
        Empty dict on failure.
    """
    # Tier 1: Tencent (QQ) — 更实时、更准确
    tencent = _fetch_tencent_hk_indices()
    if tencent:
        return tencent

    # Tier 2: Sina HK (akshare) — 兜底
    import akshare as ak

    with no_proxy():
        df = ak.stock_hk_index_spot_sina()
    if df is None or df.empty:
        logger.warning("[hk_indices] all HK sources failed")
        return {}

    sym_col = df.columns[0]     # code
    price_col = df.columns[2]    # 最新价
    chg_amount_col = df.columns[3]  # 涨跌额
    chg_pct_col = df.columns[4]  # 涨跌幅

    HK_SYMBOL_MAP: dict[str, str] = {
        "HSI": "^HSI",
        "HSCEI": "^HSCE",
        "HSTECH": "^HSTECH",
    }
    DISPLAY_NAMES: dict[str, str] = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
        "^HSTECH": "恒生科技指数",
    }

    result: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = str(row[sym_col]).strip()
        our_sym = HK_SYMBOL_MAP.get(code)
        if not our_sym:
            continue

        price = row[price_col]
        chg_pct = row[chg_pct_col]
        chg_amount = row[chg_amount_col]

        result[our_sym] = {
            "symbol": our_sym,
            "name": DISPLAY_NAMES.get(our_sym, ""),
            "region": "港股",
            "asset_type": "index",
            "price": float(price) if price is not None and price != "-" else None,
            "change_pct": float(chg_pct) if chg_pct is not None and chg_pct != "-" else None,
            "change_amount": float(chg_amount) if chg_amount is not None and chg_amount != "-" else None,
            "available": True,
        }

    return result

# --- yfinance_fetcher.py: yfinance (DEPRECATED) ---

import os
def fetch_us_etf_realtime(symbol: str) -> dict[str, Any] | None:
    try:
        proxy = os.environ.get("YFINANCE_PROXY", "")
        if proxy:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            fast = ticker.fast_info
        else:
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
        proxy = os.environ.get("YFINANCE_PROXY", "")
        if proxy:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, proxy=proxy)
        else:
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
    如需代理，设置环境变量 YFINANCE_PROXY（如 http://127.0.0.1:7890）。
    """
    try:
        proxy = os.environ.get("YFINANCE_PROXY", "")
        if proxy:
            # 使用代理时不走 no_proxy
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d", proxy=proxy)
        else:
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

# --- alphavantage_fetcher.py: Alpha Vantage API ---

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

# --- twelvedata_fetcher.py: Twelve Data API ---

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
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")


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
    return run_in_thread(_p, timeout=_TIMEOUT, executor="long")

# --- finnhub_fetcher.py: Finnhub API ---

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

# --- tushare_fetcher.py: Tushare Pro ---

def _to_ts_code(symbol: str) -> str:
    """APP 代码 -> Tushare ts_code。支持 '600519' / 'sh600519' / '600519.SH'。"""
    s = symbol.strip().upper()
    if s.endswith((".SH", ".SZ")):
        return s
    if s.startswith("SH"):
        return f"{s[2:]}.SH"
    if s.startswith("SZ"):
        return f"{s[2:]}.SZ"
    if s[0] in ("6", "9"):
        return f"{s}.SH"
    if s[0] in ("0", "3"):
        return f"{s}.SZ"
    return f"{s}.SH"


def _pro():
    """惰性获取 Tushare pro 客户端;无 token 或导入失败返回 None。"""
    if not settings.tushare_token:
        logger.warning("[tushare_fetcher] TUSHARE_TOKEN not configured in .env - Tushare data source disabled")
        return None
    try:
        import tushare as ts

        ts.set_token(settings.tushare_token)
        return ts.pro_api()
    except Exception:
        return None


def fetch_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """A 股日线(用于增强分析/回测)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.daily(ts_code=_to_ts_code(ts_code), start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "开盘": float(row["open"]),
                "最高": float(row["high"]),
                "最低": float(row["low"]),
                "收盘": float(row["close"]),
                "成交量": float(row["vol"]),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_moneyflow(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """个股主力资金流(增强)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.moneyflow(ts_code=_to_ts_code(ts_code), start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "主力净流入": float(row.get("main_net_in", row.get("net_mf_amount", 0)) or 0),
                "主力净占比": float(row.get("main_net_per", 0) or 0),
                "散户净流入": float(row.get("ret_net_in", 0) or 0),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_north_money(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """沪深港通北向资金(增强)。低频、长缓存调用。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return []
        return [
            {
                "日期": str(row["trade_date"]),
                "北向净流入": float(row.get("north_money", row.get("hk_s2_north_money", 0)) or 0),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_stock_basic() -> list[dict[str, Any]]:
    """股票基础信息(行业/市场),用于丰富标的元数据。"""
    pro = _pro()
    if pro is None:
        return []
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,market,list_date")
        if df is None or df.empty:
            return []
        return [
            {
                "ts_code": str(row["ts_code"]),
                "symbol": str(row["symbol"]),
                "name": str(row["name"]),
                "industry": str(row.get("industry", "") or ""),
                "market": str(row.get("market", "") or ""),
            }
            for _, row in df.iterrows()
        ]
    except Exception:
        return []

# --- fred_fetcher.py: FRED async ---

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
