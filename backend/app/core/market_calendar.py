"""A 股交易日历 / 交易时段判断。

集中的交易时间判定函数，供 Phase 4 场外 ETF 估值分流使用。
"""

from datetime import datetime, time


def is_trading_time(dt: datetime | None = None) -> bool:
    """判断 A 股是否在交易时段。

    规则：周一至周五，且时间在 9:30-15:00 (含) 之间。
    - 返回 ``True``：盘中，可获取实时行情。
    - 返回 ``False``：盘后或周末，应尝试读取基金净值或持仓数据。

    Args:
        dt: 待判定的时间，缺省为当前时间。

    Returns:
        是否为 A 股交易时段。
    """
    if dt is None:
        dt = datetime.now()
    # 周末 (weekday() 返回 5=周六, 6=周日)
    if dt.weekday() >= 5:
        return False
    return time(9, 30) <= dt.time() <= time(15, 0)
