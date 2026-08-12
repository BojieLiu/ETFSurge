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

    Patches only functions that actually exist in the current router module.
    Removed deprecated patches (_fetch_all_market, _collect_news) and
    functions that moved to other modules (list_etfs → portfolio_service,
    build_price_map → portfolio_service).
    """
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(return_value=CANNED_LLM_JSON),
    # Market data functions imported into router from market_service
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_all_realtime",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_indices",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_commodities",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_market_history",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_asset_realtime",
        new=AsyncMock(return_value={"symbol": "600519", "name": "贵州茅台", "price": 1700, "change_pct": 0.5}),
    # News fetchers
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_news_headlines",
        return_value=[],
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_news_macro",
        return_value=[],
    # Sector fetchers
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_sector_industry",
        return_value=[{"sector_code": "BK0001", "sector_name": "银行"}],
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_sector_concept",
        return_value=[],
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_sector_stocks",
        return_value=[{"symbol": "600036", "name": "招商银行", "price": 35.0, "change_pct": 1.0}],
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_hot_plates",
        return_value=[],
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_sector_heat",
        return_value=[],
    # Fundamental fetchers
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_fund_flow",
        return_value=None,
    ), patch(
        "app.services.market_data_hub.market_data_hub.get_hist_avg_volume",
        return_value=None,
    ):
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
