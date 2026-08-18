# -*- coding: utf-8 -*-
"""F7 R20: symbol_analysis_stream 中文名→代码兜底解析。

前端漏解析时，后端在 get_asset_realtime 返回空且输入含中文时，
用 resolve_symbol_to_code 二次解析再取数。
无网络，全 mock。
"""
from unittest.mock import AsyncMock, patch

import pytest

from fastapi.responses import StreamingResponse

from app.routers import analysis as anmod


@pytest.mark.asyncio
async def test_symbol_analysis_stream_resolves_chinese_name(monkeypatch):
    """中文名输入 + realtime 空 → 后端 resolve_symbol_to_code 兜底解析。"""
    captured = {}

    async def fake_get_asset_realtime(symbol, asset_type):
        captured["called_with"] = (symbol, asset_type)
        # 第一次（中文名）返回空 → 触发兜底；第二次（解析后代码）返回数据
        if symbol == "沪深300ETF":
            return {}
        return {"name": "沪深300ETF", "price": 3.9, "change_pct": 0.5}

    async def fake_resolve(symbol, asset_type="A"):
        return "510300"

    async def fake_get_history(*args, **kwargs):
        return []

    def fake_indicators(hist):
        return {}

    async def fake_stream(prompt, **kwargs):
        yield {"event": "done", "data": {"full_text": "ok", "usage": {}}}

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(anmod, "get_agent", lambda name: agent)
    monkeypatch.setattr(anmod.market_data_hub, "get_asset_realtime", fake_get_asset_realtime)
    monkeypatch.setattr(anmod.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_history", fake_get_history)
    monkeypatch.setattr(anmod, "compute_all_indicators", fake_indicators)
    with patch("app.services.market_service.resolve_symbol_to_code",
               new=AsyncMock(side_effect=fake_resolve)) as mock_resolve:
        resp = await anmod.symbol_analysis_stream(
            anmod.SymbolAnalysisRequest(symbol="沪深300ETF", name="沪深300ETF", asset_type="A", market="A")
        )
        # R49: 兜底解析发生在 body_iterator 消费期间——先消费再断言
        async for _chunk in resp.body_iterator:
            pass
        mock_resolve.assert_awaited_once_with("沪深300ETF", "A")
    # 兜底后第二次取数用解析出的代码
    assert captured["called_with"] == ("510300", "A")


@pytest.mark.asyncio
async def test_symbol_analysis_stream_no_resolve_when_realtime_ok(monkeypatch):
    """realtime 已有数据 → 不触发兜底解析（中文输入也直接过）。"""
    async def fake_get_asset_realtime(symbol, asset_type):
        return {"name": "沪深300ETF", "price": 3.9}

    async def fake_get_history(*args, **kwargs):
        return []

    def fake_indicators(hist):
        return {}

    async def fake_stream(prompt, **kwargs):
        yield "data: ok"

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(anmod, "get_agent", lambda name: agent)
    monkeypatch.setattr(anmod.market_data_hub, "get_asset_realtime", fake_get_asset_realtime)
    monkeypatch.setattr(anmod.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_history", fake_get_history)
    monkeypatch.setattr(anmod, "compute_all_indicators", fake_indicators)
    with patch("app.services.market_service.resolve_symbol_to_code", new=AsyncMock()) as mock_resolve:
        resp = await anmod.symbol_analysis_stream(
            anmod.SymbolAnalysisRequest(symbol="沪深300ETF", name="沪深300ETF", asset_type="A", market="A")
        )
        assert isinstance(resp, StreamingResponse)
        mock_resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_symbol_analysis_stream_code_input_skips_resolve(monkeypatch):
    """纯代码输入（无中文）→ 不触发兜底（避免拉全量列表延迟）。"""
    async def fake_get_asset_realtime(symbol, asset_type):
        return {}

    async def fake_get_history(*args, **kwargs):
        return []

    def fake_indicators(hist):
        return {}

    async def fake_stream(prompt, **kwargs):
        yield "data: ok"

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(anmod, "get_agent", lambda name: agent)
    monkeypatch.setattr(anmod.market_data_hub, "get_asset_realtime", fake_get_asset_realtime)
    monkeypatch.setattr(anmod.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(anmod.market_data_hub, "get_history", fake_get_history)
    monkeypatch.setattr(anmod, "compute_all_indicators", fake_indicators)
    with patch("app.services.market_service.resolve_symbol_to_code", new=AsyncMock()) as mock_resolve:
        resp = await anmod.symbol_analysis_stream(
            anmod.SymbolAnalysisRequest(symbol="510300", name="", asset_type="A", market="A")
        )
        assert isinstance(resp, StreamingResponse)
        mock_resolve.assert_not_awaited()

