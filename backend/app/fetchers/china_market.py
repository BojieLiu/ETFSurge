"""
中国国内市场数据聚合器 (China Market Data Aggregator)

多数据源实时行情获取，内部含 mootdx / Sina / QQ(Tencent) / akshare / 东方财富多级降级。
降级链已接入 SourceRegistry 熔断路由管理:
  A 股实时: mootdx → Sina                   (registry.route)
  A 股批量: mootdx → Tencent(QQ) → Sina     (registry.route)
  HK 实时:  Sina → Tencent(QQ) → 东方财富    (registry.route)
  A 股K线:  mootdx → Sina
  指数:     mootdx → QQ
  期货:     akshare
  基金净值:  akshare
  历史K线:   mootdx/Sina (A) / akshare (HK/US)
"""

from typing import Any
from ..core.logging import get_logger
from ..utils.proxy import no_proxy
from ..utils.decode import decode_df as _decode_df
from ..core.ttl import CACHE_TTL
from ..services.cache_service import sync_memory_cache
from ..services.source_registry import registry
from ..core.async_utils import run_in_thread
from ..fetchers import global_markets_fetcher
from ..fetchers import global_markets_fetcher
from ..fetchers import fund_fetcher

logger = get_logger(__name__)

ASSET_TYPES = {
    "A": "A股ETF", "HK": "港股ETF", "US": "美股ETF",
    "gold": "黄金", "oil": "原油", "silver": "白银",
}


# ── HTTP session helper (shared singleton, avoid per-call SSL handshake) ──

_shared_session = None


def _session():
    """Return the module-level shared requests.Session (lazy init).

    Reusing a session avoids repeated TCP/TLS handshakes (~100-300ms each)
    and enables HTTP keep-alive for Sina/QQ endpoints.
    """
    global _shared_session
    if _shared_session is None:
        import requests as _req
        s = _req.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})
        _shared_session = s
    return _shared_session


# ── mootdx helper ────────────────────────────────────────────────

import concurrent.futures as _cf

# mootdx 连接超时（Quotes.factory 的 TCP 连接超时）
_MOOTDX_TIMEOUT = 6
# mootdx 单次读操作超时（client.quotes / client.bars 的 socket read 超时）
# 使用 concurrent.futures 实现，防止 mootdx socket 读挂死线程池
_MOOTDX_READ_TIMEOUT = 8

_MOOTDX_CLIENT: "Quotes | None" = None
# 单线程 executor 用于 mootdx 读操作的超时保护
_MOOTDX_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mootdx")


def _run_mootdx_with_timeout(fn, timeout: int = _MOOTDX_READ_TIMEOUT):
    """在独立线程中执行 mootdx 读操作，带硬超时。

    解决 P0 问题：mootdx TCP socket read 可能无限挂起 → 线程池耗尽。
    asyncio.wait_for 无法中断同步阻塞的线程，因此用 ThreadPoolExecutor
    的 future.result(timeout=N) 实现硬超时。
    """
    future = _MOOTDX_EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout)
    except _cf.TimeoutError:
        logger.warning("[mootdx] read timed out after %ds — socket may be hung", timeout)
        # future 继续在后台运行，但已超时返回 None；线程最终会被 executor 回收
        return None


def _mootdx():
    """获取 mootdx 客户端（懒初始化，无需全局锁）。

    mootdx 的 socket 连接并非线程安全，但由于 SourceRegistry
    已提供 Sina/Tencent 降级通道，即使 mootdx 并发崩溃也能
    秒级熔断。去掉全局锁避免线程池被阻塞线程填满。
    """
    global _MOOTDX_CLIENT
    if _MOOTDX_CLIENT is None:
        from mootdx.quotes import Quotes
        _MOOTDX_CLIENT = Quotes.factory(market='std', timeout=_MOOTDX_TIMEOUT)
    return _MOOTDX_CLIENT


def _mootdx_realtime(symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []
    try:
        client = _mootdx()
        df = _run_mootdx_with_timeout(lambda: client.quotes(symbol=symbols))
        if df is None:
            logger.warning("_mootdx_realtime timed out for %s", symbols)
            return []
        if df.empty:
            logger.warning("_mootdx_realtime returned empty for %s", symbols)
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
        logger.warning("_mootdx_realtime exception for %s", symbols)
        return []


def _mootdx_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    freq_map = {"daily": 9, "weekly": 5, "monthly": 6}
    freq = freq_map.get(period, 9)
    count = 500
    try:
        client = _mootdx()
        df = _run_mootdx_with_timeout(lambda: client.bars(symbol=symbol, frequency=freq, start=0, count=count))
        if df is None:
            logger.warning("_mootdx_history timed out for %s (period=%s)", symbol, period)
            return _akshare_history_fallback(symbol, period)
        if df.empty:
            logger.warning("_mootdx_history returned empty for %s (period=%s)", symbol, period)
            # Fallback to akshare stock_zh_a_hist
            return _akshare_history_fallback(symbol, period)
        results = []
        for _, row in df.iterrows():
            results.append({
                # 中文 Key（兼容 indicators.py/chart_data）
                "日期": str(row.get("date", "")),
                "开盘": float(row.get("open", 0)),
                "最高": float(row.get("high", 0)),
                "最低": float(row.get("low", 0)),
                "收盘": float(row.get("close", 0)),
                "成交量": float(row.get("volume", 0) or 0),
                # 英文 Key（兼容 factor_registry._fetch_market_data）
                "day": str(row.get("date", "")),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": float(row.get("volume", 0) or 0),
            })
        return results
    except Exception:
        logger.warning("_mootdx_history exception for %s (period=%s)", symbol, period)
        return _akshare_history_fallback(symbol, period)


def _akshare_history_fallback(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """Fallback: 使用 akshare stock_zh_a_hist 获取 A 股历史 K 线。"""
    try:
        import pandas as pd
        def _p():
            import akshare as ak
            return ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq")
        df = run_in_thread(_p, timeout=15, executor="long")
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return []
        _decode_df(df)
        return df.to_dict(orient="records")
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
    # 上证指数需要 s_sh 前缀而非 sh/sz
    _SH_INDEXES = {"000001", "000300", "000688", "000016", "000905", "000852"}
    try:
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        results = []
        for sym in symbols:
            pref = "s_sh" if sym in _SH_INDEXES else _exchange(sym)
            try:
                r = s.get(f"https://hq.sinajs.cn/list={pref}{sym}", timeout=10)
                text = r.text.strip()
                if "=" not in text or '"' not in text:
                    continue
                parts = text.split('"')[1].split(",")
                # 指数格式(6字段): [0]name [1]price [2]change_amt [3]change_pct [4]volume [5]turnover
                # 股票格式(33字段): [0]name [3]price [2]prev_close [8]volume [9]turnover
                if len(parts) >= 30:
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
                elif len(parts) >= 5:
                    # 指数格式：直接使用 change_pct，无需计算
                    price = float(parts[1]) if parts[1] else 0
                    results.append({
                        "symbol": sym, "name": parts[0],
                        "price": price,
                        "change_pct": float(parts[3]) if parts[3] else 0,
                        "change_amount": float(parts[2]) if parts[2] else 0,
                        "volume": float(parts[4]) if parts[4] else 0,
                        "turnover": float(parts[5]) if parts[5] else 0,
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
                # 中文 Key（兼容 indicators.py/chart_data）
                "日期": d["day"], "开盘": float(d["open"]), "最高": float(d["high"]),
                "最低": float(d["low"]), "收盘": float(d["close"]), "成交量": float(d.get("volume", 0)),
                # 英文 Key（兼容 factor_registry._fetch_market_data）
                "day": d["day"], "open": float(d["open"]), "high": float(d["high"]),
                "low": float(d["low"]), "close": float(d["close"]), "volume": float(d.get("volume", 0)),
            } for d in data if isinstance(d, dict)]
    except Exception:
        pass
    return []


def _sina_history_cb(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """P1-6: Circuit-breaker aware Sina history via SourceRegistry."""
    from ..services.source_registry import registry
    scale = {"daily": "240", "weekly": "1200", "monthly": "7200",
             "15m": "15", "30m": "30", "1h": "60"}.get(period, "240")
    pref = _exchange(symbol)

    def _sina_call():
        import json
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={pref}{symbol}&scale={scale}&datalen=240")
        r = s.get(url, timeout=15)
        data = json.loads(r.text)
        if isinstance(data, list) and data:
            return [{
                "date": d["day"], "open": float(d["open"]), "high": float(d["high"]),
                "low": float(d["low"]), "close": float(d["close"]), "volume": float(d.get("volume", 0)),
            } for d in data if isinstance(d, dict)]
        return []

    from ..utils.proxy import no_proxy
    with no_proxy():
        result = registry.route([("sina_history", _sina_call)],
                                route_name="A_history", operation="history", target=symbol)
        return result or []


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
        def _p():
            import akshare as ak
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
            return ak.stock_zh_a_hist_min_em(symbol=symbol, period=str(period_min), start_date=start, end_date=end, adjust="")
        df = run_in_thread(_p, timeout=8, executor="long")
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
        def _p():
            import akshare as ak
            return ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date="20200101", end_date="20500101", adjust="")
        df = run_in_thread(_p, timeout=8, executor="long")
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


# ── SourceRegistry 辅助函数 ───────────────────────────────────────


def _filtered(provider_fn, *args):
    """Provider wrapper: 调用 provider 后过滤 price>0 结果。

    确保 `registry.route()` 的 `if result` 语义正确：
    - 如果 provider 返回空列表或所有项 price=0，返回 None → route() 会继续尝试下一个源。
    - 如果 provider 返回有效项（至少一个 price>0），返回列表 → route() 视为成功。

    此函数不修改低层 provider 函数的返回值，不影响其他调用者。
    """
    result = provider_fn(*args)
    if not result:
        return None
    # 检查是否至少有一条数据有有效价格
    if any(isinstance(i, dict) and i.get("price", 0) > 0 for i in result):
        return result
    return None


# ── Public API ───────────────────────────────────────────────────

def fetch_a_stock_realtime(symbol: str | None = None) -> list[dict[str, Any]]:
    """A 股实时行情：mootdx → Sina，通过 SourceRegistry 熔断路由。"""
    if not symbol:
        return []
    return registry.route([
        ("mootdx", lambda: _filtered(_mootdx_realtime, [symbol])),
        ("sina", lambda: _filtered(_sina_realtime, [symbol], "A")),
    ], route_name="A_stock_realtime", operation="realtime", target=symbol) or []


def fetch_a_stock_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """批量 A 股实时行情：mootdx → Tencent(QQ) → Sina，通过 SourceRegistry 熔断路由。"""
    if not symbols:
        return []
    return registry.route([
        ("mootdx", lambda: _filtered(_mootdx_realtime, symbols)),
        ("tencent", lambda: _filtered(_tencent_realtime, symbols, "A")),
        ("sina", lambda: _filtered(_sina_realtime, symbols, "A")),
    ], route_name="A_stock_batch", operation="batch", target=",".join(symbols)) or []


def _em_hk_realtime(symbols: list[str]) -> list[dict[str, Any]]:
    """东方财富港股实时行情（akshare stock_hk_spot_em），按 symbols 过滤。"""
    try:
        hk_spot_cache_key = "_em_hk_spot_cache"
        hk_all = sync_memory_cache.get(hk_spot_cache_key)
        if hk_all is None:
            def _p():
                import akshare as ak
                with no_proxy():
                    return ak.stock_hk_spot_em()
            df = run_in_thread(_p, timeout=8, executor="long")
            if df is None or df.empty:
                return []
            _decode_df(df)
            hk_all = df.to_dict(orient="records")
            sync_memory_cache.set(hk_spot_cache_key, hk_all, 60)
        sym_set = set(symbols)
        results = []
        for row in hk_all:
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
    """港股实时行情：Sina → Tencent(QQ) → 东方财富三级降级，通过 SourceRegistry 熔断路由。"""
    if not symbol:
        return []
    return registry.route([
        ("sina", lambda: _filtered(_sina_realtime, [symbol], "HK")),
        ("tencent", lambda: _filtered(_tencent_realtime, [symbol], "HK")),
        ("dongfang", lambda: _filtered(_em_hk_realtime, [symbol])),
    ], route_name="HK_stock_realtime", operation="realtime", target=symbol) or []


def fetch_futures_realtime() -> list[dict[str, Any]]:
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.futures_foreign_commodity_realtime()
        df = run_in_thread(_p, timeout=8, executor="long")
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


# Sina 全球指数页面映射（欧洲指数通过页面标题抓取）
_GLOBAL_SINA_PAGE: dict[str, str] = {
    "^FTSE": "UKX",        # 英国富时100指数
    "^GDAXI": "DAX",       # 德国DAX指数
    "^FCHI": "CAC",        # 法国CAC40指数
    "^KS11": "KOSPI",      # 韩国综合指数（KOSPI 即 KS11）
    "^N225": "NKY",        # 日经225指数（Bloomberg 代码 NKY）
    "^STOXX50E": "SX5E",   # 欧元区Stoxx50指数
}

# Sina 可用的实时行情 API 代码
_GLOBAL_SINA_SHORT: dict[str, str] = {
    "^GSPC": "gb_$inx",    # 标普500: gb_$inx（gb_$spx 返回空数据）
    "^IXIC": "gb_$ixic",
    "^DJI": "gb_$dji",
    "^N225": "gb_$n225",
    "^HSI": "gb_$hsi",
    "^HSCE": "gb_$hsce",
    "^HSTECH": "gb_$hstech",
    "^KS11": "gb_$ks11",
    "^FTSE": "gb_$ftse",
    "^AXJO": "gb_$axjo",
    "^GDAXI": "gb_$dax",
    "^FCHI": "gb_$fchi",
    "^STOXX50E": "gb_$stoxx50e",
}


def fetch_sina_global_index(symbol: str) -> dict[str, Any] | None:
    """通过新浪财经查询全球指数实时行情（免费、极快、中国大陆最稳定）。

    Args:
        symbol: APP 标准代码如 ^GSPC, ^IXIC, ^DJI, ^N225, ^HSI。

    Returns:
        行情 dict 或 None。
    """
    sina_code = _GLOBAL_SINA_SHORT.get(symbol)
    if not sina_code:
        return None
    try:
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        r = s.get(f"https://hq.sinajs.cn/list={sina_code}", timeout=8)
        text = r.text.strip()
        if "=" not in text or '"' not in text:
            return None
        parts = text.split('"')[1].split(",")
        if len(parts) < 6:
            return None
        name = parts[0].strip().replace("INDEX", "").replace("  ", " ").strip()
        price = float(parts[1]) if parts[1] else 0
        change_pct = float(parts[2]) if parts[2] else 0
        # Sina 列结构: 名称,价格,涨跌幅,[更新时间],涨跌额,昨收,...
        # 新版在 [3] 插入了时间列，若含日期字符则涨跌额在 [4]
        if len(parts) > 4 and any(c in str(parts[3]) for c in ("-", ":", "/")):
            change_amount = float(parts[4]) if parts[4] else 0
        else:
            change_amount = float(parts[3]) if parts[3] else 0
        return {
            "symbol": symbol,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amount,
            "asset_type": "index",
            "available": True,
        }
    except Exception as exc:
        logger.warning("[fetch_sina_global_index] %s (code=%s) failed: %s",
                       symbol, _GLOBAL_SINA_SHORT.get(symbol, "?"), exc)
        return None


def fetch_sina_page_global_index(symbol: str) -> dict[str, Any] | None:
    """通过新浪财经页面标题抓取全球指数行情（欧洲指数降级方案）。

    Sina 的实时行情 API（hq.sinajs.cn）不提供欧洲指数数据，
    但其全球指数详情页 ``https://finance.sina.com.cn/stock/globalindex/quotes/{page_sym}``
    的 ``<title>`` 标签中含有实时价格和涨跌幅。

    Args:
        symbol: APP 标准代码如 ^FTSE, ^GDAXI, ^FCHI, ^STOXX50E。

    Returns:
        行情 dict 或 None。
    """
    page_sym = _GLOBAL_SINA_PAGE.get(symbol)
    if not page_sym:
        return None
    try:
        url = f"https://finance.sina.com.cn/stock/globalindex/quotes/{page_sym}"
        s = _session()
        s.headers.update({"Referer": "https://finance.sina.com.cn"})
        r = s.get(url, timeout=8)
        # 使用原始字节搜索价格，绕过 requests 编码检测偏差（ISO-8859-1 vs GBK）
        raw = r.content
        ts = raw.find(b"<title>")
        te = raw.find(b"</title>")
        if ts < 0 or te < 0:
            return None
        title_bytes = raw[ts + 7:te]

        import re
        # 价格和涨跌幅在 title 中是纯 ASCII，在原始字节中直接匹配
        # 注意 change_pct 正数无 + 号，故 [-+] 改为 [-+]?
        m = re.search(rb"([\d.]+)\(([-+]?\d+[.]?\d*)\)", title_bytes)
        if not m:
            return None
        price = float(m.group(1).decode())
        change_pct = float(m.group(2).decode())

        prev_close = price / (1 + change_pct / 100) if change_pct != -100 else None
        change_amount = round(price - prev_close, 2) if prev_close else None

        return {
            "symbol": symbol,
            "name": "",
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amount,
            "asset_type": "index",
            "available": True,
        }
    except Exception:
        return None


def fetch_index_realtime() -> list[dict[str, Any]]:
    """Fetch major market indices via Sina(s_sh)→mootdx→Tencent(QQ) 三级降级。

    上证指数(000001/000300/000688 等)在 Sina 需用 s_sh 前缀（指数格式），
    否则会被当成深圳股票返回错误价格（如 000001=平安银行10.98）。
    """
    with no_proxy():
        indices = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
                   "000688": "科创50", "000300": "沪深300", "000016": "上证50",
                   "000905": "中证500", "000852": "中证1000"}
        codes = list(indices.keys())

        # Tier 1: Sina（已修正 s_sh 前缀，返回正确指数数据）
        try:
            sina_result = _sina_realtime(codes, "index")
            if sina_result and any(r.get("price", 0) > 100 for r in sina_result):
                return sina_result
        except Exception:
            pass

        # Tier 2: mootdx
        try:
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

        # Tier 3: Tencent(QQ) 兜底
        return _tencent_realtime(codes, "index")


def fetch_fund_nav(symbol: str) -> tuple[float, float] | None:
    """获取场外开放式基金的单位净值与日涨跌幅（用于 OTC 联接基金）。

    返回 (unit_net_value, daily_growth_pct)，取最新一条记录；不可用返回 None。
    """
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值")
        df = run_in_thread(_p, timeout=8, executor="long")
        _decode_df(df)
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            nav = float(last.get("单位净值") or last.get("unit_net_value") or 0)
            chg = float(last.get("日增长率") or last.get("daily_growth_rate") or 0)
            if nav:
                return (nav, round(chg, 2))
    except Exception:
        pass

    # Fallback: 天天基金 API
    try:
        result = run_in_thread(lambda: fund_fetcher.fetch_fund_nav(symbol), timeout=8, executor="long")
        if result and result.get("nav"):
            return (result["nav"], result.get("daily_change_pct", 0.0))
    except Exception:
        pass

    return None


def fetch_index_history(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """获取指数历史 K 线（日线/周线/月线），使用 akshare stock_zh_index_daily。
    akshare 返回格式: 日期,开盘,最高,最低,收盘,成交量,成交额。"""
    try:
        import pandas as pd
        # 处理已带前缀的 symbol（如 sh000001、sz399001）
        code = symbol[2:] if symbol.startswith(("sh", "sz", "bj")) else symbol
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.stock_zh_index_daily(symbol=f"sh{code}")
        df = run_in_thread(_p, timeout=8, executor="long")
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


_ETF_PREFIXES = ("51", "52", "15", "16", "56", "58", "59")


def _is_etf_code(symbol: str) -> bool:
    """检查代码是否以 ETF 前缀开头（A股 ETF 代码特征）。"""
    return any(symbol.startswith(p) for p in _ETF_PREFIXES)


def fetch_history(symbol: str, asset_type: str = "A", period: str = "daily") -> list[dict[str, Any]]:
    with no_proxy():
        if asset_type == "index":
            return fetch_index_history(symbol, period)
        if asset_type == "A":
            # ETF 代码跳过 mootdx（不支持），直接走 Sina（快且稳定）
            if _is_etf_code(symbol):
                return _sina_history_cb(symbol, period)
            if period in ("15m", "30m", "1h"):
                # Sina K 线为主力（稳定），akshare eastmoney 分钟线兜底
                rows = _sina_history_cb(symbol, period)
                if not rows:
                    rows = _akshare_intraday_history(symbol, int(period[:-1]))
                return rows
            if period == "4h":
                rows = _sina_history_cb(symbol, "1h")  # 分钟线
                if not rows:
                    rows = _akshare_intraday_history(symbol, 60)
                return _resample_4h(rows)
            items = _mootdx_history(symbol, period)
            if items:
                return items
            return _sina_history_cb(symbol, period)
        if asset_type in ("HK", "US"):
            return _fetch_akshare_history(symbol, asset_type, period)
        return []


def _fetch_akshare_history(symbol: str, asset_type: str, period: str) -> list[dict[str, Any]]:
    try:
        import pandas as pd
        def _p():
            import akshare as ak
            m = {"A": ak.stock_zh_a_hist, "HK": ak.stock_hk_hist, "US": ak.stock_us_hist}
            fn = m.get(asset_type)
            if not fn:
                return None
            return fn(symbol=symbol, period=period, adjust="qfq") if asset_type == "A" else fn(symbol=symbol, period=period)
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            _decode_df(df)
            return df.to_dict(orient="records")
        # Fallback: Finnhub candles → Alpha Vantage
        if asset_type in ("HK", "US"):
            fh_result = run_in_thread(lambda: global_markets_fetcher.fetch_candles(symbol, "D"), timeout=8, executor="long")
            if fh_result:
                return fh_result
            av_result = run_in_thread(lambda: global_markets_fetcher.fetch_daily(symbol), timeout=10, executor="long")
            if av_result:
                return av_result
        return []
    except Exception:
        return []


def get_k_data(symbol: str, period: str = "daily") -> list[dict[str, Any]]:
    """获取A股历史K线（akshare直接查询，作为mootdx/sina降级后的兜底）。

    Args:
        symbol: 股票代码（如 "000001"）。
        period: K线周期，如 "daily", "weekly", "monthly"。

    Returns:
        list[dict]: 每行包含 日期、开盘、最高、最低、收盘、成交量。
    """
    try:
        import pandas as pd
        def _p():
            import akshare as ak
            return ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq")
        df = run_in_thread(_p, timeout=15, executor="long")
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return []
        _decode_df(df)
        return df.to_dict(orient="records")
    except Exception:
        return []


def search_etf(keyword: str) -> list[dict[str, Any]]:
    cache_key = f"search_etf:{keyword}"
    cached = sync_memory_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.fund_etf_spot_em()
        df = run_in_thread(_p, timeout=8, executor="long")
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
        sync_memory_cache.set(cache_key, results, 60)
        return results
    except Exception:
        return []


def fetch_etf_list() -> list[dict[str, Any]]:
    """返回全量 ETF 列表（代码/名称/最新价/涨跌幅），用于本地关键字过滤。
    Sina 列表接口快（~3s），akshare spot 兜底（慢但稳定）。"""
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.fund_etf_category_sina(symbol="ETF基金")
        df = run_in_thread(_p, timeout=15, executor="long")
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
            def _p():
                import akshare as ak
                with no_proxy():
                    return ak.fund_etf_spot_em()
            df = run_in_thread(_p, timeout=8, executor="long")
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



