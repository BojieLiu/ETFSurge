from __future__ import annotations
"""
O30 (docs/archived/round7-rediagnosis.md §7 P30①): /search 增加板块/指数段（kind 参数）。

P30① 问题: /search 只返回 stock/etf/HK/US 段——无板块（sectors 表 991 行）与
指数（indices_meta 表 588 行）段；前端 sector/index 模式无下拉建议。

修复: 新增 kind 参数（symbol/sector/index/all，默认 all）——sector 查 sectors 表
name ilike；index 查 indices_meta 表 name/pinyin/first_letter ilike；
all（默认）在现有 stock/etf/HK/US 段后尾部追加 sector/index 段（向后兼容）。

P3-6 (round17): 并入 test_p022_us_index_search.py（P0-22 美股指数搜索，同域：
app.routers.market 搜索 + _lookup_index_market 市场识别）。
"""

import pytest
from unittest.mock import patch

from app.routers import market as market_router


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows, kw_filter_attr="name"):
        self._rows = rows
        self._attr = kw_filter_attr

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        # 模拟 ilike 过滤：从编译参数提取 %kw%（SQLAlchemy 绑定参数形式）
        try:
            compiled = stmt.compile()
            params = compiled.params
            kw = None
            for v in params.values():
                if isinstance(v, str) and "%" in v:
                    kw = v.strip("%")
                    break
        except Exception:
            kw = None
        filtered = self._rows
        if kw:
            filtered = [r for r in self._rows if kw.lower() in getattr(r, self._attr, "").lower()]
        return _ScalarRows(filtered)


class _FakeSector:
    def __init__(self, code, name, stype="industry"):
        self.code = code
        self.name = name
        self.type = stype


class _FakeIndex:
    def __init__(self, symbol, name, market="A", category="broad"):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.category = category
        self.pinyin = ""
        self.first_letter = ""


@pytest.mark.asyncio
async def test_search_sector_kind():
    """kind=sector → sectors 表 name ilike 命中，type='sector'。"""
    rows = [
        _FakeSector("BK0475", "半导体"),
        _FakeSector("BK1036", "光伏设备"),
    ]
    with patch("app.routers.market.async_session",
               lambda: _FakeSession(rows, kw_filter_attr="name")):
        result = await market_router._search_sectors("半导")
    assert len(result) == 1
    assert result[0]["symbol"] == "BK0475"
    assert result[0]["name"] == "半导体"
    assert result[0]["type"] == "sector"


@pytest.mark.asyncio
async def test_search_index_kind():
    """kind=index → indices_meta 表 name/pinyin/first_letter ilike，type='index'。"""
    rows = [
        _FakeIndex("sh000300", "沪深300"),
        _FakeIndex("sh000001", "上证指数"),
    ]
    with patch("app.routers.market.async_session",
               lambda: _FakeSession(rows, kw_filter_attr="name")):
        result = await market_router._search_indices("沪深")
    assert len(result) == 1
    assert result[0]["symbol"] == "sh000300"
    assert result[0]["type"] == "index"


@pytest.mark.asyncio
async def test_search_kind_all_appends_sector_index():
    """kind=all（默认）→ 现有段 + 尾部 sector/index 段。"""
    rows_sector = [_FakeSector("BK0475", "半导体")]
    rows_index = [_FakeIndex("sh000300", "沪深300")]

    class _SwitchingSession:
        def __init__(self):
            self._call = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            self._call += 1
            if "sectors" in str(stmt):
                return _ScalarRows(rows_sector)
            if "indices_meta" in str(stmt):
                return _ScalarRows(rows_index)
            return _ScalarRows([])

    async def fake_search_etf(keyword):
        return [{"symbol": "510300", "name": "沪深300ETF", "market": "A",
                 "asset_type": "etf", "type": "etf"}]

    async def fake_search_hk_us(keyword, enrich=False, include_stocks=False, market=None):
        return []

    with patch("app.routers.market.async_session", lambda: _SwitchingSession()), \
         patch("app.services.market_data_hub.market_data_hub.search_etf", new=fake_search_etf), \
         patch("app.routers.market.search_hk_us", new=fake_search_hk_us):
        result = await market_router.search("半导体", kind="all")
    types = [r.get("type") for r in result]
    assert "sector" in types, f"kind=all 应含 sector 段: {types}"
    assert "index" in types, f"kind=all 应含 index 段: {types}"
    assert "etf" in types, "现有 etf 段保留"


@pytest.mark.asyncio
async def test_search_kind_symbol_no_sector():
    """kind=symbol → 仅现有段，不追加 sector/index。"""
    async def fake_search_etf(keyword):
        return [{"symbol": "510300", "name": "沪深300ETF", "market": "A",
                 "asset_type": "etf", "type": "etf"}]

    async def fake_search_hk_us(keyword, enrich=False, include_stocks=False, market=None):
        return []

    with patch("app.routers.market.async_session", lambda: _FakeSession([])), \
         patch("app.services.market_data_hub.market_data_hub.search_etf", new=fake_search_etf), \
         patch("app.routers.market.search_hk_us", new=fake_search_hk_us):
        result = await market_router.search("510300", kind="symbol")
    assert all(r.get("type") != "sector" for r in result)
    assert all(r.get("type") != "index" for r in result)


# ── P0-22 (round16 3.24, 自 test_p022_us_index_search.py 并入): 美股指数搜索 ──────
# 验收: ① market=US 只返回 US 指数（负向：混入 HK/A → FAIL）；
#       ② 指数代码（symbol）可搜（SPX 输入命中）；③ _lookup_index_market 识别 US/HK。
# （_ScalarRows 复用上方既有实现——两文件原实现相同，删除重复类定义）


class _Idx:
    def __init__(self, symbol, name, market):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.pinyin = ""
        self.first_letter = ""
        self.is_active = True


class _IdxSession:
    """按 symbol/name 关键词 + market where 过滤的 fake async session。"""

    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        compiled = stmt.compile()
        params = compiled.params
        kw = None
        for v in params.values():
            if isinstance(v, str) and "%" in v:
                kw = v.strip("%")
                break
        market = None
        for v in params.values():
            if v in ("US", "HK", "A"):
                market = v
                break
        out = []
        for r in self._rows:
            if market is not None and r.market != market:
                continue
            if kw and kw.lower() not in r.symbol.lower() and kw.lower() not in r.name.lower():
                continue
            out.append(r)
        return _ScalarRows(out)


@pytest.mark.asyncio
async def test_search_indices_us_market_only_returns_us():
    """market=US 只返回 US 指数——负向：混入 HK/A 指数 → FAIL。"""
    rows = [
        _Idx("SPX", "标普500指数", "US"),
        _Idx("IXIC", "纳斯达克综合指数", "US"),
        _Idx("HSI", "恒生指数", "HK"),
        _Idx("sh000300", "沪深300", "A"),
    ]
    with patch("app.routers.market.async_session", lambda: _IdxSession(rows)):
        result = await market_router._search_indices("标普", market="US")
    assert len(result) == 1
    assert result[0]["symbol"] == "SPX"
    assert all(r["market"] == "US" for r in result), f"US 搜索不得混入他市场: {result}"


@pytest.mark.asyncio
async def test_search_indices_symbol_searchable():
    """指数代码（symbol）可搜——SPX 输入命中（负向：代码 0 命中 → FAIL）。"""
    rows = [
        _Idx("SPX", "标普500指数", "US"),
        _Idx("HSI", "恒生指数", "HK"),
    ]
    with patch("app.routers.market.async_session", lambda: _IdxSession(rows)):
        result = await market_router._search_indices("SPX", market="US")
    assert any(r["symbol"] == "SPX" for r in result), f"SPX 代码搜索应命中: {result}"


def test_lookup_index_market_recognizes_us_hk(monkeypatch):
    """_lookup_index_market 识别 US/HK 指数（P0-22④ realtime 防护前置）。"""
    from app.services import market_service as ms_mod

    monkeypatch.setattr(ms_mod, "_INDEX_MARKET_CACHE", {"SPX": "US", "HSI": "HK", "SH000300": "A"})
    import time
    monkeypatch.setattr(ms_mod, "_INDEX_MARKET_CACHE_TS", time.time())
    assert ms_mod._lookup_index_market_sync("SPX") == "US"
    assert ms_mod._lookup_index_market_sync("hsi") == "HK"  # 大小写不敏感
    assert ms_mod._lookup_index_market_sync("SH000300") == "A"
    assert ms_mod._lookup_index_market_sync("UNKNOWN") == ""


# ===== folded from test_phase2a_data_quality.py =====
import ast
import os
class TestP0_3_HKUSSearch:
    """P0.3: Ensure search supports HK/US stocks."""

    def test_search_includes_hk_and_us_fallbacks(self):
        """Search function should include HK/US data source fallbacks."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_service.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should mention HK/US market handling
        hk_refs = sum(1 for ref in ["港股", "hongkong", "hong_kong", "hsi", "HK"] if ref.lower() in content.lower())
        us_refs = sum(1 for ref in ["美股", "us stock", "spy", "qqq"] if ref.lower() in content.lower())
        assert hk_refs > 0 or us_refs > 0, (
            "market_service should handle HK/US stock fallbacks in search"
        )


# ===================================================================
# merged from test_round26_q46_index_search.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round26 Q4/Q6: 指数搜索索引补全 + akshare 运行时兜底。

问题（round26 §1 Q4/Q6 实证）：`indices_meta` 表极不全（US=7/HK=63）——「费城」「SO」
（美股 tab）与「恒生港股通高股息低波动指数」（港股 tab）搜不到；`_search_indices` 只查
此表、无运行时兜底（与 symbol 模式 search_etf 的兜底不同）。

修复（round26 Q4/Q6）：
- `_search_indices`：本地表 0 命中时触发 akshare 运行时兜底
  `_search_indices_akshare_fallback`（A/HK/US 三段，含静态扩展段）；
- `sync_indices_meta._STATIC_EXTRA_INDICES`：补 SOX/费城半导体、恒生港股通低波动变体。
"""

import pytest


class TestSearchIndicesRuntimeFallback:
    """Q4/Q6: 本地表空 → akshare 兜底命中。"""

    @pytest.mark.asyncio
    async def test_us_fallback_detects_sox(self, monkeypatch):
        """US tab 搜「费城」：本地表空 → akshare US 段兜底命中 SOX。"""
        from app.routers import market as mkt

        # 本地表空（session 返回 0 行）
        class _Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def execute(self, stmt): return _Result([])
        class _Result:
            def __init__(self, rows): self._rows = rows
            def scalars(self): return self
            def all(self): return self._rows

        monkeypatch.setattr(mkt, "async_session", lambda: _Session())

        # akshare US 列表返回含 SOX
        import pandas as pd
        df = pd.DataFrame([{"symbol": "SOX", "name": "费城半导体指数"}])
        calls = {"n": 0}
        async def _fake_to_thread(fn, *args):
            calls["n"] += 1
            return df() if calls["n"] > 1 else df

        import asyncio
        async def _fake_to_thread2(fn, *args):
            return df

        monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread2)

        out = await mkt._search_indices_akshare_fallback("费城", "US")
        assert any("SOX" in (r.get("symbol") or "") for r in out), (
            "US 指数兜底必须命中 SOX（Q6）"
        )

    @pytest.mark.asyncio
    async def test_hk_fallback_includes_static_low_vol(self, monkeypatch):
        """HK tab 搜「低波动」：静态扩展段（恒生港股通低波动变体）命中。"""
        from app.routers import market as mkt

        out = await mkt._search_indices_akshare_fallback("低波动", "HK")
        # 静态扩展段不依赖网络——必须命中
        assert any("低波动" in (r.get("name") or "") for r in out), (
            "港股低波动变体必须可由静态扩展段命中（Q4）"
        )

    @pytest.mark.asyncio
    async def test_akshare_failure_returns_empty(self, monkeypatch):
        """akshare 全失败 → []（诚实降级，不编造）。"""
        from app.routers import market as mkt

        import asyncio
        def _boom(fn, *args):
            raise RuntimeError("akshare down")
        monkeypatch.setattr(asyncio, "to_thread", _boom)

        out = await mkt._search_indices_akshare_fallback("费城", "US")
        assert out == []

    @pytest.mark.asyncio
    async def test_search_indices_local_hit_no_fallback(self, monkeypatch):
        """本地表命中 → 不触发 akshare 兜底（避免每搜触网）。"""
        from app.routers import market as mkt

        class _Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def execute(self, stmt):
                class _Row:
                    symbol = "000300"
                    name = "沪深300"
                    market = "A"
                return _Result([_Row()])
        class _Result:
            def __init__(self, rows): self._rows = rows
            def scalars(self): return self
            def all(self): return self._rows

        monkeypatch.setattr(mkt, "async_session", lambda: _Session())
        monkeypatch.setattr(mkt, "_search_indices_akshare_fallback",
                            lambda kw, m: (_ for _ in ()).throw(AssertionError("本地命中不应触网")))

        out = await mkt._search_indices("沪深", "A")
        assert out and out[0]["symbol"] == "000300"


class TestStaticIndicesExtended:
    """Q4/Q6: _STATIC_EXTRA_INDICES 补全覆盖（US/HK 索引缺失项）。"""

    def test_us_sox_present(self):
        from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES
        us_syms = {s["symbol"] for s in _STATIC_EXTRA_INDICES if s.get("market") == "US"}
        assert "SOX" in us_syms, "费城半导体指数必须入静态索引（Q6）"
        assert "IXIC" in us_syms
        assert "DJI" in us_syms

    def test_hk_low_vol_variant_present(self):
        from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES
        hk_names = [s["name"] for s in _STATIC_EXTRA_INDICES if s.get("market") == "HK"]
        assert any("低波动" in n for n in hk_names), "恒生港股通低波动变体必须入静态索引（Q4）"
