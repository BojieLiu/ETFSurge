"""F8 剩余 (round6 §14.5): 指数实时多源降级——get_index_realtime 兜底。

现象（14.5）：设计报告"今日涨跌"列全"数据源不可用"——get_index_realtime()
为空（东财 push2 限流 RemoteDisconnected）→ 行情注入失败而因子评分正常。

R6-F6 已实现 advice 快照注入兜底（get_index_realtime 空时从 market_service
缓存 A 股段补）。F8 剩余：_refresh_market_snapshot 的 _fetch_indices 在
get_global_indices 失败/返回空时，用东财 push2delay 直连拉 A 股主要指数
（沪深300/上证50/中证500/科创50/创业板）兜底，使 _index_realtime_cache
非空（设计报告今日涨跌可用）。
"""
import asyncio

import pytest

from app.services.market_data_hub import MarketDataHub

# push2delay 指数行（与 _fetch_a_index_rows 归一化输出一致）
_INDEX_ROWS = [
    {"symbol": "sh000300", "code": "000300", "name": "沪深300", "price": 3980.5, "change_pct": 0.35, "amount": 3.2e11},
    {"symbol": "sh000016", "code": "000016", "name": "上证50", "price": 2680.0, "change_pct": 0.12, "amount": 1.1e11},
    {"symbol": "sh000905", "code": "000905", "name": "中证500", "price": 5680.0, "change_pct": -0.25, "amount": 1.8e11},
    {"symbol": "sh000688", "code": "000688", "name": "科创50", "price": 1020.0, "change_pct": 1.15, "amount": 6.5e10},
    {"symbol": "sz399006", "code": "399006", "name": "创业板指", "price": 2200.0, "change_pct": 0.9, "amount": 9.0e10},
]


class TestIndexRealtimeFallback:
    def test_fallback_injects_major_indices_when_global_empty(self, monkeypatch):
        """F8: get_global_indices 空/失败 → push2delay 兜底注入主要指数。"""
        async def _empty_global():
            return {}
        hub = MarketDataHub()
        hub._index_realtime_cache = None
        monkeypatch.setattr(hub, "_fetch_a_index_rows", lambda: _INDEX_ROWS)

        # 直接调用内部协程（绕过公共 refresh 锁）
        monkeypatch.setattr(
            "app.services.market_service.get_global_indices", _empty_global)
        hub._index_realtime_cache = []
        asyncio.run(hub._refresh_market_snapshot_indices_only())

        cache = hub.get_index_realtime()
        names = [(i.get("name"), i.get("region")) for i in cache]
        assert any("沪深300" in (n or "") for n, _ in names), f"应含沪深300, got {names}"
        assert any("创业板" in (n or "") for n, _ in names), f"应含创业板指, got {names}"

    def test_fallback_keeps_global_when_available(self, monkeypatch):
        """F8: get_global_indices 正常时不用兜底（回归）。"""
        async def _full_global():
            return {"A": [{"name": "沪深300", "price": 3980.0, "region": "A"}]}
        hub = MarketDataHub()
        hub._index_realtime_cache = []
        monkeypatch.setattr(
            "app.services.market_service.get_global_indices", _full_global)
        monkeypatch.setattr(hub, "_fetch_a_index_rows", lambda: _INDEX_ROWS)
        asyncio.run(hub._refresh_market_snapshot_indices_only())
        cache = hub.get_index_realtime()
        assert len(cache) == 1 and cache[0]["name"] == "沪深300"
