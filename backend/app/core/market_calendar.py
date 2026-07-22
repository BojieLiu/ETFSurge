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


def is_trading_time(dt: datetime | None = None) -> bool:
    """判断 A 股是否在交易时段。（向后兼容）"""
    return get_market_status("A股", dt) == "open"


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
