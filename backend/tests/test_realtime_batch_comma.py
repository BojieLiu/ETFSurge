"""
P2-2 (R4-05): /market/realtime/batch 逗号分隔参数解析。

- ?symbols=a,b,c（逗号分隔）→ 全量 split 为 3 个 symbol（旧行为只取 1 条）。
- ?symbols=a&symbols=b&symbols=c（重复参数）→ 3 个 symbol（等价形态）。
- 混合形态 + 空白清洗。

mock 数据源，无网络（HTTP 层解析测试）。
"""

import pytest

from app.routers import market as market_mod


@pytest.mark.asyncio
async def test_comma_separated_symbols_expanded(monkeypatch):
    """P2-2: 逗号分隔全量解析——3 个 symbol 传给 get_realtime。"""
    captured = {}

    async def _fake_get_realtime(symbols, asset_type="A"):
        captured["symbols"] = symbols
        return [{"symbol": s} for s in symbols]

    monkeypatch.setattr(market_mod.market_data_hub, "get_realtime", _fake_get_realtime)
    resp = await market_mod.realtime_batch(symbols=["510300,510880,518880"])
    assert captured["symbols"] == ["510300", "510880", "518880"], \
        f"逗号分隔应全量解析，实际 {captured['symbols']}"
    assert len(resp) == 3


@pytest.mark.asyncio
async def test_repeated_params_equivalent(monkeypatch):
    """P2-2: 重复参数形态不受影响（等价）。"""
    captured = {}

    async def _fake_get_realtime(symbols, asset_type="A"):
        captured["symbols"] = symbols
        return [{"symbol": s} for s in symbols]

    monkeypatch.setattr(market_mod.market_data_hub, "get_realtime", _fake_get_realtime)
    await market_mod.realtime_batch(symbols=["510300", "510880", "518880"])
    assert captured["symbols"] == ["510300", "510880", "518880"]


@pytest.mark.asyncio
async def test_mixed_and_whitespace(monkeypatch):
    """P2-2: 混合形态 + 空白清洗 + 空项过滤。"""
    captured = {}

    async def _fake_get_realtime(symbols, asset_type="A"):
        captured["symbols"] = symbols
        return [{"symbol": s} for s in symbols]

    monkeypatch.setattr(market_mod.market_data_hub, "get_realtime", _fake_get_realtime)
    await market_mod.realtime_batch(symbols=["510300, 510880", "518880", ""])
    assert captured["symbols"] == ["510300", "510880", "518880"]


@pytest.mark.asyncio
async def test_all_empty_returns_empty(monkeypatch):
    """P2-2: 全空输入返回空列表（不调用下游）。"""
    called = {"n": 0}

    async def _fake_get_realtime(symbols, asset_type="A"):
        called["n"] += 1
        return []

    monkeypatch.setattr(market_mod.market_data_hub, "get_realtime", _fake_get_realtime)
    resp = await market_mod.realtime_batch(symbols=["", " , "])
    assert resp == []
    assert called["n"] == 0
