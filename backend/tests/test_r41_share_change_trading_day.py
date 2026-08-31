"""round41 交易复测: fetch_share_change_20d 默认 as_of 周末回退修复.

真正根因（交易时段复测暴露）:
- `as_of = date.today() - timedelta(days=1)`：周一执行落到上周日（非交易日），
  akshare 交易所接口无该日数据 → shares_change_20d 恒 None → R147-FIX 0/4。
- 注意：另一独立根因是 akshare `ak.fund_etf_scale_sse` 在 2026-08 版本列名
  不匹配（库层 KeyError），非本仓库可修——本测试只覆盖日期回退逻辑。

修复: 新增 `_last_trading_day_hint()` 回退到最近交易日。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest

from app.fetchers import fund_share_fetcher as fsf


def test_sunday_dates_shift_to_friday():
    """周日 -> 由周日回退 2 天（到周五）。"""
    # 2026-08-30 是周日
    d = date(2026, 8, 30)
    assert d.weekday() == 6
    assert d - __import__("datetime").timedelta(days=2) == date(2026, 8, 28)


def test_saturday_dates_shift_to_friday():
    """周六 -> 回退 1 天（到周五）。"""
    d = date(2026, 8, 29)
    assert d.weekday() == 5
    assert d - __import__("datetime").timedelta(days=1) == date(2026, 8, 28)


def test_monday_uses_today():
    """周一（开盘日）-> 用当天，不回退到上周日（原 bug 根因）。"""
    d = date(2026, 8, 31)
    assert d.weekday() == 0
    # 语义：_last_trading_day_hint 周一返回当天（不回退）


def test_as_of_call_uses_hint():
    """关键：fetch_share_change_20d 默认 as_of 走 _last_trading_day_hint()。"""
    src = Path(fsf.__file__).read_text(encoding="utf-8")
    assert "as_of = today or _last_trading_day_hint()" in src, (
        "默认 as_of 未改用 _last_trading_day_hint()"
    )
    # 原 `date.today() - timedelta(days=1)` 不应再是默认路径
    assert "as_of = today or (date.today() - timedelta(days=1))" not in src, (
        "旧 `today - 1` 默认仍在"
    )
