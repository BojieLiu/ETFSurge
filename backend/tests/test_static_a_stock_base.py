# -*- coding: utf-8 -*-
"""round30 R91: A股个股中文名搜索兜底（instruments 空 + levistock 空 → 静态基座）。

根因（§14.1 R91）：instruments 表 A 股个股 0 条（同步数据缺口）+ levistock 盘后
空结果 → 「茅台/A」=0 且无静态兜底。

修复：`_search_a_stocks` 在 instruments 与 levistock 双空时降级到静态个股基座
（_STATIC_A_STOCK_BASE，收录高频个股 600519 等），保证「茅台」→600519 盘后也可搜。

无网络：get_all_stocks / async_session 全部 monkeypatch。
"""
import asyncio
import logging

import pytest


@pytest.fixture
def patch_db_empty(monkeypatch):
    """instruments 本地表查询返回空（模拟 0 条数据缺口）。"""
    import contextlib

    class _FakeSession:
        async def execute(self, *a, **k):
            class _R:
                def scalars(self):
                    return self
                def all(self):
                    return []
            return _R()

    @contextlib.asynccontextmanager
    async def _empty_session():
        yield _FakeSession()

    monkeypatch.setattr("app.routers.market.async_session", _empty_session)
    return monkeypatch


@pytest.fixture
def patch_hub_empty(monkeypatch):
    """levistock get_all_stocks 返回空（盘后）。"""
    from app.services.market_data_hub import market_data_hub
    monkeypatch.setattr(market_data_hub, "get_all_stocks", lambda: [])
    return monkeypatch


class TestStaticBaseFallbackR91:
    @pytest.mark.asyncio
    async def test_maotai_found_via_static_base(self, patch_db_empty, patch_hub_empty):
        """instruments+levistock 双空 → 静态基座命中「茅台」→600519。"""
        from app.routers import market
        out = await market._search_a_stocks("茅台")
        assert any(s["symbol"] == "600519" for s in out), f"静态基座未命中: {out}"

    @pytest.mark.asyncio
    async def test_code_match_static_base(self, patch_db_empty, patch_hub_empty):
        """静态基座支持代码匹配。"""
        from app.routers import market
        out = await market._search_a_stocks("600519")
        assert any(s["symbol"] == "600519" for s in out)

    @pytest.mark.asyncio
    async def test_unknown_keyword_returns_empty(self, patch_db_empty, patch_hub_empty):
        """静态基座未收录的冷门词 → 空（不编造）。"""
        from app.routers import market
        out = await market._search_a_stocks("星河生物")
        assert out == []

    @pytest.mark.asyncio
    async def test_static_base_used_after_levistock_empty(self, patch_db_empty, patch_hub_empty, caplog):
        """levistock 空 + 静态基座命中 → 有 WARNING 日志线索（非静默）。"""
        from app.routers import market
        with caplog.at_level(logging.WARNING, logger="app.routers.market"):
            out = await market._search_a_stocks("茅台")
        assert any("empty" in r.message for r in caplog.records), "空结果未打 WARNING"
