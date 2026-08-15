"""全球主流市场交易日历 / 交易时段判断。

集中的交易时间判定函数，基于各交易所夏令时规则。
"""
from datetime import datetime, time

# ── 市场作息（北京时间，夏令时） ──────────────────────────────────
# 字段: (开盘, 收盘)
_MARKET_SCHEDULE: dict[str, tuple[time, time]] = {
    "A股":  (time(9, 30),  time(15, 0)),
    "港股":  (time(9, 30),  time(16, 0)),
    "日经":  (time(8, 0),   time(14, 30)),
    "韩国":  (time(7, 0),   time(14, 30)),
    "澳洲":  (time(7, 0),   time(13, 0)),
    "美股":  (time(21, 30), time(4, 0)),    # 21:30→次日04:00
    "欧股":  (time(15, 0),  time(23, 30)),
    "英国":  (time(15, 0),  time(23, 30)),
}

# round24 R26: A股盘后固定价格交易窗口（2026-07-06 起，沪深交易所新规）——
# 交易时间 15:05-15:30，以当日收盘价（15:00 集合竞价产生）逐笔撮合，成交量计入当日总量。
# 该窗口不产生新价格（收盘价 15:00 已定），但成交量/成交额在 15:30 结束前持续累加，
# 因此「完整当日数据」要等到 15:30（盘后快照 as_of 用 15:30 而非 15:00）。
_A_SHARE_AFTER_HOURS_START = time(15, 5)
_A_SHARE_AFTER_HOURS_END = time(15, 30)


def is_trading_time(dt: datetime | None = None) -> bool:
    """判断 A 股是否在交易时段。（向后兼容）

    以 15:00 收盘为界——盘后固定价格交易（15:05-15:30）以收盘价成交不产生新价格，
    不视为「盘中」（价格语义不变，仅成交量在窗口内累加）。
    """
    return get_market_status("A股", dt) == "open"


def market_session(dt: datetime | None = None) -> str:
    """round24 R26: A股交易会话细分（含 2026-07-06 盘后固定价格交易窗口）。

    Returns:
        ``"open"`` — 盘中连续竞价/集合竞价（9:30-15:00）
        ``"after_hours"`` — 盘后固定价格交易窗口（15:05-15:30，A股新规）——
            价格=当日收盘价，成交量仍在累加，完整数据待 15:30
        ``"post_market"`` — 盘后（15:30 后，当日数据完整）
        ``"pre_market"`` — 盘前（工作日 9:30 前）
        ``"closed"`` — 休市（周末/节假日）
    """
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:
        return "closed"
    t = dt.time()
    if _A_SHARE_AFTER_HOURS_START <= t <= _A_SHARE_AFTER_HOURS_END:
        return "after_hours"
    open_t, close_t = _MARKET_SCHEDULE["A股"]
    if open_t <= t <= close_t:
        return "open"
    if t < open_t:
        return "pre_market"
    return "post_market"


def get_market_status(
    market: str,
    dt: datetime | None = None,
) -> str:
    """获取指定市场的交易状态。
    
    Args:
        market: 市场名称，如 ``"A股"``, ``"港股"``, ``"美股"``, ``"欧股"``, 
                ``"英国"``, ``"日经"``, ``"韩国"``, ``"澳洲"``
        dt: 待判定的时间，缺省为当前时间。
    
    Returns:
        ``"open"`` — 盘中
        ``"closed"`` — 盘后或休市 (周末/节假日)
    """
    if dt is None:
        dt = datetime.now()
    # 周末
    if dt.weekday() >= 5:
        return "closed"
    schedule = _MARKET_SCHEDULE.get(market)
    if schedule is None:
        return "closed"
    open_t, close_t = schedule
    # 美股跨日：收盘 < 开盘 (如 04:00 < 21:30)
    if close_t < open_t:
        return "open" if (dt.time() >= open_t or dt.time() <= close_t) else "closed"
    return "open" if open_t <= dt.time() <= close_t else "closed"
