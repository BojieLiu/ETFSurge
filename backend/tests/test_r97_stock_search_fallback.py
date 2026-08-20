# -*- coding: utf-8 -*-
"""round31 R97: 个股搜索 + instruments 分段同步修复。

根因（§4.5）：instruments 同步 A股个股段单段 30s 超时即弃全段（EM 主源黑洞占满
预算 → 新浪降级链没机会执行 → 表内无 A股个股 → 茅台搜不到）；`_search_a_stocks`
levistock 全量挂起时无超时保护（静态基座 `_STATIC_A_STOCK_BASE` 未兜住）。

修复：
  ① `_fetch_a_stock_list` / `_fetch_hk_list` 每源独立超时（EM 12s / Sina 15s），
     单源超时不弃全段（降级链仍执行）；
  ② `_search_a_stocks` levistock 拉取加超时（8s），挂起/空/异常均回落静态基座。

无网络：monkeypatch 断言。
"""
import asyncio
import pytest


class TestSyncInstrumentsPerSourceTimeout:
    @pytest.mark.asyncio
    async def test_a_stock_em_timeout_falls_back_to_sina(self, monkeypatch):
        """EM 源超时 → 新浪降级链仍执行，返回新浪行（R97 ①）。"""
        from app.fetchers import sync_instruments as si

        async def _fake(fn, symbol_col, name_col, market, asset_type):
            if fn == "stock_zh_a_spot_em":
                await asyncio.sleep(30)  # EM 黑洞，超时被 wait_for 掐断
                return [{"symbol": "600000", "name": "浦发银行"}]
            return [{"symbol": "600519", "name": "贵州茅台"}]

        monkeypatch.setattr(si, "_fetch_akshare_list", _fake)
        monkeypatch.setattr(si, "_A_STOCK_SOURCE_TIMEOUTS",
                            {"em": 0.05, "sina": 5.0})
        rows = await si._fetch_a_stock_list()
        assert any(r["symbol"] == "600519" for r in rows), f"应命中新浪降级链: {rows}"

    @pytest.mark.asyncio
    async def test_hk_em_timeout_falls_back_to_sina(self, monkeypatch):
        """港股段同样每源超时降级（容器港股 FAILED 修复，R97 ①）。"""
        from app.fetchers import sync_instruments as si

        async def _fake(fn, symbol_col, name_col, market, asset_type):
            if fn == "stock_hk_main_board_spot_em":
                await asyncio.sleep(30)
                return [{"symbol": "00001", "name": "长和"}]
            return [{"symbol": "00700", "name": "腾讯控股"}]

        monkeypatch.setattr(si, "_fetch_akshare_list", _fake)
        monkeypatch.setattr(si, "_HK_SOURCE_TIMEOUTS", {"em": 0.05, "sina": 5.0})
        rows = await si._fetch_hk_list()
        assert any(r["symbol"] == "00700" for r in rows), f"应命中新浪降级链: {rows}"

    @pytest.mark.asyncio
    async def test_both_sources_fail_raises(self, monkeypatch):
        """两源全失败 → 抛 RuntimeError（collect_all 记 ERROR，sync 保留旧表）。"""
        from app.fetchers import sync_instruments as si

        async def _fail(fn, symbol_col, name_col, market, asset_type):
            raise ConnectionError("EM down")

        monkeypatch.setattr(si, "_fetch_akshare_list", _fail)
        monkeypatch.setattr(si, "_A_STOCK_SOURCE_TIMEOUTS", {"em": 1.0, "sina": 1.0})
        with pytest.raises(RuntimeError):
            await si._fetch_a_stock_list()


class TestSearchStaticBaseFallback:
    def _patch_search_env(self, monkeypatch, stocks=None, stocks_raise=False):
        """构造 instruments 空表 + levistock 行为的 _search_a_stocks 环境。"""
        import app.routers.market as market_mod

        class _FakeSession:
            async def execute(self, stmt):
                return _FakeResult()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        class _FakeResult:
            def scalars(self):
                return self
            def all(self):
                return []  # instruments 表无 A股个股段

        monkeypatch.setattr(market_mod, "async_session", _FakeSession)

        # asyncio.to_thread 调用同步函数——mock 用同步（async 函数经 to_thread
        # 会生成从未 await 的 coroutine，触发 RuntimeWarning）
        def _stocks_impl():
            if stocks_raise:
                raise ConnectionError("levistock down")
            return stocks or []

        monkeypatch.setattr(market_mod.market_data_hub, "get_all_stocks", _stocks_impl)
        # 缩短 levistock 超时便于测试
        monkeypatch.setattr(market_mod, "_LEVISTOCK_SEARCH_TIMEOUT", 0.05)

    @pytest.mark.asyncio
    async def test_static_base_when_levistock_empty(self, monkeypatch):
        """instruments + levistock 双空 → 静态基座命中（茅台→600519，R97 ②）。"""
        import app.routers.market as market_mod
        self._patch_search_env(monkeypatch, stocks=[])
        results = await market_mod._search_a_stocks("茅台")
        assert any(r["symbol"] == "600519" and r["name"] == "贵州茅台"
                   for r in results), f"静态基座应命中 600519: {results}"

    @pytest.mark.asyncio
    async def test_static_base_when_levistock_raises(self, monkeypatch):
        """levistock 异常 → 静态基座仍命中（R97 ②）。"""
        import app.routers.market as market_mod
        self._patch_search_env(monkeypatch, stocks_raise=True)
        results = await market_mod._search_a_stocks("600519")
        assert any(r["symbol"] == "600519" for r in results)

    @pytest.mark.asyncio
    async def test_static_base_when_levistock_hangs(self, monkeypatch):
        """levistock 挂起 → 超时后静态基座仍命中（R97 ② 负向：不无限等待）。"""
        import app.routers.market as market_mod

        class _FakeSession:
            async def execute(self, stmt):
                return _FakeResult()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        class _FakeResult:
            def scalars(self):
                return self
            def all(self):
                return []

        monkeypatch.setattr(market_mod, "async_session", _FakeSession)
        monkeypatch.setattr(market_mod, "_LEVISTOCK_SEARCH_TIMEOUT", 0.05)

        def _hang():
            import time
            time.sleep(1.5)  # 远超测试超时（同步挂起，wait_for 掐断 to_thread）
            return []

        monkeypatch.setattr(market_mod.market_data_hub, "get_all_stocks", _hang)
        results = await market_mod._search_a_stocks("茅台")
        assert any(r["symbol"] == "600519" for r in results)

    @pytest.mark.asyncio
    async def test_unknown_keyword_returns_empty(self, monkeypatch):
        """静态基座未收录词 → 返回空（不编造，诚实降级）。"""
        import app.routers.market as market_mod
        self._patch_search_env(monkeypatch, stocks=[])
        results = await market_mod._search_a_stocks("不存在之标")
        assert results == []
