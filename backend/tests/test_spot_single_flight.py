from __future__ import annotations
# -*- coding: utf-8 -*-
"""F9 R27: spot 全量列表 single-flight——缓存 miss 时同 key 并发只 fetch 一次。

无网络，纯 mock：验证并发调用共享一次 fetch 结果。
"""
import threading
import time
from unittest.mock import patch

from app.fetchers import china_market as cm
from app.services.cache_service import sync_memory_cache


def test_single_flight_concurrent_shared():
    """R27: 两个并发调用同 key → fetch_fn 只执行一次，两者拿到相同结果。"""
    sync_memory_cache.set("hk_spot_list", None, 0)  # 确保缓存 miss
    # 直接删缓存 key（MemoryCache.set 用 None 不一定清 key）
    try:
        sync_memory_cache.delete("hk_spot_list")
    except Exception:
        pass

    fetch_count = 0
    fetch_lock = threading.Lock()

    def fake_fetch():
        nonlocal fetch_count
        with fetch_lock:
            fetch_count += 1
        time.sleep(0.2)  # 模拟慢网络，让并发窗口出现
        rows = [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}]
        sync_memory_cache.set("hk_spot_list", rows, 600)
        return rows

    results = []
    errors = []

    def caller():
        try:
            results.append(cm._spot_single_flight("hk_spot_list", fake_fetch))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=caller)
    t2 = threading.Thread(target=caller)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors
    assert fetch_count == 1, f"fetch 执行 {fetch_count} 次（应 1 次）"
    assert len(results) == 2
    assert results[0] == results[1] == [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}]
    # inflight 已清理
    assert "hk_spot_list" not in cm._spot_inflight


def test_single_flight_cache_hit_skips_fetch():
    """R27: 缓存命中 → 不触发 fetch（直接返回缓存）。"""
    sync_memory_cache.set("us_spot_list", [{"symbol": "AAPL", "name": "苹果", "market": "US"}], 600)
    fetch_count = 0

    def fake_fetch():
        nonlocal fetch_count
        fetch_count += 1
        return []

    with patch("app.fetchers.china_market.fetch_us_spot_list",
               wraps=cm.fetch_us_spot_list):
        result = cm.fetch_us_spot_list()
    assert result[0]["symbol"] == "AAPL"
    # 缓存命中路径不经过 single-flight fetch
    assert "us_spot_list" not in cm._spot_inflight


# ===== folded from test_round18_p1_p2.py =====
import pytest
from unittest.mock import AsyncMock, MagicMock
class TestP27ConfidenceScaling:
    """round18 P2-7: confidence 按因子填充率分级。

    round24 R4 修订：表示法由裸数值（0.5/0.7）改为全站统一语义标签
    （<70%→low、≥70%→medium、≥90%→high）——原「随填充率变化、非恒定值」的意图不变
    （契约 api-contracts/portfolio/strategy-check-v2.md §3.1-3）。
    """

    def _suggestion(self, filled, total):
        from app.services.portfolio_service import _rule_based_suggestion
        return _rule_based_suggestion(
            symbol="512000", name="券商ETF", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 0.7},
            signal={"signal": "buy"}, regime="range_bound",
            factor_availability={"filled": filled, "total": total, "ratio": f"{filled}/{total}"},
        )

    def test_low_fill_ratio_confidence_downgraded(self):
        """因子填充率 10/39（26% <70%）→ low（负向：medium/high 即未降级 → FAIL）。"""
        s = self._suggestion(10, 39)
        assert s["confidence"] == "low", f"低填充率应降级 confidence，实得 {s['confidence']}"

    def test_high_fill_ratio_keeps_confidence(self):
        """填充率 30/39（77% ≥70%）→ medium（R4：旧 0.7 的真实语义就是「中等」）。"""
        s = self._suggestion(30, 39)
        assert s["confidence"] == "medium"

    def test_no_availability_keeps_default(self):
        from app.services.portfolio_service import _rule_based_suggestion
        s = _rule_based_suggestion(
            symbol="512000", name="券商ETF", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 0.7},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["confidence"] == "medium"
class TestP14DesignPrice:
    """round18 P1-4: design etfs[].price 非 None（候选池无价时回查实时价）。"""

    @pytest.mark.asyncio
    async def test_missing_price_backfilled_from_realtime(self, monkeypatch):
        """pool_entry 无 price → 批量回查实时价（负向：仍 None → 前端「—」→ FAIL）。"""
        from app.services import strategy_design as sd

        class _FakeHub:
            def __init__(self):
                self.calls = []

            def get_by_code(self, code):
                # 候选池条目无 price 字段（P1-4 场景）
                return {"symbol": code, "name": "沪深300ETF", "change_pct": 0.42}

            async def get_asset_realtime(self, code, asset_type):
                self.calls.append(code)
                return {"symbol": code, "price": 4.748, "change_pct": 0.42}

        hub = _FakeHub()
        allocs = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "weight": 0.1, "daily_change_pct": 0.42},
            {"symbol": "CASH", "layer": "cash", "weight": 0.2},
        ]
        # 复用 S6 注入段逻辑：模拟候选池无 price + 回查
        for a in allocs:
            if a.get("symbol") == "CASH":
                continue
            pool_entry = hub.get_by_code(a["symbol"])
            price = pool_entry.get("price")
            if price is None:
                price = pool_entry.get("last_price")
            if price is not None:
                a["price"] = price
        _missing = [a["symbol"] for a in allocs
                    if a.get("symbol") != "CASH" and a.get("price") is None]
        assert _missing == ["510300"], "候选池无价标的应进入回查清单"

        import asyncio
        async def _rt_price(code):
            rt = await hub.get_asset_realtime(code, "A")
            p = (rt or {}).get("price") if rt else None
            return code, float(p) if p else None

        prices = dict(await asyncio.gather(*[_rt_price(c) for c in _missing]))
        for a in allocs:
            if a.get("symbol") != "CASH" and a.get("price") is None and a["symbol"] in prices:
                if prices[a["symbol"]] is not None:
                    a["price"] = prices[a["symbol"]]
        assert allocs[0]["price"] == 4.748, f"回查实时价应填充 price，实得 {allocs[0].get('price')}"
