"""
R5-3-3: prompt 数据完整性断言（测试防护体系）。

对 sector_analysis_stream / symbol_analysis_stream 的 prompt 构建——
mock hub 返回非空数据 → 断言关键数据段已注入（板块快照字段、realtime price
出现在 prompt 文本中）；数据为空时断言显式降级文案（"数据源不可用"）而非静默。

mock 数据源与 agent，无网络。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import analysis as ar


class _FakeReq:
    def __init__(self, **kw):
        defaults = {
            "sector_code": "BK1036", "sector_type": "industry", "sector_name": "半导体",
            "symbol": "510300", "name": "沪深300ETF", "asset_type": "A",
            "market": "A", "question": "", "period": "daily",
        }
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


class _FakeStream:
    def __init__(self, captured):
        self.captured = captured

    async def run_stream(self, prompt):
        self.captured["prompt"] = prompt
        yield {"type": "done"}


class _DONE_RESP:
    """sector 用例 fake_sse 返回值（_drain 对普通对象不再消费）。"""


async def _drain(resp):
    """消费 SSE 流，触发 agent.run_stream 执行并捕获 prompt。"""
    if hasattr(resp, "body_iterator"):
        async for _ in resp.body_iterator:
            pass
    elif hasattr(resp, "run_stream"):
        async for _ in resp.run_stream(""):
            pass
    elif isinstance(resp, _DONE_RESP):
        return  # prompt 已在 fake_sse 内捕获
    else:
        async for _ in resp:
            pass


@pytest.mark.asyncio
async def test_sector_prompt_injects_snapshot_fields(monkeypatch):
    """板块行情快照关键字段（点位/涨跌幅/主力净流入/领涨股）注入 prompt。"""
    captured = {}

    def fake_get_sector_stocks(code):
        return [{"stock_code": "688111", "stock_name": "金山办公"}]

    sector_data = {
        "sector_code": "BK1036", "sector_name": "半导体",
        "price": 3500.5, "change_pct": 2.5, "amount": 1.2e11,
        "turnover_rate": 3.4, "main_inflow": 5.6e9,
        "up_count": 45, "down_count": 12,
        "lead_stock_name": "中芯国际", "lead_stock_code": "688981", "lead_stock_chg": 6.8,
    }

    def fake_normalize(code, industry, concept, name=""):
        return code

    async def fake_stream(prompt):
        captured["prompt"] = prompt
        yield {"event": "done", "data": {"full_text": "ok"}}

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(ar, "get_agent", lambda name: agent)
    monkeypatch.setattr(ar.market_data_hub, "get_sector_industry", lambda n=200: [sector_data])
    monkeypatch.setattr(ar.market_data_hub, "get_sector_concept", lambda n=200: [])
    monkeypatch.setattr(ar.market_data_hub, "get_sector_stocks", fake_get_sector_stocks)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "_normalize_sector_code", fake_normalize)

    req = _FakeReq(sector_code="BK1036", sector_type="industry", sector_name="半导体")
    resp = await ar.sector_analysis_stream(req)
    async for _chunk in resp.body_iterator:
        pass

    prompt = captured.get("prompt", "")
    assert prompt, "R5-3-3 板块 prompt 应被捕获"
    assert "板块实时行情" in prompt, "prompt 应含板块实时行情段"
    assert "3500.5" in prompt, "板块指数点位应注入"
    assert "2.5" in prompt, "今日涨跌幅应注入"
    assert "5.6e+09" in prompt or "5600000000" in prompt, f"主力净流入应注入: {prompt[:400]}"
    assert "中芯国际" in prompt, "领涨股应注入"


@pytest.mark.asyncio
async def test_symbol_prompt_injects_realtime_price(monkeypatch):
    """symbol 分析 prompt 注入 realtime price（非空数据）。"""
    captured = {}

    async def fake_realtime(symbol, asset_type):
        return {"symbol": "510300", "name": "沪深300ETF", "price": 3.845, "change_pct": 1.2}

    async def fake_history(*args, **kwargs):
        return [{"date": "2026-07-31", "close": 3.8}]

    def fake_indicators(hist):
        return {}

    agent = _FakeStream(captured)
    monkeypatch.setattr(ar, "get_agent", lambda name: agent)
    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", fake_realtime)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "get_history", fake_history)
    monkeypatch.setattr(ar, "compute_all_indicators", fake_indicators)

    req = _FakeReq(symbol="510300", name="沪深300ETF", asset_type="A", market="A")
    await _drain(await ar.symbol_analysis_stream(req))

    prompt = captured.get("prompt", "")
    assert prompt, "R5-3-3 symbol prompt 应被捕获"
    assert "3.845" in prompt, f"realtime price 应注入 prompt: {prompt[:300]}"
    assert "1.2" in prompt, "涨跌幅应注入"


@pytest.mark.asyncio
async def test_symbol_prompt_explicit_downgrade_when_data_empty(monkeypatch):
    """数据全空 → 显式降级（R21 DATA_UNAVAILABLE error 事件，而非静默空 prompt 调 LLM）。"""
    captured = {"llm_called": False}

    async def fake_realtime(symbol, asset_type):
        return {}

    async def fake_history(*args, **kwargs):
        return []

    def fake_indicators(hist):
        return {}

    async def fake_stream(prompt):
        captured["llm_called"] = True
        captured["prompt"] = prompt
        yield {"type": "done"}

    agent = AsyncMock()
    agent.run_stream = fake_stream
    monkeypatch.setattr(ar, "get_agent", lambda name: agent)
    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", fake_realtime)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "get_history", fake_history)
    monkeypatch.setattr(ar, "compute_all_indicators", fake_indicators)

    req = _FakeReq(symbol="510300", name="沪深300ETF", asset_type="A", market="A")
    resp = await ar.symbol_analysis_stream(req)
    body = "".join([chunk async for chunk in resp.body_iterator])
    # R21: 数据全空 → SSE error 事件（DATA_UNAVAILABLE）显式降级，不调 LLM
    assert "event: error" in body, f"应返回 error 事件显式降级: {body[:200]}"
    assert "DATA_UNAVAILABLE" in body or "数据源" in body
    assert captured["llm_called"] is False, "数据空不得调用 LLM（静默空 prompt）"

