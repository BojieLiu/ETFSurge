"""交易所官方份额源 fetcher — R147-FIX.

背景：`shares_change_20d` 依赖份额历史序列，而免费 EM 源（fund_etf_hist_em 无份额列、
fund_etf_spot_em 仅当前份额）无历史 → change_20d 恒 None → shares_change 因子恒 no_data。
本 fetcher 接入两个交易所官方 API（免费无认证）：
- 深交所 `ak.fund_scale_daily_szse(start_date, end_date)`：一次请求返回窗口内全部深市
  ETF/LOF/REITS 的日频份额序列（可算 20 日变化率）。
- 上交所 `ak.fund_etf_scale_sse(date=...)`：按统计日期快照全量沪市 ETF 份额；T 与 T-20
  两次请求算 20 日变化率。

接口返回列名是 GBK 乱码（akshare 未解码），按**位置索引**列（见 _SZSE_COLS/_SSE_COLS）。

诚实降级：任一段失败返回 None（不造数），与现有 gap 标注语义一致。
"""
from __future__ import annotations

import time
from datetime import date, timedelta

# 结果缓存：{symbol: (ts, data)}，TTL 24h（与 _kline._FUND_SHARES_CACHE 同语义）
_cache: dict[str, tuple[float, dict | None]] = {}
_TTL = 86400.0  # 24h

# 位置列索引（akshare 封装后列名仍是 GBK 乱码，按位置取列最稳）
_SZSE_DATE = 0
_SZSE_CODE = 1
_SZSE_SHARES = 3
_SSE_CODE = 1
_SSE_SHARES = 5


def _is_sse(symbol: str) -> bool:
    """沪市 ETF：5 开头（518/510/511/588 等）。"""
    return symbol.startswith("5")


def fetch_share_change_20d(symbol: str, today: date | None = None) -> dict | None:
    """返回 {total_shares, shares_change_20d}；无历史源时 shares_change_20d=None；失败 None。

    按前缀分流：5xxxxx → SSE 两次快照；1xxxxx → SZSE 窗口序列；
    其它前缀（LOF 501xxx 等）暂不支持 → 返回 None（诚实降级，观察清单）。

    Args:
        today: 注入测试用日期（None 表示用真实 date.today()）。
    """
    cached = _cache.get(symbol)
    if cached and (time.time() - cached[0]) < _TTL:
        return cached[1]

    as_of = today or _last_trading_day_hint()
    try:
        if _is_sse(symbol):
            data = _fetch_sse_change(symbol, as_of)
        else:
            data = _fetch_szse_change(symbol, as_of)
    except Exception:
        data = None

    _cache[symbol] = (time.time(), data)
    return data


def _last_trading_day_hint() -> date:
    """默认 as_of 回退到最近有份额数据的交易日。

    上交所份额接口（fund_etf_scale_sse）数据 T+1 才可用——盘中查当天
    （如周一查 20260831）返回空 result（实测 0 条），查 T-1（上周五
    20260828）返回 898 条。故 as_of 需比"今天减一"再往前到最近
    已发布份额交易日。周内语义：周一用上周五（T+1 边界）、周二~五用
    前一天、周六日用上周五（精确节假日需 market_calendar，此为免费
    接口足够的最小回退）。
    """
    d = date.today()
    if d.weekday() == 0:   # Mon -> 上周五（份额数据 T+1，查当天为空）
        return d - timedelta(days=3)
    if d.weekday() == 5:   # Sat -> 上周五
        return d - timedelta(days=1)
    if d.weekday() == 6:   # Sun -> 上周五
        return d - timedelta(days=2)
    return d - timedelta(days=1)  # Tue-Fri -> 前一天


def _fetch_sse_change(symbol: str, as_of: date) -> dict | None:
    """上交所两次快照（T 与 T-20）算 change_20d。"""
    import akshare as ak

    # as_of 为最近交易日（节假日需调用方提前到最近一交易日；测试可注入）
    today = as_of.strftime("%Y%m%d")
    # T-20 个自然日（约 14-16 交易日，容忍误差）
    t20 = (as_of - timedelta(days=21)).strftime("%Y%m%d")

    def _snapshot(d: str) -> dict[str, float]:
        df = ak.fund_etf_scale_sse(date=d)
        if df is None or df.empty:
            return {}
        code_col = df.columns[_SSE_CODE]
        shares_col = df.columns[_SSE_SHARES]
        out: dict[str, float] = {}
        for _, row in df.iterrows():
            code = str(row[code_col])
            try:
                val = float(row[shares_col])
            except (TypeError, ValueError):
                continue
            if code and val > 0:
                out[code] = val
        return out

    now_map = _snapshot(today)
    if not now_map:
        return None
    total = now_map.get(symbol)
    if total is None or total <= 0:
        return None

    old_map = _snapshot(t20)
    old = old_map.get(symbol) if old_map else None
    if old and old > 0:
        change_20d = (total - old) / old
    else:
        change_20d = None
    return {"total_shares": total, "shares_change_20d": change_20d}


def _fetch_szse_change(symbol: str, as_of: date) -> dict | None:
    """深交所窗口序列算 change_20d。"""
    import akshare as ak

    end = as_of.strftime("%Y%m%d")
    start = (as_of - timedelta(days=40)).strftime("%Y%m%d")
    df = ak.fund_scale_daily_szse(start_date=start, end_date=end, symbol="ETF")
    if df is None or df.empty:
        return None
    code_col = df.columns[_SZSE_CODE]
    date_col = df.columns[_SZSE_DATE]
    shares_col = df.columns[_SZSE_SHARES]

    sub = df[df[code_col].astype(str) == symbol]
    if sub.empty:
        return None
    sub = sub.sort_values(by=date_col)
    if len(sub) < 2:
        return None
    total = float(sub.iloc[-1][shares_col])
    prev = float(sub.iloc[0][shares_col])
    change_20d = (total - prev) / prev if prev > 0 else None
    return {"total_shares": total, "shares_change_20d": change_20d}
