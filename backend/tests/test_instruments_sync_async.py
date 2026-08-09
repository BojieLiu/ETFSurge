"""
O1 (docs/archived/round8-rediagnosis.md §7 P0-新): instruments 同步全链路改造。

P0-新 根因: scripts/sync_instruments.py 的 `_fetch_akshare_list` 对 akshare 做裸同步调用
（stock_us_spot_em 在当前网络环境永久卡死）→ 阻塞事件循环 → asyncio.wait(timeout=60)
超时回调无法触发 → uvicorn 永不 bind 端口。

修复（已拍板 A+B 结合）:
  A. akshare 调用全部改走 asyncio.to_thread（线程池，不占事件循环）；
  B. 每段 asyncio.wait_for 超时（US 段 20s / 其他 30s）+ INSTRUMENTS_SYNC_DISABLED=1
     环境开关 + 服务层整体超时（默认 120s）；任一段失败仅降级该段。
"""

import asyncio
import inspect

import pytest

from scripts import sync_instruments as si
from app.services import instruments_sync as ins


class TestNoBareSyncAkshare:
    def test_fetch_akshare_list_uses_to_thread(self):
        """裸同步拦截：akshare 调用必须经 asyncio.to_thread（async-lint 语义）。"""
        src = inspect.getsource(si._fetch_akshare_list)
        assert "asyncio.to_thread" in src
        # 无裸同步调用模式（await 之前直接 getattr(ak, ...)()）
        assert "getattr(ak, fn_name)()" not in src


class TestSegmentTimeout:
    @pytest.mark.asyncio
    async def test_segment_times_out_without_hanging(self, monkeypatch):
        """段超时：慢段在超时窗口内结束（不阻塞事件循环），失败段仅降级。"""
        orig_timeouts = dict(si._SEGMENT_TIMEOUTS)
        orig_fetch = si._fetch_akshare_list
        orig_a = si._fetch_a_stock_list

        async def slow_fetch(*args, **kwargs):
            await asyncio.sleep(10)
            return [{"symbol": "X", "name": "Y"}]

        async def fast_a():
            return [{"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock",
                     "pinyin": "", "first_letter": ""}]

        try:
            monkeypatch.setattr(si, "_SEGMENT_TIMEOUTS",
                                {"A股个股": 0.3, "A股ETF": 0.3, "港股": 0.3, "港股ETF": 0.3, "美股": 0.3})
            monkeypatch.setattr(si, "_fetch_akshare_list", slow_fetch)
            monkeypatch.setattr(si, "_fetch_a_stock_list", fast_a)
            # round9 P1-2: _fetch_us_list 有新浪降级分支（真实 urllib 网络）——mock 走
            # 超时降级路径，避免测试环境真实请求新浪（6 页 × 8s 最长 48s 卡顿）。
            monkeypatch.setattr(si, "_fetch_us_list", slow_fetch)
            monkeypatch.setattr(si, "_fetch_hk_etf_list", slow_fetch)
            results = await si.collect_all()
            # 慢段被超时降级，但 A 股个股段（fast）结果保留
            assert any(r["symbol"] == "600519" for r in results)
        finally:
            monkeypatch.setattr(si, "_SEGMENT_TIMEOUTS", orig_timeouts)
            monkeypatch.setattr(si, "_fetch_akshare_list", orig_fetch)
            monkeypatch.setattr(si, "_fetch_a_stock_list", orig_a)

    @pytest.mark.asyncio
    async def test_us_timeout_shorter_than_others(self):
        """US 段超时 ≤ 其他段（美股源最容易黑洞，需最短暴露面）。"""
        assert si._SEGMENT_TIMEOUTS.get("美股", 999) <= si._SEGMENT_TIMEOUTS.get("港股", 0)
        assert si._SEGMENT_TIMEOUTS.get("美股", 999) <= si._SEGMENT_TIMEOUTS.get("A股个股", 0)


class TestDisabledFlag:
    def test_sync_disabled_env(self, monkeypatch):
        monkeypatch.setenv("INSTRUMENTS_SYNC_DISABLED", "1")
        assert si._sync_disabled() is True
        monkeypatch.setenv("INSTRUMENTS_SYNC_DISABLED", "true")
        assert si._sync_disabled() is True
        monkeypatch.delenv("INSTRUMENTS_SYNC_DISABLED")
        assert si._sync_disabled() is False

    @pytest.mark.asyncio
    async def test_service_skips_when_disabled(self, monkeypatch):
        """INSTRUMENTS_SYNC_DISABLED=1 → sync_instruments_table 直接返回 0。"""
        monkeypatch.setenv("INSTRUMENTS_SYNC_DISABLED", "1")
        n = await ins.sync_instruments_table()
        assert n == 0

    @pytest.mark.asyncio
    async def test_service_overall_timeout(self, monkeypatch):
        """服务层整体超时：慢采集在 INSTRUMENTS_SYNC_TIMEOUT 内结束，返回 0 不抛。"""
        async def slow_collect():
            await asyncio.sleep(10)
            return [{"symbol": "X", "name": "Y"}]

        monkeypatch.setattr(ins, "_collect", slow_collect)
        monkeypatch.setattr(ins, "_INSTRUMENTS_SYNC_TIMEOUT", 0.3)
        n = await ins.sync_instruments_table()
        assert n == 0
