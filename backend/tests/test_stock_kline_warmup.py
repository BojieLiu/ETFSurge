# -*- coding: utf-8 -*-
"""round30 R88: 个股 K 线缓存扩展（方案 A——个股纳入 Hub K 线预热符号集）。

根因（§14.5）：design-data warmup 只预热 pool 内 ETF，个股（600519/AAPL）不在
hub._kline_cache_rows → symbol-analysis 的 R60 兜底 get_kline_rows_any 只查 hub
缓存取空 → 盘后 indicators data_available=false。

修复：warmup 符号集从「pool ETF」扩展为「pool ETF + 持仓个股段（A 股 600519 / HK
00700 / US AAPL）」，复用同一缓存域与 R86 落盘路径。

无网络：DB 查询 monkeypatch。

⚠️ round58：`_kline_warmup_symbols` / `_kline_warmup_holdings_symbols` 已从
`app.main` 下沉到 `app.tasks.startup`（唯一调用点在那里；main 反向 import 会成循环）。
**monkeypatch 必须打定义处 `app.tasks.startup.*`**——打 `app.main.*` 只会改到
re-export 别名，函数体在 startup 模块 globals 里查找，不会生效（静默失效的测试陷阱）。
`from app.main import ...` 仍可用（re-export 保持导入面），但断言的是同一个函数对象。
"""
import pytest

# 定义处（monkeypatch 目标）——与 app.main 的 re-export 别名区分开
_HOLDINGS_PATCH_TARGET = "app.tasks.startup._kline_warmup_holdings_symbols"


@pytest.fixture
def patch_holdings(monkeypatch):
    """模拟 DB 持仓：一只 ETF + 一只 A 股个股。"""
    async def _fake_query():
        return ["510300", "600519"]
    monkeypatch.setattr(_HOLDINGS_PATCH_TARGET, _fake_query)
    return monkeypatch


class TestKlineWarmupSymbolsR88:
    @pytest.mark.asyncio
    async def test_warmup_symbols_include_holdings(self, monkeypatch):
        """warmup 符号集 = pool ETF + 持仓个股。"""
        from app.tasks.startup import _kline_warmup_symbols

        async def _holdings():
            return ["510300", "600519", "00700", "AAPL"]
        monkeypatch.setattr(_HOLDINGS_PATCH_TARGET, _holdings)

        syms = await _kline_warmup_symbols(["510050", "512880", "518880"])
        assert "600519" in syms, "A 股个股未纳入 K 线预热"
        assert "AAPL" in syms, "美股个股未纳入 K 线预热"
        assert "510050" in syms  # pool ETF 保留
        assert syms == list(dict.fromkeys(syms)), "不应有重复符号"

    @pytest.mark.asyncio
    async def test_empty_holdings_keeps_pool(self, monkeypatch):
        """无持仓个股时退化为纯 pool 符号集（不回归）。"""
        from app.tasks.startup import _kline_warmup_symbols

        async def _holdings():
            return []
        monkeypatch.setattr(_HOLDINGS_PATCH_TARGET, _holdings)

        syms = await _kline_warmup_symbols(["510050", "512880"])
        assert syms == ["510050", "512880"]

    @pytest.mark.asyncio
    async def test_holdings_query_failure_is_silent(self, monkeypatch):
        """持仓查询失败静默（不影响 pool 符号集）。"""
        from app.tasks.startup import _kline_warmup_symbols

        async def _holdings():
            raise RuntimeError("db down")
        monkeypatch.setattr(_HOLDINGS_PATCH_TARGET, _holdings)

        syms = await _kline_warmup_symbols(["510050"])
        assert syms == ["510050"]

    @pytest.mark.asyncio
    async def test_main_reexport_is_the_same_function(self):
        """main 的 re-export 与定义处是同一函数对象（导入面兼容性守卫）。

        防「只在一处定义、另一处成了副本」这类漂移：副本会让调用点走旧实现。
        """
        from app.main import _kline_warmup_symbols as via_main
        from app.tasks.startup import _kline_warmup_symbols as via_startup
        assert via_main is via_startup

    def test_patch_target_is_the_definition_site(self):
        """守卫：monkeypatch 目标字符串必须指向定义模块（防有人改回 app.main）。"""
        assert _HOLDINGS_PATCH_TARGET.startswith("app.tasks.startup.")
