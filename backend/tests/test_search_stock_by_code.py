"""
O4 (docs/archived/round8-rediagnosis.md §7 P4-新): 个股名称/代码搜索修复。

验收:
① search?keyword=茅台 / 00700 / AAPL 均非空（数据源可用时——instruments 表重灌）；
② verify_e2e.py R7-O13 名称搜索从 SKIP 改为 FAIL 门禁（不再豁免 0 条）；
③ instruments 表 US>0（依赖 O1 同步修复 + 数据源可用）。
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestVerifyE2ENoSkip:
    def test_name_search_no_longer_skipped(self):
        """verify_e2e R7-O13 名称搜索不再有 SKIP 豁免（0 条 = FAIL 门禁）。"""
        from pathlib import Path
        e2e = Path(__file__).resolve().parent.parent / "scripts" / "verify_e2e.py"
        with open(e2e, encoding="utf-8") as f:
            src = f.read()
        assert "skip=(_ok_code and _hits == 0)" not in src
        assert "O4 名称搜索门禁" in src


class FakeInstrument:
    def __init__(self, symbol, name, market, asset_type="stock", pinyin="", first_letter=""):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.asset_type = asset_type
        self.pinyin = pinyin
        self.first_letter = first_letter
        self.is_active = True


def _fake_session(rows):
    """构造 async_session 的 fake：execute → scalars().all() → rows。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return cm


class TestSearchHkUsLocalFallback:
    @pytest.mark.asyncio
    async def test_hk_instruments_fallback_when_spot_empty(self, monkeypatch):
        """HK spot 空 → 本地 instruments 表（HK 段）补搜 → 00700 可命中。"""
        import app.services.market_service as ms
        from app.services.market_service import search_hk_us

        rows = [
            FakeInstrument("00700", "腾讯控股", "HK", pinyin="tengxunkonggu", first_letter="tx"),
            FakeInstrument("09988", "阿里巴巴", "HK"),
        ]
        monkeypatch.setattr(ms, "async_session", _fake_session(rows))
        # 两段 spot 都空 → HK/US 均走本地表补搜
        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))

        results = await search_hk_us("00700", include_stocks=True)
        hits = [r for r in results if r["symbol"] == "00700"]
        assert hits, "HK 本地表补搜应命中 00700"
        assert hits[0]["name"] == "腾讯控股"
        assert hits[0]["market"] == "HK"

    @pytest.mark.asyncio
    async def test_hk_name_search_via_local_table(self, monkeypatch):
        """HK 名称（腾讯）经本地 instruments 表命中。"""
        import app.services.market_service as ms
        from app.services.market_service import search_hk_us

        rows = [
            FakeInstrument("00700", "腾讯控股", "HK", pinyin="tengxunkonggu", first_letter="tx"),
        ]
        monkeypatch.setattr(ms, "async_session", _fake_session(rows))
        monkeypatch.setattr(ms, "_call", AsyncMock(return_value=[]))

        results = await search_hk_us("腾讯", include_stocks=True)
        assert any(r["name"] == "腾讯控股" for r in results)
