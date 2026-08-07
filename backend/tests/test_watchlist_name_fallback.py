"""
O9 (docs/round8-rediagnosis.md §7 P9-新): watchlist 新添条目 name 从 instruments 补名。

现象: 自选添加 510050（realtime name 空/未命中）→ name='510050'（代码当名称入库）。
验收③: watchlist 新条目 name 为真实名称（realtime name 空时从 instruments 本地表补）。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


class _Inst:
    def __init__(self, symbol, name, market):
        self.symbol = symbol
        self.name = name
        self.market = market


class _Realtime:
    def get(self, k, d=None):
        return {"price": 3.8, "change_pct": 0.5}.get(k, d)


def _fake_session(inst_rows):
    """async context manager：execute 顺序返回 ①查重 None ②instruments 补名。"""
    session = AsyncMock()
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # 查重
        MagicMock(scalar_one_or_none=MagicMock(return_value=inst_rows[0] if inst_rows else None)),  # 补名
    ]
    session.execute = AsyncMock(side_effect=results)
    session.add = AsyncMock()

    async def _commit():
        pass
    session.commit = AsyncMock(side_effect=_commit)
    session.refresh = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return cm


class TestWatchlistNameFallback:
    @pytest.mark.asyncio
    async def test_name_from_instruments_when_realtime_empty(self, monkeypatch):
        """realtime name 空 + instruments 表命中 → name 补为真实名称。"""
        import app.routers.market as mr

        inst = _Inst("510050", "上证50ETF", "A")
        fake_session = _fake_session([inst])
        monkeypatch.setattr(mr, "async_session", lambda: fake_session)

        async def fake_realtime(symbol, asset_type):
            return None  # realtime 拿不到

        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", fake_realtime)

        data = MagicMock()
        data.symbol = "510050"
        data.asset_type = "A"
        data.name = ""
        data.notes = None

        with patch.object(mr, "CODE_PATTERN") as pat:
            pat.match.return_value = True
            resp = await mr.watchlist_add(data)

        assert resp["name"] == "上证50ETF", f"应补名，实得 {resp['name']}"

    @pytest.mark.asyncio
    async def test_provided_name_wins(self, monkeypatch):
        """前端传入 name 优先（不覆盖合法名称）。"""
        import app.routers.market as mr
        fake_session = _fake_session([])
        monkeypatch.setattr(mr, "async_session", lambda: fake_session)
        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", AsyncMock(return_value=None))

        data = MagicMock()
        data.symbol = "510050"
        data.asset_type = "A"
        data.name = "上证50ETF"
        data.notes = None

        with patch.object(mr, "CODE_PATTERN") as pat:
            pat.match.return_value = True
            resp = await mr.watchlist_add(data)

        assert resp["name"] == "上证50ETF"

    @pytest.mark.asyncio
    async def test_instruments_name_beats_symbol_code(self, monkeypatch):
        """前端把代码当 name 传入（name==symbol）+ instruments 命中 → 补名优先于代码。"""
        import app.routers.market as mr
        inst = _Inst("510050", "上证50ETF", "A")
        fake_session = _fake_session([inst])
        monkeypatch.setattr(mr, "async_session", lambda: fake_session)
        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", AsyncMock(return_value=None))

        data = MagicMock()
        data.symbol = "510050"
        data.asset_type = "A"
        data.name = "510050"  # 前端把代码当 name 传入（name==symbol 视为未解析）
        data.notes = None

        with patch.object(mr, "CODE_PATTERN") as pat:
            pat.match.return_value = True
            resp = await mr.watchlist_add(data)

        assert resp["name"] == "上证50ETF", "instruments 补名应优先于代码占位"

    @pytest.mark.asyncio
    async def test_all_empty_still_422(self, monkeypatch):
        """realtime/instruments/name 全空 → 仍 422（不把代码当名称入库）。"""
        import app.routers.market as mr
        fake_session = _fake_session([])
        monkeypatch.setattr(mr, "async_session", lambda: fake_session)
        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", AsyncMock(return_value=None))

        data = MagicMock()
        data.symbol = "510050"
        data.asset_type = "A"
        data.name = "510050"
        data.notes = None

        with patch.object(mr, "CODE_PATTERN") as pat:
            pat.match.return_value = True
            with pytest.raises(HTTPException) as exc:
                await mr.watchlist_add(data)
            assert exc.value.status_code == 422


