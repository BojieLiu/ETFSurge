"""
R5-2-8: PE/PB 备用源（stock_value_em）+ 失败缓存 1h。

主源 stock_zh_a_hist（东财日线估值列）失败 → 备用源 stock_value_em。
mock akshare，无网络。
"""
import pandas as pd
from unittest.mock import patch

from app.fetchers import fundamentals_fetcher as ff


def _df(columns, rows):
    return pd.DataFrame(rows, columns=columns)


def test_primary_source_success(monkeypatch):
    """主源返回 PE/PB → 直接使用，不触发备用源。"""
    fallback_called = {"n": 0}
    ff.sync_memory_cache.clear()

    def _fake_primary(symbol, **kw):
        return _df(["日期", "市盈率", "市净率"], [["2026-08-01", 12.5, 1.8]])

    def _fake_fallback(symbol, **kw):
        fallback_called["n"] += 1
        return _df(["市盈率-动态", "市净率"], [[13.0, 2.0]])

    with patch.object(ff, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_a_hist", side_effect=_fake_primary), \
         patch("akshare.stock_value_em", side_effect=_fake_fallback):
        result = ff.fetch_current_pe_pb("600000")

    assert result == {"pe_ttm": 12.5, "pb": 1.8}
    assert fallback_called["n"] == 0, "主源成功不应触发备用源"


def test_fallback_source_used_when_primary_fails(monkeypatch):
    """主源抛异常 → 备用源返回 PE/PB。"""
    ff.sync_memory_cache.clear()

    def _fake_fallback(symbol, **kw):
        return _df(["市盈率-动态", "市净率"], [[13.5, 2.1]])

    with patch.object(ff, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_a_hist", side_effect=Exception("eastmoney down")), \
         patch("akshare.stock_value_em", side_effect=_fake_fallback):
        result = ff.fetch_current_pe_pb("600000")

    assert result == {"pe_ttm": 13.5, "pb": 2.1}, f"备用源应返回估值: {result}"


def test_fallback_empty_when_both_fail(monkeypatch):
    """主源+备用源都失败 → None + 失败缓存（二次调用不再触源）。"""
    ff.sync_memory_cache.clear()
    calls = {"n": 0}

    def _fake_fallback(symbol, **kw):
        calls["n"] += 1
        raise Exception("fallback down")

    with patch.object(ff, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_a_hist", side_effect=Exception("primary down")), \
         patch("akshare.stock_value_em", side_effect=_fake_fallback):
        assert ff.fetch_current_pe_pb("600000") is None
        # 失败缓存 1h：二次调用不触源
        assert ff.fetch_current_pe_pb("600000") is None
    assert calls["n"] == 1, f"失败缓存应阻止重复触源，实际 {calls['n']} 次"
    ff.sync_memory_cache.clear()


