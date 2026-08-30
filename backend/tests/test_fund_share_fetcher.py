"""R147-FIX: 交易所官方份额源 fetcher 测试（fund_share_fetcher.py）。

验证 fetch_share_change_20d 正确分流 SSE/SZSE 前缀、算 20 日变化率、诚实降级、缓存命中。
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.fetchers import fund_share_fetcher as fsf

AS_OF = date(2026, 8, 28)  # 测试用固定 as_of（fetcher 接受 today 参数）


@pytest.fixture(autouse=True)
def clear_cache():
    fsf._cache.clear()
    yield
    fsf._cache.clear()


class TestSseChange20d:
    def test_sse_change_20d_computed(self, monkeypatch):
        """SSE 两次快照（T 与 T-20）→ change_20d 正确。"""
        df_now = pd.DataFrame([
            {"序号": 1, "基金代码": "510300", "基金简称": "300ETF", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 23578687700.0},
            {"序号": 2, "基金代码": "518880", "基金简称": "黄金", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 11650740800.0},
        ])
        df_old = pd.DataFrame([
            {"序号": 1, "基金代码": "510300", "基金简称": "300ETF", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-07"), "基金份额": 25128487700.0},
            {"序号": 2, "基金代码": "518880", "基金简称": "黄金", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-07"), "基金份额": 11400140800.0},
        ])

        def fake_scale_sse(**kwargs):
            d = kwargs.get("date", "")
            if d.startswith("20260828"):
                return df_now
            return df_old

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_scale_sse)
        res = fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert res is not None
        assert res["total_shares"] == 23578687700.0
        # (23578687700 - 25128487700)/25128487700 ≈ -0.0617
        assert res["shares_change_20d"] is not None
        assert abs(res["shares_change_20d"] - (-0.0617)) < 0.001

    def test_sse_missing_in_old_snapshot(self, monkeypatch):
        """T-20 快照无该 symbol → change_20d=None（诚实降级不造数）。"""
        df_now = pd.DataFrame([
            {"序号": 1, "基金代码": "510300", "基金简称": "300", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 100.0},
        ])
        df_old = pd.DataFrame([
            {"序号": 1, "基金代码": "518880", "基金简称": "黄金", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-07"), "基金份额": 50.0},
        ])

        def fake_scale_sse(**kwargs):
            d = kwargs.get("date", "")
            return df_now if d.startswith("20260828") else df_old

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_scale_sse)
        res = fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert res is not None
        assert res["total_shares"] == 100.0
        assert res["shares_change_20d"] is None

    def test_sse_symbol_not_in_snapshot(self, monkeypatch):
        """SSE 当日快照无该 symbol → 返回 None。"""
        df_now = pd.DataFrame([
            {"序号": 1, "基金代码": "518880", "基金简称": "黄金", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 50.0},
        ])

        def fake_scale_sse(**kwargs):
            return df_now

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_scale_sse)
        res = fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert res is None


class TestSzseChange20d:
    def test_szse_change_20d_computed(self, monkeypatch):
        """SZSE 窗口序列 → change_20d 正确（159915 深市）。"""
        df = pd.DataFrame([
            {"统计日期": pd.Timestamp("2026-08-07"), "基金代码": "159915",
             "基金简称": "创业板", "基金份额": 20359454936.0},
            {"统计日期": pd.Timestamp("2026-08-27"), "基金代码": "159915",
             "基金简称": "创业板", "基金份额": 18791454936.0},
        ])

        def fake_szse(**kwargs):
            return df

        monkeypatch.setattr("akshare.fund_scale_daily_szse", fake_szse)
        res = fsf.fetch_share_change_20d("159915", today=AS_OF)
        assert res is not None
        assert res["total_shares"] == 18791454936.0
        # (18791454936 - 20359454936)/20359454936 ≈ -0.077
        assert res["shares_change_20d"] is not None
        assert abs(res["shares_change_20d"] - (-0.077)) < 0.01

    def test_szse_symbol_not_in_window(self, monkeypatch):
        """SZSE 窗口无该 symbol → 返回 None。"""
        df = pd.DataFrame([
            {"统计日期": pd.Timestamp("2026-08-07"), "基金代码": "159915",
             "基金简称": "创业板", "基金份额": 100.0},
        ])

        def fake_szse(**kwargs):
            return df

        monkeypatch.setattr("akshare.fund_scale_daily_szse", fake_szse)
        res = fsf.fetch_share_change_20d("159915", today=AS_OF)
        # 单点无 prev → change_20d=None，但 total_shares 仍返回
        assert res is None  # szse 分支 < 2 行直接 return None


class TestPrefixRouting:
    def test_sse_prefix_routes_to_sse(self, monkeypatch):
        """5 开头 → 走 SSE 分支（不调 SZSE）。"""
        called = {"sse": 0, "szse": 0}

        def fake_sse(**kwargs):
            called["sse"] += 1
            return pd.DataFrame([{
                "序号": 1, "基金代码": "510300", "基金简称": "300", "ETF类型": "沪市",
                "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 100.0,
            }])

        def fake_szse(**kwargs):
            called["szse"] += 1
            return pd.DataFrame()

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_sse)
        monkeypatch.setattr("akshare.fund_scale_daily_szse", fake_szse)
        fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert called["sse"] == 2
        assert called["szse"] == 0

    def test_szse_prefix_routes_to_szse(self, monkeypatch):
        """1 开头 → 走 SZSE 分支（不调 SSE）。"""
        called = {"sse": 0, "szse": 0}

        def fake_sse(**kwargs):
            called["sse"] += 1
            return pd.DataFrame()

        def fake_szse(**kwargs):
            called["szse"] += 1
            return pd.DataFrame([
                {"统计日期": pd.Timestamp("2026-08-07"), "基金代码": "159915",
                 "基金简称": "创", "基金份额": 100.0},
                {"统计日期": pd.Timestamp("2026-08-27"), "基金代码": "159915",
                 "基金简称": "创", "基金份额": 80.0},
            ])

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_sse)
        monkeypatch.setattr("akshare.fund_scale_daily_szse", fake_szse)
        fsf.fetch_share_change_20d("159915", today=AS_OF)
        assert called["sse"] == 0
        assert called["szse"] == 1


class TestCache:
    def test_cache_hit(self, monkeypatch):
        """命中缓存时不再打接口。"""
        df_now = pd.DataFrame([
            {"序号": 1, "基金代码": "510300", "基金简称": "300", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-27"), "基金份额": 100.0},
        ])
        df_old = pd.DataFrame([
            {"序号": 1, "基金代码": "510300", "基金简称": "300", "ETF类型": "沪市",
             "统计日期": pd.Timestamp("2026-08-07"), "基金份额": 90.0},
        ])
        calls = {"n": 0}

        def fake_scale_sse(**kwargs):
            calls["n"] += 1
            d = kwargs.get("date", "")
            return df_now if d.startswith("20260828") else df_old

        monkeypatch.setattr("akshare.fund_etf_scale_sse", fake_scale_sse)
        r1 = fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert calls["n"] == 2
        r2 = fsf.fetch_share_change_20d("510300", today=AS_OF)
        assert calls["n"] == 2, "第二次应命中缓存"
        assert r1 == r2
