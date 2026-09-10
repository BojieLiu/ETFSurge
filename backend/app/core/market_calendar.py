"""全球主流市场交易日历 / 交易时段判断。

集中的交易时间判定函数，基于各交易所夏令时规则。
"""
from datetime import date, datetime, time as _dtime, timedelta, timezone
import logging
import time as _time

# ── 市场作息（北京时间，夏令时） ──────────────────────────────────
# 字段: (开盘, 收盘)
_MARKET_SCHEDULE: dict[str, tuple[_dtime, _dtime]] = {
    "A股":  (_dtime(9, 30),  _dtime(15, 0)),
    "港股":  (_dtime(9, 30),  _dtime(16, 0)),
    "日经":  (_dtime(8, 0),   _dtime(14, 30)),
    "韩国":  (_dtime(7, 0),   _dtime(14, 30)),
    "澳洲":  (_dtime(7, 0),   _dtime(13, 0)),
    "美股":  (_dtime(21, 30), _dtime(4, 0)),    # 21:30→次日04:00
    "欧股":  (_dtime(15, 0),  _dtime(23, 30)),
    "英国":  (_dtime(15, 0),  _dtime(23, 30)),
}

# round24 R26: A股盘后固定价格交易窗口（2026-07-06 起，沪深交易所新规）——
# 交易时间 15:05-15:30，以当日收盘价（15:00 集合竞价产生）逐笔撮合，成交量计入当日总量。
# 该窗口不产生新价格（收盘价 15:00 已定），但成交量/成交额在 15:30 结束前持续累加，
# 因此「完整当日数据」要等到 15:30（盘后快照 as_of 用 15:30 而非 15:00）。
_A_SHARE_AFTER_HOURS_START = _dtime(15, 5)
_A_SHARE_AFTER_HOURS_END = _dtime(15, 30)

# ── 节假日交易日历缓存（round53 遗留批：R183 节假日接入） ────────────────
# akshare tool_trade_date_hist_sina（免费，~8800 行，覆盖至当年年底）；
# 24h TTL 模块级缓存；失败降级返回 None（调用方回落周末判定）。
_HOLIDAY_CAL_CACHE: tuple[float, tuple[date, ...] | None] | None = None
_HOLIDAY_CAL_TTL_S = 24 * 3600


def _fetch_trade_dates() -> tuple[date, ...] | None:
    """拉取交易日历（同步 IO，供 _holiday_calendar 调用方包 run_sync）。"""
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty or "trade_date" not in df.columns:
            return None
        dates = []
        for v in df["trade_date"]:
            if isinstance(v, date) and not isinstance(v, datetime):
                dates.append(v)
            elif isinstance(v, datetime):
                dates.append(v.date())
            else:
                dates.append(datetime.strptime(str(v)[:10], "%Y-%m-%d").date())
        return tuple(sorted(dates))
    except Exception as e:  # noqa: BLE001 - 外部源失败由调用方降级
        logging.getLogger(__name__).warning(
            "[market_calendar] trade_date_hist_sina fetch failed (weekend "
            "fallback active): %s", e)
        return None


def _holiday_calendar() -> tuple[date, ...] | None:
    """返回交易日集合（24h 缓存）；外部源不可用返回 None（调用方降级）。"""
    global _HOLIDAY_CAL_CACHE
    now_ts = _time.time()
    if _HOLIDAY_CAL_CACHE is not None:
        ts, cal = _HOLIDAY_CAL_CACHE
        if now_ts - ts < _HOLIDAY_CAL_TTL_S:
            return cal
    cal = _fetch_trade_dates()
    if cal is not None:
        _HOLIDAY_CAL_CACHE = (now_ts, cal)
    return cal


def is_trading_time(dt: datetime | None = None) -> bool:
    """判断 A 股是否在交易时段。（向后兼容）

    以 15:00 收盘为界——盘后固定价格交易（15:05-15:30）以收盘价成交不产生新价格，
    不视为「盘中」（价格语义不变，仅成交量在窗口内累加）。
    """
    return get_market_status("A股", dt) == "open"


def is_a_share_trading_day(dt: datetime | date | None = None) -> bool:
    """判断 A 股交易日（R183, docs/round53-container-reacceptance-round52-plans.md §8.3）。

    三级判定（round53 遗留批补全节假日）：
    1. 日历可用（akshare tool_trade_date_hist_sina，24h 缓存）→ 日历精确判定
       （含调休上班日：日历含 2026-10-10 周六 → True）；
    2. 日历不可用 → 降级周末判定（WARN，诚实降级不阻塞 IC 落库——误杀交易日
       比多落一个节假日行危害大）；
    3. 日期超出日历覆盖期（日历最晚日期之后）→ 回落周末判定。

    Args:
        dt: date / datetime，缺省为北京时间今天。

    Returns:
        True = 交易日，False = 休市日（周末/法定节假日；降级模式下仅周末）。
    """
    if dt is None:
        dt = (datetime.now(timezone.utc) + timedelta(hours=8)).date()  # 北京时间今天
    if isinstance(dt, datetime):
        dt = dt.date()
    cal = _holiday_calendar()
    if cal is None:
        return dt.weekday() < 5  # 降级：周末判定
    if cal[-1] < dt:
        return dt.weekday() < 5  # 超出日历覆盖期：回落周末判定
    return dt in cal
    """判断 A 股交易日（R183, docs/round53-container-reacceptance-round52-plans.md §8.3）。

    ⚠️ 免费实现边界：只判周末（weekday>=5 → False）。法定节假日（春节/国庆等）
    需外部交易日历（akshare tool_trade_date_hist_sync），待后续轮接入——届时本
    函数补节假日分支，调用方接口不变。

    Args:
        dt: date / datetime，缺省为北京时间今天。

    Returns:
        True = 交易日（工作日），False = 休市日（周末；节假日接入后含法定节假日）。
    """
    if dt is None:
        dt = (datetime.now(timezone.utc) + timedelta(hours=8)).date()  # 北京时间今天
    if isinstance(dt, datetime):
        dt = dt.date()
    return dt.weekday() < 5


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
