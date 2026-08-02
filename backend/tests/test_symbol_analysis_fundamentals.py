"""
P1-3 (R4-09): 个股分析基本面注入 + asset_type 归一化。

- asset_type='stock'（非标准值）→ 归一化为 'A'，get_history 不再静默返回 0 条。
- get_history 失败时按 'A' 重试。
- fundamentals（PE/PB）注入 prompt；缺失时明确标注「数据源不可用」，
  不再让 LLM 误报「输入数据未包含 PE、PB 等财务指标」。

mock 数据源与 LLM，无网络。
"""

import pytest

from app.routers import analysis as ar


class _FakeReq:
    def __init__(self, asset_type="A", symbol="600519", name="贵州茅台", question=""):
        self.symbol = symbol
        self.name = name
        self.asset_type = asset_type
        self.market = "A"
        self.question = question


async def _collect(resp):
    if hasattr(resp, "body_iterator"):
        return "".join([chunk async for chunk in resp.body_iterator])
    return ""


def _make_prompt_capture():
    captured = {}

    def _fake_agent(name):
        class _A:
            def run_stream(self, prompt):
                captured["prompt"] = prompt
                return iter([])
        return _A()

    return captured, _fake_agent


@pytest.mark.asyncio
async def test_asset_type_stock_normalized_to_a(monkeypatch):
    """P1-3: asset_type='stock' 归一化为 'A'——get_history 收到 ('600519','A')。"""
    history_calls = []
    realtime = {"symbol": "600519", "name": "贵州茅台", "price": 1700.0, "change_pct": 1.2}

    async def _fake_realtime(symbol, asset_type):
        assert asset_type == "A", f"realtime asset_type 应为 A，实际 {asset_type}"
        return realtime

    async def _fake_history(symbol, asset_type, period="daily"):
        history_calls.append((symbol, asset_type))
        return [{"日期": "2026-08-01", "收盘": 1700.0, "开盘": 1690.0,
                 "最高": 1710.0, "最低": 1680.0, "成交量": 1000, "成交额": 1.7e9}]

    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
    monkeypatch.setattr(ar, "get_history", _fake_history)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {"rsi": 55.0})
    monkeypatch.setattr(ar, "get_agent", _make_prompt_capture()[1])

    # 禁止真实 akshare 拉取
    async def _no_fund(*a, **k):
        return None
    monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", _no_fund)

    await ar.symbol_analysis_stream(_FakeReq(asset_type="stock"))
    assert history_calls and history_calls[0] == ("600519", "A"), \
        f"get_history 应收到归一化 ('600519','A')，实际 {history_calls}"


@pytest.mark.asyncio
async def test_history_retry_with_a_when_asset_type_fails(monkeypatch):
    """P1-3: get_history 失败时按 'A' 重试。"""
    history_calls = []

    async def _fake_realtime(symbol, asset_type):
        return {"symbol": symbol, "price": 1.0}

    async def _fake_history(symbol, asset_type, period="daily"):
        history_calls.append((symbol, asset_type))
        if asset_type == "HK":  # 首次（HK）返回空 → 触发 A 重试
            return []
        return [{"日期": "2026-08-01", "收盘": 1.0, "开盘": 1.0,
                 "最高": 1.0, "最低": 1.0, "成交量": 100, "成交额": 100}]

    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
    monkeypatch.setattr(ar, "get_history", _fake_history)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {} if not hist else {"rsi": 50.0})
    monkeypatch.setattr(ar, "get_agent", _make_prompt_capture()[1])

    async def _no_fund(*a, **k):
        return None
    monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", _no_fund)

    await ar.symbol_analysis_stream(_FakeReq(asset_type="HK"))
    assert ("600519", "A") in history_calls, f"应触发 A 重试，实际 {history_calls}"


@pytest.mark.asyncio
async def test_fundamentals_injected_into_prompt(monkeypatch):
    """P1-3: PE/PB 可用时注入 prompt 基本面段。"""
    captured, fake_agent = _make_prompt_capture()

    async def _fake_realtime(symbol, asset_type):
        return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

    async def _fake_history(symbol, asset_type, period="daily"):
        return [{"日期": "2026-08-01", "收盘": 1700.0, "开盘": 1690.0,
                 "最高": 1710.0, "最低": 1680.0, "成交量": 1000, "成交额": 1.7e9}]

    async def _fake_to_thread(fn, *a, **k):
        return {"pe_ttm": 28.5, "pb": 8.2}

    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
    monkeypatch.setattr(ar, "get_history", _fake_history)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {"rsi": 55.0})
    monkeypatch.setattr(ar, "get_agent", fake_agent)
    monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", _fake_to_thread)

    await ar.symbol_analysis_stream(_FakeReq(asset_type="A"))
    assert "基本面(PE/PB估值)" in captured["prompt"]
    assert "pe_ttm" in captured["prompt"] and "28.5" in captured["prompt"]


@pytest.mark.asyncio
async def test_fundamentals_unavailable_marked(monkeypatch):
    """P1-3: PE/PB 不可用时 prompt 明确标注数据源不可用（不再静默缺失）。"""
    captured, fake_agent = _make_prompt_capture()

    async def _fake_realtime(symbol, asset_type):
        return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

    async def _fake_history(symbol, asset_type, period="daily"):
        return [{"日期": "2026-08-01", "收盘": 1700.0, "开盘": 1690.0,
                 "最高": 1710.0, "最低": 1680.0, "成交量": 1000, "成交额": 1.7e9}]

    async def _fake_to_thread(fn, *a, **k):
        raise RuntimeError("akshare unavailable")

    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
    monkeypatch.setattr(ar, "get_history", _fake_history)
    monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
    monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {"rsi": 55.0})
    monkeypatch.setattr(ar, "get_agent", fake_agent)
    monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", _fake_to_thread)

    await ar.symbol_analysis_stream(_FakeReq(asset_type="A"))
    assert "基本面(PE/PB估值)" in captured["prompt"]
    assert "数据源不可用" in captured["prompt"]
