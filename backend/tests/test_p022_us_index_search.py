# -*- coding: utf-8 -*-
"""P0-22 (round16 3.24): 美股指数搜索——round14 P2-AM 未落地修复。

验收:
① market=US 只返回 US 指数（负向：混入 HK/A 指数 → FAIL）；
② 指数代码（symbol）可搜（SPX 输入命中）；
③ 跨市场 realtime 防护：_lookup_index_market 识别 US/HK 指数。
"""
import pytest
from unittest.mock import patch

from app.routers import market as market_router


class _Idx:
    def __init__(self, symbol, name, market):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.pinyin = ""
        self.first_letter = ""
        self.is_active = True


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


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
