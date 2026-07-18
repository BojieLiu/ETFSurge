"""
中国国内市场数据聚合器 (China Market Data Aggregator)

多数据源实时行情获取，内部含 mootdx / Sina / QQ(Tencent) / akshare 四级降级。
数据源优先级 (由 SourceRegistry 熔断路由管理):
  A 股实时: mootdx → Sina → QQ(Tencent)
  A 股K线:  mootdx → Sina
  HK 实时:  Sina → QQ
  指数:     mootdx → QQ
  期货:     akshare
  基金净值:  akshare
  历史K线:   mootdx/Sina (A) / akshare (HK/US)
"""

from typing import Any
from ..utils.proxy import no_proxy
from ..utils.decode import decode_df as _decode_df
from ..core.ttl import CACHE_TTL
from ..services.source_registry import registry

ASSET_TYPES = {
    "A": "A股ETF", "HK": "港股ETF", "US": "美股ETF",
    "gold": "黄金", "oil": "原油", "silver": "白银",
}


# ── HTTP session helper ─────────────────────────────────────────

def _session():
    import requests as _req
    s = _req.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})
    return s


# ── mootdx helper ────────────────────────────────────────────────

import contextlib
import threading

_MOOTDX_CLIENT = None
_MOOTDX_LOCK = threading.Lock()

# mootdx socket read/write timeout (must be less than the async
# _call timeout=8 so mootdx errors out before asyncio cancels)
_MOOTDX_TIMEOUT = 6
# max seconds to wait for the mootdx lock before falling back
_MOOTDX_LOCK_TIMEOUT = 10


def _mootdx():
    global _MOOTDX_CLIENT
    if _MOOTDX_CLIENT is None:
        from mootdx.quotes import Quotes
        _MOOTDX_CLIENT = Quotes.factory(market='std', timeout=_MOOTDX_TIMEOUT)
    return _MOOTDX_CLIENT


@contextlib.contextmanager
def _mootdx_locked():
    """Acquire _MOOTDX_LOCK with timeout to prevent cascading blockage.

    When a previous mootdx call hangs (holding the lock), this will
    time out after _MOOTDX_LOCK_TIMEOUT seconds and let the caller
    fall through to the next data-source tier instead of blocking
    the entire worker thread indefinitely.
    """
    if not _MOOTDX_LOCK.acquire(timeout=_MOOTDX_LOCK_TIMEOUT):
        raise TimeoutError("mootdx lock acquisition timed out")
    try:
        yield
    finally:
        _MOOTDX_LOCK.release()


def _mootdx_realtime(symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []
    try:
        with _mootdx_locked():
            client = _mootdx()
            df = client.quotes(symbol=symbols)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            code = str(row.get("code", ""))
            price = float(row.get("price", 0) or 0)
            last_close = float(row.get("last_close", 0) or 0)
            change_pct = round((price - last_close) / last_close * 100, 2) if last_close else 0
            results.append({
                "symbol": code,
                "name": "",
                "price": price,
                "change_pct": change_pct,
                "change_amount": round(price - last_close, 2),
                "volume": float(row.get("volume", 0) or 0),
                "turnover": float(row.get("amount", 0) or 0),
                "asset_type": "A",
            })
        return results
    except Exception:
        return []


def _mootdx_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    freq_map = {"daily": 9, "weekly": 5, "monthly": 6}
    freq = freq_map.get(period, 9)
    count = 500
    try:
        with _mootdx_locked():
            client = _mootdx()
            df = client.bars(symbol=symbol, frequency=freq, start=0, count=count)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "日期": str(row.get("date", "")),
                "开盘": float(row.get("open", 0)),
                "最高": float(row.get("high", 0)),
                "最低": float(row.get("low", 0)),
                "收盘": float(row.get("close", 0)),
                "成交量": float(row.get("volume", 0) or 0),
            })
        return results
    except Exception:
        return []


# ── Sina helper ──────────────────────────────────────────────────

def _exchange(symbol: str) -> str:
    if symbol.startswith("6") or symbol.startswith("51") or symbol.startswith("5"):
        return "sh"
    return "sz"


def _sina_realtime(symbols: list[str], asset_type: str) -> list[dict[str, Any]]:
    if not symbols:
        return []
    try:
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        results = []
        for sym in symbols:
            pref = _exchange(sym)
            try:
                r = s.get(f"https://hq.sinajs.cn/list={pref}{sym}", timeout=10)
                text = r.text.strip()
                if "=" not in text or '"' not in text:
                    continue
                parts = text.split('"')[1].split(",")
                if len(parts) < 30:
                    continue
                prev_close = float(parts[2]) if parts[2] else 0
                price = float(parts[3]) if parts[3] else 0
                results.append({
                    "symbol": sym, "name": parts[0],
                    "price": price,
                    "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close else 0,
                    "change_amount": round(price - prev_close, 2) if prev_close else 0,
                    "volume": float(parts[8]) if parts[8] else 0,
                    "turnover": float(parts[9]) if parts[9] else 0,
                    "asset_type": asset_type,
                })
            except Exception:
                continue
        return results
    except Exception:
        return []


def _sina_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    scale = {"daily": "240", "weekly": "1200", "monthly": "7200", "15m": "15", "30m": "30", "1h": "60"}.get(period, "240")
    try:
        import json
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        pref = _exchange(symbol)
        url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={pref}{symbol}&scale={scale}&datalen=240")
        r = s.get(url, timeout=15)
        data = json.loads(r.text)
        if isinstance(data, list) and data:
            return [{
                "日期": d["day"], "开盘": float(d["open"]), "最高": float(d["high"]),
                "最低": float(d["low"]), "收盘": float(d["close"]), "成交量": float(d.get("volume", 0)),
            } for d in data if isinstance(d, dict)]
    except Exception:
        pass
    return []


def _resample_4h(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i in range(0, len(rows), 4):
        grp = rows[i:i + 4]
        if not grp:
            continue
        out.append({
            "日期": grp[0]["日期"],
            "开盘": float(grp[0]["开盘"]),
            "最高": max(float(r["最高"]) for r in grp),
            "最低": min(float(r["最低"]) for r in grp),
            "收盘": float(grp[-1]["收盘"]),
            "成交量": sum(float(r["成交量"]) for r in grp),
        })
    return out


def _akshare_intraday_history(symbol: str, period_min: int = 60) -> list[dict[str, Any]]:
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=str(period_min), start_date=start, end_date=end, adjust="")
        if df is None or df.empty:
            return []
        rename = {"时间": "日期", "开盘": "开盘", "最高": "最高", "最低": "最低", "收盘": "收盘", "成交量": "成交量"}
        df = df.rename(columns=rename)
        keep = ["日期", "开盘", "最高", "最低", "收盘", "成交量"]
        df = df[[c for c in keep if c in df.columns]]
        _decode_df(df)
        return df.to_dict(orient="records")
    except Exception:
        return []


# ── QQ (Tencent) helper ──────────────────────────────────────────

def _tencent_realtime(symbols: list[str], asset_type: str) -> list[dict[str, Any]]:
    if not symbols:
        return []
    try:
        codes = ",".join(f"{_exchange(s)}{s}" for s in symbols)
        s = _session()
        r = s.get(f"http://qt.gtimg.cn/q={codes}", timeout=10)
        if not r.text:
            return []
        results = []
        for line in r.text.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            parts = line.split('"')[1].split("~") if '"' in line else []
            if len(parts) < 38:
                continue
            code = parts[2]
            price = float(parts[3]) if parts[3] else 0
            prev_close = float(parts[4]) if parts[4] else 0
            results.append({
                "symbol": code, "name": parts[1],
                "price": price,
                "change_pct": float(parts[32]) if parts[32] else 0,
                "change_amount": float(parts[31]) if parts[31] else 0,
                "volume": float(parts[6]) if parts[6] else 0,
                "turnover": float(parts[37]) if parts[37] else 0,
                "asset_type": asset_type,
            })
        return results
    except Exception:
        return []


# ── New ETF data source functions ──────────────────────────


def fetch_etf_net_value(symbol: str) -> dict | None:
    """获取ETF实时IOPV（参考净值）和折溢价。

    从Sina ETF行情中解析最新价与IOPV计算折溢价率。
    返回: { "nav": float, "price": float, "premium_discount": float }
    失败返回 None。
    """
    try:
        import urllib.request
        url = f"http://hq.sinajs.cn/list=sh{symbol}"
        req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn"})
        resp = urllib.request.urlopen(req, timeout=5)
        text = resp.read().decode("gbk")
        # Sina ETF format, fields include IOPV data
        if not text or '"' not in text:
            return None
        parts = text.split('"')[1].split(",")
        if len(parts) < 10:
            return None
        # parts[3] = current price, parts[8] = IOPV (reference NAV)
        price = float(parts[3]) if parts[3] else None
        nav = float(parts[8]) if parts[8] else None
        if price and nav and nav > 0:
            return {
                "nav": nav,
                "price": price,
                "premium_discount": (price - nav) / nav,
            }
    except Exception:
        pass
    return None


def fetch_etf_shares_outstanding(symbol: str) -> dict | None:
    """获取ETF份额数据（用于规模变化率计算）。

    使用 akshare fund_etf_hist_em 获取份额数据。
    返回: { "total_shares": float, "shares_change_20d": float }
    失败返回 None。
    """
    try:
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date="20200101", end_date="20500101", adjust="")
        if df is None or df.empty:
            return None
        cols = [c for c in df.columns if "份额" in str(c) or "规模" in str(c)]
        if not cols:
            return None
        shares_col = cols[0]
        latest = float(df.iloc[-1][shares_col])
        if len(df) >= 20:
            prev = float(df.iloc[-20][shares_col])
            change_20d = (latest - prev) / prev if prev > 0 else 0.0
        else:
            change_20d = 0.0
        return {"total_shares": latest, "shares_change_20d": change_20d}
    except Exception:
        pass
    return None


# ── Public API ───────────────────────────────────────────────────

def fetch_a_stock_realtime(symbol: str | None = None) -> list[dict[str, Any]]:
    with no_proxy():
        if not symbol:
            return []
        items = _mootdx_realtime([symbol])
        if items and items[0].get("price"):
            return items
        items = _sina_realtime([symbol], "A")
        return items


def fetch_a_stock_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """Batch fetch A-share quotes — used by _build_price_map."""
    with no_proxy():
        items = _mootdx_realtime(symbols)
        if len(items) == len(symbols) and all(i.get("price") for i in items):
            return items
        # Fallback: QQ (Tencent) batch API
        items = _tencent_realtime(symbols, "A")
        if len(items) == len(symbols) and all(i.get("price") for i in items):
            return items
        # Final fallback: Sina per-symbol
        return _sina_realtime(symbols, "A")


def _em_hk_realtime(symbols: list[str]) -> list[dict[str, Any]]:
    """东方财富港股实时行情（akshare stock_hk_spot_em），按 symbols 过滤。"""
    try:
        with no_proxy():
            import akshare as ak
            df = ak.stock_hk_spot_em()
        _decode_df(df)
        if df is None or df.empty:
            return []
        sym_set = set(symbols)
        results = []
        for _, row in df.iterrows():
            code = str(row.get("代码", row.get("symbol", "")))
            if code not in sym_set:
                continue
            try:
                price = float(row.get("最新价", 0) or 0)
            except (ValueError, TypeError):
                price = 0
            try:
                chg = float(row.get("涨跌幅", 0) or 0)
            except (ValueError, TypeError):
                chg = 0
            results.append({
                "symbol": code,
                "name": str(row.get("名称", row.get("name", ""))),
                "price": price,
                "change_pct": round(chg, 2),
                "change_amount": round(price * chg / 100, 2) if chg else 0,
                "volume": float(row.get("成交量", 0) or 0),
                "turnover": float(row.get("成交额", 0) or 0),
                "asset_type": "HK",
            })
        return results
    except Exception:
        return []


def fetch_hk_stock_realtime(symbol: str | None = None) -> list[dict[str, Any]]:
    """港股实时行情：Sina → Tencent(QQ) → 东方财富三级降级。"""
    if not symbol:
        return []
    with no_proxy():
        items = _sina_realtime([symbol], "HK")
        if items and items[0].get("price"):
            return items
        items = _tencent_realtime([symbol], "HK")
        if items and items[0].get("price"):
            return items
        # EM HK spot 是全量接口，本地过滤
        items = _em_hk_realtime([symbol])
        return items


def fetch_futures_realtime() -> list[dict[str, Any]]:
    try:
        with no_proxy():
            import akshare as ak
            df = ak.futures_foreign_commodity_realtime()
        _decode_df(df)
        results = []
        for _, row in df.iterrows():
            try:
                price = float(row.get("当前价", 0) or 0)
            except (ValueError, TypeError):
                price = 0
            try:
                change_pct = float(row.get("涨跌幅", 0) or 0)
            except (ValueError, TypeError):
                change_pct = 0
            results.append({
                "symbol": str(row.get("商品", "")),
                "name": str(row.get("名称", row.get("商品", ""))),
                "price": price,
                "change_pct": change_pct,
                "change_amount": 0,
                "volume": 0,
                "turnover": 0,
                "asset_type": "futures",
            })
        return results
    except Exception:
        return []


def fetch_index_realtime() -> list[dict[str, Any]]:
    """Fetch major market indices via mootdx; fallback QQ."""
    with no_proxy():
        indices = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
                   "000688": "科创50", "000300": "沪深300", "000016": "上证50",
                   "000905": "中证500", "000852": "中证1000"}
        codes = list(indices.keys())
        try:
            with _mootdx_locked():
                client = _mootdx()
                df = client.index(symbol=codes)
            if df is not None and not df.empty:
                results = []
                for _, row in df.iterrows():
                    code = str(row.get("code", ""))
                    price = float(row.get("price", 0) or 0)
                    prev = float(row.get("last_close", 0) or 0)
                    results.append({
                        "symbol": code, "name": indices.get(code, ""),
                        "price": price,
                        "change_pct": round((price - prev) / prev * 100, 2) if prev else 0,
                        "change_amount": round(price - prev, 2),
                        "volume": float(row.get("volume", 0) or 0),
                        "turnover": 0,
                        "asset_type": "index",
                    })
                return results
        except Exception:
            pass

        return _tencent_realtime(codes, "index")


def fetch_fund_nav(symbol: str) -> tuple[float, float] | None:
    """获取场外开放式基金的单位净值与日涨跌幅（用于 OTC 联接基金）。

    返回 (unit_net_value, daily_growth_pct)，取最新一条记录；不可用返回 None。
    """
    try:
        with no_proxy():
            import akshare as ak
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值")
        _decode_df(df)
        if df is None or len(df) == 0:
            return None
        last = df.iloc[-1]
        nav = float(last.get("单位净值") or last.get("unit_net_value") or 0)
        chg = float(last.get("日增长率") or last.get("daily_growth_rate") or 0)
        if nav:
            return (nav, round(chg, 2))
        return None
    except Exception:
        return None


def fetch_index_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """获取指数历史 K 线（日线/周线/月线），使用 akshare stock_zh_index_daily。
    akshare 返回格式: 日期,开盘,最高,最低,收盘,成交量,成交额。"""
    try:
        import akshare as ak
        import pandas as pd
        # 处理已带前缀的 symbol（如 sh000001、sz399001）
        code = symbol[2:] if symbol.startswith(("sh", "sz", "bj")) else symbol
        with no_proxy():
            df = ak.stock_zh_index_daily(symbol=f"sh{code}")
        if df is None or df.empty:
            return []
        rename = {"date": "日期", "open": "开盘", "high": "最高", "low": "最低",
                  "close": "收盘", "volume": "成交量"}
        df = df.rename(columns=rename)
        df["日期"] = df["日期"].astype(str)
        # akshare 返回顺序从旧到新，与系统中其他源一致
        keep = ["日期", "开盘", "最高", "最低", "收盘", "成交量"]
        df = df[[c for c in keep if c in df.columns]]
        _decode_df(df)
        return df.to_dict(orient="records")
    except Exception:
        return []


def fetch_history(symbol: str, asset_type: str = "A", period: str = "daily") -> list[dict[str, Any]]:
    with no_proxy():
        if asset_type == "index":
            return fetch_index_history(symbol, period)
        if asset_type == "A":
            if period in ("15m", "30m", "1h"):
                # Sina K 线为主力（稳定），akshare eastmoney 分钟线兜底
                rows = _sina_history(symbol, period)
                if not rows:
                    rows = _akshare_intraday_history(symbol, int(period[:-1]))
                return rows
            if period == "4h":
                rows = _sina_history(symbol, "1h")  # 60 分钟线
                if not rows:
                    rows = _akshare_intraday_history(symbol, 60)
                return _resample_4h(rows)
            items = _mootdx_history(symbol, period)
            if items:
                return items
            return _sina_history(symbol, period)
        if asset_type in ("HK", "US"):
            return _fetch_akshare_history(symbol, asset_type, period)
        return []


def _fetch_akshare_history(symbol: str, asset_type: str, period: str) -> list[dict[str, Any]]:
    try:
        import akshare as ak
        import pandas as pd
        m = {"A": ak.stock_zh_a_hist, "HK": ak.stock_hk_hist, "US": ak.stock_us_hist}
        fn = m.get(asset_type)
        if not fn:
            return []
        df = fn(symbol=symbol, period=period, adjust="qfq") if asset_type == "A" else fn(symbol=symbol, period=period)
        if isinstance(df, pd.DataFrame) and not df.empty:
            _decode_df(df)
            return df.to_dict(orient="records")
        return []
    except Exception:
        return []


def search_etf(keyword: str) -> list[dict[str, Any]]:
    try:
        with no_proxy():
            import akshare as ak
            df = ak.fund_etf_spot_em()
        _decode_df(df)
        if keyword:
            mask = df["代码"].str.contains(keyword, na=False) | df["名称"].str.contains(keyword, na=False)
            df = df[mask]
        results = []
        for _, row in df.head(20).iterrows():
            results.append({
                "symbol": row["代码"], "name": row["名称"],
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "asset_type": "A",
            })
        return results
    except Exception:
        return []


def fetch_etf_list() -> list[dict[str, Any]]:
    """返回全量 ETF 列表（代码/名称/最新价/涨跌幅），用于本地关键字过滤。
    Sina 列表接口快（~3s），akshare spot 兜底（慢但稳定）。"""
    try:
        with no_proxy():
            import akshare as ak
            df = ak.fund_etf_category_sina(symbol="ETF基金")
        cols = list(df.columns)
        if len(cols) < 5:
            raise ValueError("unexpected etf list columns")
        code_col, name_col, price_col, pct_col = cols[0], cols[1], cols[2], cols[4]
        results = []
        for _, row in df.iterrows():
            raw = str(row[code_col])
            symbol = raw[2:] if raw[:2].lower() in ("sz", "sh") else raw
            try:
                price = float(row[price_col] or 0)
            except (ValueError, TypeError):
                price = 0
            try:
                change_pct = float(row[pct_col] or 0)
            except (ValueError, TypeError):
                change_pct = 0
            results.append({
                "symbol": symbol,
                "name": str(row[name_col]),
                "price": price,
                "change_pct": change_pct,
                "asset_type": "A",
            })
        return results
    except Exception:
        # 兜底：慢但稳定的 akshare spot 接口
        try:
            with no_proxy():
                import akshare as ak
                df = ak.fund_etf_spot_em()
            _decode_df(df)
            return [
                {
                    "symbol": str(row["代码"]),
                    "name": str(row["名称"]),
                    "price": float(row.get("最新价", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "asset_type": "A",
                }
                for _, row in df.iterrows()
            ]
        except Exception:
            return []



