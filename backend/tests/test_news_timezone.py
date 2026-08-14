# -*- coding: utf-8 -*-
"""F24 (round23 P0-A): 新闻时间戳时区统一为北京时间（Asia/Shanghai, UTC+8）。

验收：Unix epoch（UTC 绝对时）解析后显示北京时间（旧实现按 UTC 直显 → 慢 8h）；
sort_time 用北京时间语义 epoch（与时区无关排序 + 存储一致）。
"""
from datetime import datetime, timezone, timedelta

from app.fetchers.news_fetcher import _normalize_time, _parse_time

_SHA = timezone(timedelta(hours=8))


def _beijing_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_SHA).strftime("%Y-%m-%d %H:%M:%S")


def test_parse_time_epoch_is_beijing_not_utc():
    """epoch 解析显示北京时间（比 UTC 直显快 8h），不再慢 8h。"""
    ts = 1802410200
    dt = _parse_time(ts)
    assert dt is not None
    assert dt.strftime("%Y-%m-%d %H:%M:%S") == _beijing_str(ts)


def test_normalize_time_epoch_string_is_beijing():
    """_normalize_time 对 epoch 源产出北京时间 time 字符串。"""
    ts = 1802410200
    item = {"ctime": ts}
    _normalize_time(item)
    assert item["time"] == _beijing_str(ts)


def test_normalize_time_string_beijing_sort_epoch():
    """字符串北京时间 → sort_time 为该北京时刻的 epoch（排序/存储一致）。"""
    item = {"time": "2026-07-13 15:30:00"}
    _normalize_time(item)
    expected = int(datetime(2026, 7, 13, 15, 30).replace(tzinfo=_SHA).timestamp())
    assert item["sort_time"] == expected


def test_normalize_time_relative_no_crash():
    """相对时间（刚刚/X分钟前）可解析且不抛。"""
    item = {"time": "10分钟前"}
    _normalize_time(item)  # 不应抛异常
    assert "time" in item
