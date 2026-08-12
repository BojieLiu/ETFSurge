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
