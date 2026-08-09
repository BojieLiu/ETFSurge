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
import time  # U7/N08: fetch_fund_nav 24h 缓存时间戳
from pathlib import Path
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
        from requests.adapters import HTTPAdapter
        s = _req.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})
        # P4.2: Connection pool configurable from settings
        from ..config import settings
        adapter = HTTPAdapter(
            pool_connections=settings.pool_connections,
            pool_maxsize=settings.pool_maxsize,
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _shared_session = s
    return _shared_session


# ── mootdx helper ────────────────────────────────────────────────

import concurrent.futures as _cf

# mootdx 连接超时（Quotes.factory 的 TCP 连接超时）
_MOOTDX_TIMEOUT = 6
# mootdx 单次读操作超时（client.quotes / client.bars 的 socket read 超时）
# 使用 concurrent.futures 实现，防止 mootdx socket 读挂死线程池
# P0-4 (round9 §10): mootdx 读超时 8→3s——容器内实测 0.35s 返回真实行情，
# 3s 余量充足；数据源弱/EM 冷却期 mootdx 空转 8s 是 watchlist 29.9s 与批量 5.7s
# 的稳定开销（每次调用链 mootdx→tencent→sina 都要先空等 mootdx 超时）。
_MOOTDX_READ_TIMEOUT = 3

_MOOTDX_CLIENT: "Quotes | None" = None
# 单线程 executor 用于 mootdx 读操作的超时保护
_MOOTDX_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mootdx")

# R6-F1 (round6 §三/§十 R6-02): 全新环境（容器/CI 无 ~/.mootdx/config.json）fallback 服务器。
# 容器内实测 0.35s 返回真实行情；mootdx StdQuotes 显式 server 参数会跳过 BESTIP 缓存依赖。
_MOOTDX_FALLBACK_SERVERS = [("180.153.18.172", 80)]


def _has_mootdx_config() -> bool:
    """~/.mootdx/config.json 是否存在（mootdx BESTIP 服务器缓存）。"""
    try:
        return (Path.home() / ".mootdx" / "config.json").exists()
    except Exception:
        return False


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

    R6-F1: 全新环境（容器/CI 无 ~/.mootdx/config.json BESTIP 缓存）时
    显式传入已知可用 fallback server——避免 Quotes.factory 空转
    （曾致 report A 309s / 策略检查持仓加载 55s / 预热 6.2s）。
    """
    global _MOOTDX_CLIENT
    if _MOOTDX_CLIENT is None:
        from mootdx.quotes import Quotes
        if _has_mootdx_config():
            _MOOTDX_CLIENT = Quotes.factory(market='std', timeout=_MOOTDX_TIMEOUT)
        else:
            _MOOTDX_CLIENT = Quotes.factory(
                market='std', server=_MOOTDX_FALLBACK_SERVERS[0],
                timeout=_MOOTDX_TIMEOUT,
            )
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

def _strip_a_prefix(symbol: str) -> str:
    """O22 (round8 §7 §5.1G): 剥离 A 股交易所前缀（sh688981 → 688981）。

    底层源（tencent/sina/mootdx）只认纯数字代码，带 sh/sz/bj 前缀直接取数失败
    （_exchange 把 sh688981 判成 sz → 拼出 szsh688981 → 恒空）。
    """
    s = str(symbol or "").lower()
    for pref in ("sh", "sz", "bj"):
        if s.startswith(pref):
            return s[len(pref):]
    return s


def _exchange(symbol: str) -> str:
    # O22: 先剥 sh/sz/bj 前缀再判断（带前缀输入不再误判为 sz）
    s = _strip_a_prefix(symbol)
    if s.startswith("6") or s.startswith("51") or s.startswith("5"):
        return "sh"
    return "sz"


def _normalize_hk_symbol(symbol: str) -> str:
    """F1-1: 港股代码归一化 — 去除 .HK 后缀、转大写，供各数据源前缀拼接。"""
    if not symbol:
        return symbol
    s = symbol.upper()
    if s.endswith(".HK"):
        s = s[:-3]
    return s


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
            # F1-1: 港股新浪前缀为 rt_hk + 5 位代码（如 rt_hk00700），
            # 此前误用 _exchange() 拼出 sz00700 → 恒为空 → tencent 降级也失效。
            if asset_type == "HK":
                pref = "rt_hk"
                sym_key = _normalize_hk_symbol(sym)
            else:
                pref = "s_sh" if sym in _SH_INDEXES else _exchange(sym)
                # O22: A 股前缀拼接使用纯数字（带 sh 前缀会拼出 shsh688981 → 空）
                sym_key = _strip_a_prefix(sym)
            try:
                r = s.get(f"https://hq.sinajs.cn/list={pref}{sym_key}", timeout=10)
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
        # F1-1: 港股腾讯前缀为 hk + 5 位代码（如 hk00700），此前误用
        # _exchange() 拼出 sz00700 → tencent 分支恒空但不报错 → 直接返回空结构。
        code_parts = []
        for s in symbols:
            if asset_type == "HK":
                code_parts.append(f"hk{_normalize_hk_symbol(s)}")
            else:
                # O22: A 股前缀拼接使用纯数字（带 sh 前缀会拼出 szsh688981 → 空）
                code_parts.append(f"{_exchange(s)}{_strip_a_prefix(s)}")
        codes = ",".join(code_parts)
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
            # F1-1: 返回符号归一化 — 以调用方传入的原始符号为准（含 .HK 后缀），
            # 保证 _filtered() 的调用者拿到一致的 symbol（组合/自选存的是 00700.HK）。
            out_sym = code
            if asset_type == "HK":
                for req in symbols:
                    if _normalize_hk_symbol(req) == code.upper() or req.upper() == code.upper():
                        out_sym = req
                        break
            results.append({
                "symbol": out_sym, "name": parts[1],
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


# P1-9 (round9 §6.5.1-B): fund_etf_spot_em 的「最新份额」降级缓存——全市场 ETF spot
# 拉取 ~24s（分页），只能 1h 缓存后复用；仅当前份额（无历史，change_20d 不可算）。
_SPOT_SHARES_CACHE: dict[str, float] = {}
_SPOT_SHARES_TS = 0.0
_SPOT_SHARES_TTL = 3600.0


def _fetch_spot_shares() -> dict[str, float]:
    """懒加载 fund_etf_spot_em 的 symbol→最新份额 映射（1h 内存缓存，失败回退旧值）。"""
    global _SPOT_SHARES_CACHE, _SPOT_SHARES_TS
    if _SPOT_SHARES_CACHE and (time.time() - _SPOT_SHARES_TS) < _SPOT_SHARES_TTL:
        return _SPOT_SHARES_CACHE
    try:
        def _p():
            import akshare as ak
            return ak.fund_etf_spot_em()
        df = run_in_thread(_p, timeout=25, executor="long")
        _decode_df(df)
        out: dict[str, float] = {}
        if df is not None and len(df) > 0:
            for _, r in df.iterrows():
                code = str(r.get("代码", "") or "")
                val = r.get("最新份额")
                if code and val is not None:
                    try:
                        fv = float(val)
                        if fv > 0:
                            out[code] = fv
                    except (TypeError, ValueError):
                        pass
        if out:
            _SPOT_SHARES_CACHE = out
            _SPOT_SHARES_TS = time.time()
        return out
    except Exception:
        return dict(_SPOT_SHARES_CACHE)


def fetch_etf_shares_outstanding(symbol: str) -> dict | None:
    """获取ETF份额数据（用于规模变化率计算）。

    round9 P1-9 (§6.5.1-B): 主源 fund_etf_hist_em 实测返回的列是行情字段
    （日期/开盘/收盘/.../换手率），**无「份额/规模」列** → 主源恒 None（旧代码
    静默失败无降级）。修复：新增降级源 fund_etf_spot_em 的「最新份额」列
    （实测 510050=7107966720.0 可用，1h 缓存防 24s 全量拉取）；份额历史序列
    无免费公开源 → shares_change_20d 无法计算时显式 None + reason 标注
    （诚实降级，不再伪装有数据）。
    返回: { "total_shares": float, "shares_change_20d": float|None, "reason": str|None }
    失败返回 None。
    """
    try:
        def _p():
            import akshare as ak
            return ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date="20200101", end_date="20500101", adjust="")
        df = run_in_thread(_p, timeout=8, executor="long")
        if df is None or df.empty:
            return None
        _decode_df(df)
        cols = [c for c in df.columns if "份额" in str(c) or "规模" in str(c)]
        if cols:
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

    # 降级 (P1-9): fund_etf_hist_em 无「份额」列 → 用 fund_etf_spot_em 的「最新份额」
    #（当前份额，1h 缓存）；份额历史序列无公开源 → change_20d=None + reason 标注。
    try:
        shares_map = _fetch_spot_shares()
        val = shares_map.get(symbol)
        if val is not None and val > 0:
            return {
                "total_shares": val,
                "shares_change_20d": None,
                "reason": "份额历史源不可用（fund_etf_hist_em 无份额列），仅当前份额",
            }
    except Exception:
        pass
    return None


# ── S12: 网易财经 K 线降级源 ────────────────────────────────────────


def fetch_history_netease(symbol: str, market: str = "A", period: str = "daily") -> list[dict] | None:
    """使用网易财经 money.163.com 获取历史 K 线（作为降级兜底）。

    Args:
        symbol: 股票/ETF 代码。
        market: 市场类型（仅支持 "A"）。
        period: K 线周期（仅支持 "daily"）。

    Returns:
        [{date, open, high, low, close, volume}, ...] 或 None。
    """
    try:
        import urllib.request
        import time
        
        # 网易财经历史数据 API
        # 上海: 0{symbol}, 深圳: 1{symbol}
        prefix = "0" if symbol.startswith("5") or symbol.startswith("6") else "1"
        url = f"http://quotes.money.163.com/service/chddata.html?code={prefix}{symbol}&start=20240101&end=20500101"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://money.163.com/",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
        
        lines = raw.strip().split("\n")
        if len(lines) < 2:
            return None
        
        result = []
        for line in lines[1:]:  # Skip header
            cols = line.split(",")
            if len(cols) < 7:
                continue
            try:
                result.append({
                    "date": cols[0],
                    "open": float(cols[3]) if cols[3] else 0,
                    "high": float(cols[4]) if cols[4] else 0,
                    "low": float(cols[5]) if cols[5] else 0,
                    "close": float(cols[6]) if cols[6] else 0,
                    "volume": float(cols[7]) if len(cols) > 7 and cols[7] else 0,
                })
            except (ValueError, IndexError):
                continue
        
        if not result:
            return None
        logger.debug("[netease] Fetched %d k-lines for %s", len(result), symbol)
        return result
    except Exception as e:
        logger.debug("[netease] Failed to fetch %s: %s", symbol, e)
        return None


# ── 在 fetch_history 中添加 NetEase 降级 ────────────────────────────



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
    """A 股实时行情：mootdx → Tencent(QQ) → Sina，通过 SourceRegistry 熔断路由。

    F1-2: 与批量版 fetch_a_stock_batch 降级链对齐（补 tencent），
    修复 mootdx 熔断窗口期单只 A 股 realtime 间歇性为空的问题。
    O22 (round8 §7): 入口剥 sh/sz/bj 前缀——底层源只认纯数字代码。
    """
    if not symbol:
        return []
    clean = _strip_a_prefix(symbol)
    return registry.route([
        ("mootdx", lambda: _filtered(_mootdx_realtime, [clean])),
        ("tencent", lambda: _filtered(_tencent_realtime, [clean], "A")),
        ("sina", lambda: _filtered(_sina_realtime, [clean], "A")),
    ], route_name="A_stock_realtime", operation="realtime", target=symbol) or []


def fetch_a_stock_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """批量 A 股实时行情：mootdx → Tencent(QQ) → Sina，通过 SourceRegistry 熔断路由。"""
    if not symbols:
        return []
    # O22 (round8 §7): 批量入口同样剥 sh/sz/bj 前缀
    clean_symbols = [_strip_a_prefix(s) for s in symbols]
    return registry.route([
        ("mootdx", lambda: _filtered(_mootdx_realtime, clean_symbols)),
        ("tencent", lambda: _filtered(_tencent_realtime, clean_symbols, "A")),
        ("sina", lambda: _filtered(_sina_realtime, clean_symbols, "A")),
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
        sym_set = set(_normalize_hk_symbol(s) for s in symbols)
        results = []
        for row in hk_all:
            code = str(row.get("代码", row.get("symbol", "")))
            if _normalize_hk_symbol(code) not in sym_set:
                continue
            try:
                price = float(row.get("最新价", 0) or 0)
            except (ValueError, TypeError):
                price = 0
            try:
                chg = float(row.get("涨跌幅", 0) or 0)
            except (ValueError, TypeError):
                chg = 0
            # F1-1: 返回符号与请求一致（含 .HK 后缀），保证契约稳定
            out_sym = code
            for req in symbols:
                if _normalize_hk_symbol(req) == _normalize_hk_symbol(code):
                    out_sym = req
                    break
            results.append({
                "symbol": out_sym,
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


# R27: spot 全量列表 single-flight——缓存 miss 时同 key 并发请求只 fetch 一次，
# 其余调用等待共享结果（消除 thundering herd，补全响应不随并发搜索退化）
import threading as _threading

_spot_inflight: dict[str, _threading.Event] = {}
_spot_inflight_lock = _threading.Lock()


def _spot_single_flight(cache_key: str, fetch_fn) -> list[dict]:
    """单飞执行 fetch_fn；同 key 并发调用等待首发起者完成并共享结果。

    首发起者注册 Event 并执行 fetch；后续调用看到已有 Event 则阻塞等待
    其完成（Event.set 后 fetch 已写缓存，直接读缓存返回）。
    """
    with _spot_inflight_lock:
        evt = _spot_inflight.get(cache_key)
        if evt is None:
            evt = _threading.Event()
            _spot_inflight[cache_key] = evt
            is_leader = True
        else:
            is_leader = False
    if not is_leader:
        # 等待发起者完成（最多 15s，与 fetch 超时一致）
        evt.wait(timeout=15)
        return sync_memory_cache.get(cache_key) or []
    try:
        return fetch_fn()
    finally:
        evt.set()
        with _spot_inflight_lock:
            _spot_inflight.pop(cache_key, None)


def fetch_hk_spot_list() -> list[dict[str, Any]]:
    """港股全量 spot 列表（akshare stock_hk_spot_em），6h 长 TTL 缓存，供搜索用。

    返回: [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}, ...]
    失败返回 []，绝不抛异常。
    与 `_em_hk_realtime` 的 60s 实时缓存相互独立（key 不同、TTL 不同）。
    """
    cache_key = "hk_spot_list"
    cached = sync_memory_cache.get(cache_key)
    if cached is not None:
        return cached
    # R27: single-flight——缓存 miss 时同 key 并发只 fetch 一次，其余等待共享结果
    return _spot_single_flight(cache_key, _fetch_hk_spot)


def _fetch_hk_spot() -> list[dict[str, Any]]:
    cache_key = "hk_spot_list"
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.stock_hk_spot_em()
        df = run_in_thread(_p, timeout=10, executor="long")
        if df is None or df.empty:
            # R4-26: 失败/空长缓存 1h（原 60s）——数据源不可用期间搜索
            # 快速走静态基座（毫秒级），而非每次搜索都等超时重试
            sync_memory_cache.set(cache_key, [], 3600)
            return []
        _decode_df(df)
        rows = []
        for _, row in df.iterrows():
            code = str(row.get("代码", row.get("symbol", ""))).strip()
            # R2: akshare 代码列可能不带前导零（700 vs 00700），统一补零到 5 位
            if code.isdigit() and len(code) < 5:
                code = code.zfill(5)
            rows.append({
                "symbol": code,
                "name": str(row.get("名称", row.get("name", ""))),
                "market": "HK",
            })
        sync_memory_cache.set(cache_key, rows, CACHE_TTL["hk_spot_list"])
        return rows
    except Exception:
        # 失败/异常也长缓存 1h（R4-26）
        try:
            sync_memory_cache.set(cache_key, [], 3600)
        except Exception:
            pass
        return []


def fetch_us_spot_list() -> list[dict[str, Any]]:
    """美股全量 spot 列表（akshare stock_us_spot_em），6h 长 TTL 缓存，供搜索用。

    返回: [{"symbol": "AAPL", "name": "苹果", "name_en": "Apple Inc", "market": "US"}, ...]
    失败返回 []，绝不抛异常。
    注意：akshare 该接口列名以实际返回为准（名称=中文、代码、英文名称），
    本函数对列名做了兼容读取；境内网络不可用时返回 []（搜索降级为静态基座）。
    """
    cache_key = "us_spot_list"
    cached = sync_memory_cache.get(cache_key)
    if cached is not None:
        return cached
    # R27: single-flight——缓存 miss 时同 key 并发只 fetch 一次
    return _spot_single_flight(cache_key, _fetch_us_spot)


def _fetch_us_spot() -> list[dict[str, Any]]:
    cache_key = "us_spot_list"
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                return ak.stock_us_spot_em()
        df = run_in_thread(_p, timeout=10, executor="long")
        if df is None or df.empty:
            # R4-26: 失败/空长缓存 1h（原 60s）
            sync_memory_cache.set(cache_key, [], 3600)
            return []
        _decode_df(df)
        rows = []
        for _, row in df.iterrows():
            rows.append({
                "symbol": str(row.get("代码", row.get("symbol", ""))).strip(),
                "name": str(row.get("名称", row.get("name", ""))),
                "name_en": str(row.get("英文名称", row.get("name_en", row.get("英文名", "")))),
                "market": "US",
                # P2-R (round10 §5.6): 补实时字段——美股热点排行（成交额榜）依赖。
                # 东财 stock_us_spot_em 列：最新价/涨跌幅/成交量/成交额/总市值/流通市值。
                "price": _to_float(row.get("最新价", row.get("price"))),
                "change_pct": _to_float(row.get("涨跌幅", row.get("change_pct"))),
                "amount": _to_float(row.get("成交额", row.get("amount"))),
                "mcap": _to_float(row.get("总市值", row.get("total_mv"))),
            })
        sync_memory_cache.set(cache_key, rows, CACHE_TTL["us_spot_list"])
        return rows
    except Exception:
        # 失败/异常也长缓存 1h（R4-26）
        try:
            sync_memory_cache.set(cache_key, [], 3600)
        except Exception:
            pass
        return []


def fetch_futures_realtime() -> list[dict[str, Any]]:
    """外盘商品期货实时行情（akshare futures_foreign_commodity_realtime）。

    R5-2-7: akshare 新签名需 symbol 参数（旧无参调用 TypeError → 商品恒空）。
    传常用外盘品种（NYMEX 原油/COMEX 黄金白银等），失败静默（非交易时段允许为空）。
    """
    # 常用外盘品种（akshare 官方 symbol 表：NYMEX/COMEX/CBOT 等交易所品种代码）
    _FOREIGN_COMMODITY_SYMBOLS = [
        "CL", "GC", "SI", "HG",  # 原油(纽约)/黄金/白银/铜(COMEX)
        "NQ", "ES", "YM",        # 纳指/标普/道指期货(CME)
        "WTI", "BZ",             # WTI 原油/布伦特
        "ZL", "ZSI", "ZC",       # 豆油/白银(大)/玉米(CBOT)
        "ZW", "ZS", "ZR",        # 小麦/大豆/糙米(CBOT)
    ]
    try:
        def _p():
            import akshare as ak
            with no_proxy():
                # R5-2-7: 传 symbol 列表（akshare 新签名），避免无参 TypeError
                return ak.futures_foreign_commodity_realtime(symbol=_FOREIGN_COMMODITY_SYMBOLS)
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

    R77 缺口 4：改为 registry.route（对齐 mootdx→Sina 模式）——熔断源被跳过、
    成功/失败记录熔断状态；全失败返回 []（保持旧调用方兼容）。
    上证指数(000001/000300/000688 等)在 Sina 需用 s_sh 前缀（指数格式），
    否则会被当成深圳股票返回错误价格（如 000001=平安银行10.98）。
    """
    indices = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
               "000688": "科创50", "000300": "沪深300", "000016": "上证50",
               "000905": "中证500", "000852": "中证1000"}
    codes = list(indices.keys())

    def _sina_index():
        with no_proxy():
            sina_result = _sina_realtime(codes, "index")
            # 指数价格 >100 校验：s_sh 前缀错误时返回的是股票价格（如 10.98），需跳过
            if sina_result and any(r.get("price", 0) > 100 for r in sina_result):
                return sina_result
            return []

    def _mootdx_index():
        with no_proxy():
            client = _mootdx()
            df = client.index(symbol=codes)
            if df is None or df.empty:
                return []
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

    def _tencent_index():
        with no_proxy():
            return _tencent_realtime(codes, "index")

    result = registry.route(
        [("sina", _sina_index), ("mootdx", _mootdx_index), ("tencent", _tencent_index)],
        route_name="index_realtime", operation="realtime", target="CN_INDEX",
    )
    return result or []


# Z05: Connection-pooled _session for fetch_fund_nav fallback
# Avoid creating new HTTP connections on every call during warmup
_fund_nav_session: "requests.Session | None" = None

# U7/N08 R3: NAV 24h 内存缓存（日频数据，预热首拉后不再重复）
_FUND_NAV_CACHE: dict[str, tuple[float, tuple[float, float] | None]] = {}
_FUND_NAV_TTL = 24 * 3600.0


def _get_nav_session() -> "requests.Session":
    """Get or create a shared Session for HTTP requests during NAV fetching."""
    global _fund_nav_session
    if _fund_nav_session is None:
        import requests
        _fund_nav_session = requests.Session()
        _fund_nav_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        })
    return _fund_nav_session


def _fetch_ttj_lsjz(symbol: str) -> list[dict[str, Any]]:
    """天天基金 f10/lsjz 历史净值（round9 P0-6：场内 ETF 的可靠日净值源）。

    实测（2026-08-07）：`api.fund.eastmoney.com/f10/lsjz?fundCode=510050` 返回
    {"Data": {"LSJZList": [{"FSRQ":"2026-08-07","DWJZ":"3.0687","LJJZ":"4.5764","JZZZL":"1.37"}]}}
    ——对场内 ETF 可用（akshare fund_open_fund_info_em 对场内 ETF 返回 0 行，见 P0-6 诊断）。
    返回列表最新在前（pageIndex=1）。
    """
    try:
        # EM 源换 curl_cffi（round11 EM 根因路线 A：浏览器 TLS 指纹绕容器侧 EM 拦截）
        from curl_cffi import requests as _cffi
        url = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=%s&pageIndex=1&pageSize=2" % symbol
        resp = _cffi.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://fundf10.eastmoney.com/",
        })
        payload = resp.json()
        rows = (payload.get("Data") or {}).get("LSJZList") or []
        return [r for r in rows if r.get("DWJZ")]
    except Exception:
        return []


def fetch_fund_nav(symbol: str) -> dict[str, Any] | None:
    """获取基金单位净值与日涨跌幅（场外联接基金 + 场内 ETF 净值兜底）。

    round9 P0-7: **契约统一为 dict** —— ``{"nav", "daily_change_pct", "nav_date"}``。
    旧实现返回 ``tuple[float, float]``，与 factor_registry 调用方 ``_nav.get("nav")``
    （dict 契约）不匹配 → AttributeError 被 except 吞掉 → TTJ 兜底永远静默失败；
    此处统一为 dict（与 fund_fetcher.fetch_fund_nav 契约一致）。

    round9 P0-6: 主源 akshare ``fund_open_fund_info_em``（场外基金）；对场内 ETF 该接口返回
    0 行 → 新增降级源天天基金 f10/lsjz（实测 510050 DWJZ=3.0687 可用）——折溢价率因子
    由此拿到可靠日净值口径。

    24h 内存缓存（日频数据，预热首拉后不再重复）。
    """
    _now = time.time()
    _cached = _FUND_NAV_CACHE.get(symbol)
    if _cached and (_now - _cached[0]) < _FUND_NAV_TTL:
        return _cached[1]

    result: dict[str, Any] | None = None
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
            nav_date = str(last.get("净值日期") or last.get("nav_date") or "")
            if nav:
                result = {
                    "nav": nav,
                    "daily_change_pct": round(chg, 2),
                    "nav_date": nav_date or None,
                }
    except Exception:
        pass

    # Fallback 1 (round9 P0-6): 天天基金 f10/lsjz 历史净值——场内 ETF 可用
    if result is None:
        try:
            rows = _fetch_ttj_lsjz(symbol)
            if rows:
                last = rows[0]
                result = {
                    "nav": float(last["DWJZ"]),
                    "daily_change_pct": float(last.get("JZZZL") or 0),
                    "nav_date": str(last.get("FSRQ") or ""),
                }
        except Exception:
            pass

    # Fallback 2: 天天基金 API (uses connection-pooled session, Z05)
    if result is None:
        try:
            session = _get_nav_session()
            fb = run_in_thread(lambda: fund_fetcher.fetch_fund_nav(symbol), timeout=8, executor="long")
            if fb and fb.get("nav"):
                result = {
                    "nav": float(fb["nav"]),
                    "daily_change_pct": float(fb.get("daily_change_pct", 0.0)),
                    "nav_date": fb.get("nav_date"),
                }
        except Exception:
            pass

    if result is not None:
        _FUND_NAV_CACHE[symbol] = (_now, result)
    return result


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
                rows = _sina_history_cb(symbol, period)
                if rows:
                    return rows
                # F0-4: 网易财经日线兜底
                if period == "daily":
                    ne_rows = fetch_history_netease(symbol, "A", "daily")
                    if ne_rows:
                        return ne_rows
                return []
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
            rows = _sina_history_cb(symbol, period)
            if rows:
                return rows
            # F0-4: 网易财经日线兜底（mootdx/sina 均失败时，akshare 熔断期间仍有数据）
            if period == "daily":
                ne_rows = fetch_history_netease(symbol, "A", "daily")
                if ne_rows:
                    return ne_rows
            return []
        if asset_type in ("HK", "US"):
            return _fetch_akshare_history(symbol, asset_type, period)
        return []


def _alphavantage_symbol(symbol: str, asset_type: str) -> str:
    """O2 (round8 §7 P1-新): Alpha Vantage 符号格式转换——港股需 4 位码 + .HK
    （00700 → 0700.HK），传 "00700" 恒返回空 → HK K 线链断裂。"""
    if asset_type == "HK":
        s = _normalize_hk_symbol(symbol)  # 00700 / 09988
        return f"{s[-4:].zfill(4)}.HK"
    return symbol


def _fetch_tencent_hk_history(symbol: str) -> list[dict[str, Any]]:
    """P1-1 (round9 §5/O2): 腾讯港股日 K 降级源（web.ifzq.gtimg.cn，非 EM）。

    容器内 EM 被 TLS 拦截（round9 C4）时 stock_hk_hist（东财）恒空 → 腾讯港股
    K 线兜底。返回 [{date, open, high, low, close, volume}, ...]（旧→新）。
    """
    try:
        import json
        import urllib.request
        hk_code = symbol if symbol.startswith("hk") else f"hk{symbol}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={hk_code},day,,,320,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        data = (payload.get("data") or {}).get(hk_code) or {}
        klines = data.get("qfqday") or data.get("day") or []
        out = []
        for row in klines:
            if len(row) < 6:
                continue
            out.append({
                "date": str(row[0]),
                "open": float(row[1]), "close": float(row[2]),
                "high": float(row[3]), "low": float(row[4]),
                "volume": float(row[5]) if row[5] else 0,
            })
        # 统一旧→新（腾讯接口实测为旧→新；异常倒序时翻转）
        if len(out) >= 2 and out[0]["date"] > out[-1]["date"]:
            out.reverse()
        return out
    except Exception:
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
            logger.debug("[history] %s %s: akshare main source hit (%d rows)", asset_type, symbol, len(df))
            return df.to_dict(orient="records")
        # P1-1: 逐源日志——旧实现静默降级，源链不可用时无任何痕迹
        logger.warning("[history] %s %s: akshare %s empty/missing — fallback chain", asset_type, symbol,
                       {"A": "stock_zh_a_hist", "HK": "stock_hk_hist", "US": "stock_us_hist"}.get(asset_type, "?"))
        # Fallback: Finnhub candles → Alpha Vantage → Tencent HK（P1-1 新增，非 EM）
        if asset_type in ("HK", "US"):
            fh_result = run_in_thread(lambda: global_markets_fetcher.fetch_candles(symbol, "D"), timeout=8, executor="long")
            if fh_result:
                logger.info("[history] %s %s: finnhub fallback hit (%d rows)", asset_type, symbol, len(fh_result))
                return fh_result
            logger.warning("[history] %s %s: finnhub fallback failed/empty", asset_type, symbol)
            # O2: alphavantage 用转换后符号（0700.HK）——旧实现传裸 00700 恒空
            av_result = run_in_thread(
                lambda: global_markets_fetcher.fetch_daily_alphavantage(
                    _alphavantage_symbol(symbol, asset_type)
                ),
                timeout=10, executor="long",
            )
            if av_result:
                logger.info("[history] %s %s: alphavantage fallback hit (%d rows)", asset_type, symbol, len(av_result))
                return av_result
            logger.warning("[history] %s %s: alphavantage fallback failed/empty", asset_type, symbol)
            # P1-1: 腾讯港股日 K（非 EM 源，容器 EM 被拦时唯一可用链）
            if asset_type == "HK":
                tx_result = _fetch_tencent_hk_history(symbol)
                if tx_result:
                    logger.info("[history] HK %s: tencent hk kline fallback hit (%d rows)", symbol, len(tx_result))
                    return tx_result
                logger.warning("[history] HK %s: tencent hk kline fallback failed/empty", symbol)
        return []
    except Exception as e:
        logger.warning("[history] %s %s history fetch failed: %s", asset_type, symbol, e)
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



