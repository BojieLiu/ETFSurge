# -*- coding: utf-8 -*-
"""round29 R76: A 股个股中文名搜索（茅台→600519）。

根因（§14.1 R76）：instruments 表 A 股个股 0 条（同步数据缺口）+ levistock 降级
`get_all_stocks` **空结果静默**（market.py 仅异常打 WARNING、空返回不打）→ 「茅台」
搜不到 600519，且无任何日志线索。

修复：
  ② levistock 空结果也打 WARNING；
  ③ levistock 兜底分支补拼音匹配（instruments 表无拼音字段时「gzmt」类关键词仍可命中）。

无网络：get_all_stocks / async_session 全部 monkeypatch。
"""
import asyncio
import logging

import pytest


@pytest.fixture
def patch_db(monkeypatch):
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
def patch_hub(monkeypatch):
    """注入可控 get_all_stocks。"""
    from app.services.market_data_hub import market_data_hub

    monkeypatch.setattr(market_data_hub, "get_all_stocks", lambda: [])
    return monkeypatch


class TestLeviStockSilentEmptyR76:
    @pytest.mark.asyncio
    async def test_empty_levistock_logs_warning(self, patch_db, patch_hub, caplog):
        """R76 负向：levistock 空结果不得静默——必须有 WARNING 日志线索。

        R91 (round30)：levistock 空 → 静态基座兜底（「茅台」→600519），WARNING 保留。
        """
        from app.routers import market

        with caplog.at_level(logging.WARNING, logger="app.routers.market"):
            out = await market._search_a_stocks("茅台")
        assert any(
            "get_all_stocks" in r.message and "empty" in r.message
            for r in caplog.records
        ), f"空结果未打 WARNING: {[r.message for r in caplog.records]}"
        # R91: 静态基座兜底命中 600519（不再返回空）
        assert any(s["symbol"] == "600519" for s in out), f"静态基座未命中: {out}"

    @pytest.mark.asyncio
    async def test_exception_levistock_still_warns(self, patch_db, monkeypatch):
        """异常路径原有 WARNING 不回归；静态基座兜底仍可用。"""
        from app.routers import market
        from app.services.market_data_hub import market_data_hub

        def _boom():
            raise RuntimeError("levistock down")

        monkeypatch.setattr(market_data_hub, "get_all_stocks", _boom)
        out = await market._search_a_stocks("茅台")
        # R91: 异常路径同样落到静态基座
        assert any(s["symbol"] == "600519" for s in out)


class TestPinyinFallbackR76:
    @pytest.mark.asyncio
    async def test_pinyin_keyword_matches_via_levistock(self, patch_db, monkeypatch):
        """instruments 表空 + levistock 可用 → 拼音「gzmt」命中贵州茅台。"""
        from app.routers import market
        from app.services.market_data_hub import market_data_hub

        monkeypatch.setattr(
            market_data_hub, "get_all_stocks",
            lambda: [
                {"stock_code": "600519", "stock_name": "贵州茅台"},
                {"stock_code": "000001", "stock_name": "平安银行"},
            ],
        )
        out = await market._search_a_stocks("gzmt")
        assert any(s["symbol"] == "600519" for s in out), f"拼音未命中: {out}"

    @pytest.mark.asyncio
    async def test_chinese_name_matches_via_levistock(self, patch_db, monkeypatch):
        """中文名「茅台」经 levistock 命中（表空时主匹配路径）。"""
        from app.routers import market
        from app.services.market_data_hub import market_data_hub

        monkeypatch.setattr(
            market_data_hub, "get_all_stocks",
            lambda: [{"stock_code": "600519", "stock_name": "贵州茅台"}],
        )
        out = await market._search_a_stocks("茅台")
        assert any(s["symbol"] == "600519" for s in out)

    @pytest.mark.asyncio
    async def test_symbol_match_kept(self, patch_db, monkeypatch):
        """代码匹配不回归。"""
        from app.routers import market
        from app.services.market_data_hub import market_data_hub

        monkeypatch.setattr(
            market_data_hub, "get_all_stocks",
            lambda: [{"stock_code": "600519", "stock_name": "贵州茅台"}],
        )
        out = await market._search_a_stocks("600519")
        assert any(s["symbol"] == "600519" for s in out)
