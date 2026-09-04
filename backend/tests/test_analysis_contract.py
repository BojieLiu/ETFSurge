"""Contract tests for the 8 analysis endpoints (HTTP layer).

Validates that every endpoint matches the API contract in
``api-contracts/analysis/agents.md``: method, path, request shape, and the
keys present in the 200 response. All external dependencies (LLM, market
fetchers, news fetchers) are mocked so the test is hermetic and fast.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app

# Canned responses for each endpoint type
# Must be valid JSON for endpoints using run_json()
CANNED_LLM_TEXT = "测试LLM响应文本"
CANNED_LLM_JSON = '{"action": "继续持有", "rationale": "组合结构合理", "risk_level": "中等", "report": "测试报告", "sector_name": "测试行业", "symbol": "600519", "outlook": "中性"}'


@pytest.fixture
def client():
    """TestClient with LLM + all data fetchers mocked.

    R52 (2026-09-04): 改用 contextlib.ExitStack 逐项挂 patch——原 20 项
    with-item 单链撞 CPython compile 静态嵌套块上限（cannot add more than
    20），且 symbol-analysis stream 取证挂起后新增 6 个外部源 mock。
    """
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.analysis.runtime.llm_complete_with_system",
            new=AsyncMock(return_value=CANNED_LLM_JSON),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_all_realtime",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_indices",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_commodities",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_market_history",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_asset_realtime",
            new=AsyncMock(return_value={"symbol": "600519", "name": "贵州茅台", "price": 1700, "change_pct": 0.5}),
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_news_headlines",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_news_macro",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_sector_industry",
            return_value=[{"sector_code": "BK0001", "sector_name": "银行"}],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_sector_concept",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_sector_stocks",
            return_value=[{"symbol": "600036", "name": "招商银行", "price": 35.0, "change_pct": 1.0}],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_hot_plates",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_sector_heat",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_fund_flow",
            return_value=None,
        ))
        stack.enter_context(patch(
            "app.services.market_data_hub.market_data_hub.get_hist_avg_volume",
            return_value=None,
        ))
        stack.enter_context(patch(
            "app.routers.analysis.get_history",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.services.market_service.get_history",
            new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.fetchers.news_fetcher.fetch_stock_news",
            return_value=[],
        ))
        stack.enter_context(patch(
            "app.fetchers.fundamentals_fetcher.fetch_current_pe_pb",
            return_value=None,
        ))
        stack.enter_context(patch(
            "app.fetchers.sector_fetcher.get_stock_industry_map",
            return_value={},
        ))
        yield TestClient(app)

def test_news_impact(client):
    r = client.post(
        "/api/v1/analysis/news-impact",
        json={
            "news": {"title": "降准", "content": "央行降准"},
            "portfolio": [{"symbol": "510300", "name": "沪深300ETF", "asset_type": "A", "target_weight": 0.2}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "impact_scope" in body and "affected_holdings" in body and "summary" in body
    assert "disclaimer" in body
    assert body["disclaimer"] == "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"


# NOTE: portfolio-design endpoint was removed in refactor.
# Portfolio design is now handled via the async task system
# at POST /api/v1/portfolio/design-async (see test_portfolio_* in verify_e2e).


def test_sector_analysis_stream(client):
    """Sector analysis is available as SSE streaming endpoint."""
    r = client.post(
        "/api/v1/analysis/sector-analysis/stream",
        json={"sector_code": "BK0001", "sector_type": "industry", "sector_name": "银行"},
    )
    # SSE endpoint returns 200 with text/event-stream
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")
    assert "event:" in r.text


def test_symbol_analysis_stream(client):
    """Symbol analysis is available as SSE streaming endpoint."""
    r = client.post(
        "/api/v1/analysis/symbol-analysis/stream",
        json={"symbol": "600519", "name": "贵州茅台", "asset_type": "A"},
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")
    assert "event:" in r.text


# ── P2-9 B1 (round16 3.9, 自 test_p29_contract_bias.py 并入): SymbolAnalysisRequest ──
# 契约字段完备性：B1 入 analysis 域（权威来源 round16 §3.9/P2-9）。
class TestP29ContractFieldCompleteness:
    def test_symbol_analysis_request_parses_market(self):
        """B1: SymbolAnalysisRequest 接受 market 字段（Pydantic 显式声明）。"""
        from app.routers.analysis import SymbolAnalysisRequest

        req = SymbolAnalysisRequest(symbol="00700", name="腾讯控股", asset_type="HK", market="HK")
        assert req.market == "HK", "market 字段应被 Pydantic 解析（旧实现 extra 静默忽略）"


# ===================================================================
# merged from test_round28_fixes.py::TestR60SymbolAnalysisKlineFallback (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR60SymbolAnalysisKlineFallback:
    """round28 §14.1 R60: 指标端点有数据时，分析端点不得「历史K线为空」。
    get_history 全链空 → 从 Hub K 线缓存取任意年龄数据兜底注入 prompt。"""

    @staticmethod
    def _fake_req(symbol="600519", name="贵州茅台"):
        class _FakeReq:
            def __init__(self):
                self.symbol = symbol
                self.name = name
                self.asset_type = "A"
                self.market = "A"
                self.question = ""
        return _FakeReq()

    @staticmethod
    def _make_prompt_capture():
        captured = {}

        def _fake_agent(name):
            class _A:
                async def run_stream(self, prompt, **kwargs):
                    # R49: prompt 捕获发生在 body_iterator 消费期间（async generator）
                    captured["prompt"] = prompt
                    yield {"event": "done", "data": {"full_text": "ok", "usage": {}}}
            return _A()

        return captured, _fake_agent

    @staticmethod
    async def _collect(resp):
        async for chunk in resp.body_iterator:
            pass

    @pytest.mark.asyncio
    async def test_history_empty_falls_back_to_hub_kline_cache(self, monkeypatch):
        """R60 负向: get_history 全链空 + Hub K线缓存有数据 → prompt 含历史K线与技术指标。"""
        from app.routers import analysis as ar

        captured, fake_agent = self._make_prompt_capture()

        async def _fake_realtime(symbol, asset_type):
            return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

        async def _fake_history(symbol, asset_type, period="daily"):
            return []  # 盘后/源冷却：全链空

        rows = [
            {"date": "2026-08-14", "open": 1680.0, "close": 1700.0, "high": 1710.0,
             "low": 1670.0, "volume": 1000},
            {"date": "2026-08-15", "open": 1700.0, "close": 1705.0, "high": 1715.0,
             "low": 1695.0, "volume": 1100},
        ]

        monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
        monkeypatch.setattr(ar, "get_history", _fake_history)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_rows_any", lambda symbol: rows)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_age_seconds", lambda symbol: 86400.0)
        monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
        monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
        monkeypatch.setattr(ar, "compute_all_indicators",
                            lambda hist: {"rsi": 55.2, "ma5": 1701.0} if hist else {})
        monkeypatch.setattr(ar, "get_agent", fake_agent)
        monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", lambda *a, **k: None)

        resp = await ar.symbol_analysis_stream(self._fake_req())
        await self._collect(resp)
        assert "历史K线" in captured["prompt"]
        assert "2026-08-15" in captured["prompt"], "prompt 应含 Hub 缓存 K 线（不得「K线为空」）"
        assert "技术指标" in captured["prompt"] and "rsi" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_hub_cache_empty_still_honest(self, monkeypatch):
        """R60 负向: get_history 与 Hub 缓存均空 → 诚实标注「无」（不伪造 K 线）。"""
        from app.routers import analysis as ar

        captured, fake_agent = self._make_prompt_capture()

        async def _fake_realtime(symbol, asset_type):
            return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

        async def _fake_history(symbol, asset_type, period="daily"):
            return []

        monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
        monkeypatch.setattr(ar, "get_history", _fake_history)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_rows_any", lambda symbol: None)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_age_seconds", lambda symbol: None)
        monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
        monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
        monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {} if not hist else {"rsi": 1.0})
        monkeypatch.setattr(ar, "get_agent", fake_agent)
        monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", lambda *a, **k: None)

        resp = await ar.symbol_analysis_stream(self._fake_req())
        await self._collect(resp)
        assert "历史K线(最近30条)：无" in captured["prompt"], \
            "两源均空时应诚实标注「无」，不得伪造 K 线"
