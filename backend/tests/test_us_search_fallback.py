"""R6-F9 (round6 §十 R6-10): US 个股名称搜索备用源。

背景：akshare US spot 源不可用（东财限流）→ 搜 apple 0 条（代码 AAPL 可搜）。
修复：US spot 拉取失败/空时，用本地 instruments 表（US 段，F17 自动同步）补搜。
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services import market_service as ms


def test_us_spot_failure_falls_back_to_local_instruments(monkeypatch):
    """fetch_us_spot_list 失败/空 → 本地 instruments 表 US 段补搜（apple 非空）。"""
    us_rows = [
        type("R", (), {"symbol": "AAPL", "name": "苹果", "market": "US", "is_active": True})(),
        type("R", (), {"symbol": "MSFT", "name": "微软", "market": "US", "is_active": True})(),
    ]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            return self

        def scalars(self):
            return self

        def all(self):
            return us_rows

    import app.services.market_service as _ms
    monkeypatch.setattr(_ms, "async_session", lambda: _FakeSession())
    # HK spot 正常返回空，US spot 失败（模拟限流）——search_hk_us 内部
    # `from ..fetchers.china_market import fetch_us_spot_list` 读模块属性
    monkeypatch.setattr("app.fetchers.china_market.fetch_us_spot_list", lambda: [])
    monkeypatch.setattr("app.fetchers.china_market.fetch_hk_spot_list", lambda: [])

    async def _go():
        # 直接调用 search_hk_us：include_stocks=True 触发 spot 段
        return await ms.search_hk_us("apple", include_stocks=True, enrich=False)

    import asyncio
    results = asyncio.run(_go())
    us_hits = [r for r in results if r.get("market") == "US" and r.get("type") == "stock"]
    assert any("apple" in (r.get("name") or "").lower() or r.get("symbol") == "AAPL"
               for r in us_hits), f"本地 US instruments 补搜应命中 apple, got {results[:5]}"
