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
        "app.routers.analysis.get_all_realtime",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.routers.analysis.get_indices",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.routers.analysis.get_commodities",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.routers.analysis.get_history",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.routers.analysis.get_asset_realtime",
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
        "app.routers.analysis.fetch_industry_sectors",
        return_value=[{"sector_code": "BK0001", "sector_name": "银行"}],
    ), patch(
        "app.routers.analysis.fetch_concept_sectors",
        return_value=[],
    ), patch(
        "app.routers.analysis.fetch_sector_stocks",
        return_value=[{"symbol": "600036", "name": "招商银行", "price": 35.0, "change_pct": 1.0}],
    ), patch(
        "app.routers.analysis.fetch_hot_plates",
        return_value=[],
    ), patch(
        "app.routers.analysis.fetch_sector_heat",
        return_value=[],
    # Fundamental fetchers
    ), patch(
        "app.routers.analysis.fetch_fund_flow",
        return_value=None,
    ), patch(
        "app.routers.analysis.fetch_hist_avg_volume",
        return_value=None,
    ):
        yield TestClient(app)


def test_llm_report(client):
    r = client.post("/api/v1/analysis/llm-report", json={"symbols": ["510050"]})
    assert r.status_code == 200
    body = r.json()
    assert "report" in body
    assert "market_data" in body and "indices" in body and "commodities" in body
    assert "disclaimer" in body
    assert body["disclaimer"] == "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"


def test_llm_advice(client):
    r = client.post("/api/v1/analysis/llm-advice", json={"query": "现在该加仓吗"})
    assert r.status_code == 200
    body = r.json()
    assert "advice" in body
    assert "disclaimer" in body
    assert body["disclaimer"] == "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"


def test_llm_news_analysis(client):
    r = client.post("/api/v1/analysis/llm-news-analysis")
    assert r.status_code == 200
    body = r.json()
    assert "analysis" in body and "news_count" in body
    assert "disclaimer" in body
    assert body["disclaimer"] == "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"


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


def test_portfolio_review(client):
    r = client.post(
        "/api/v1/analysis/portfolio-review",
        json={
            "portfolio_type": "平衡型",
            "last_rebalance_date": "2026-04-10",
            "current_portfolio_holdings": [
                {"ticker": "510300.SH", "name": "沪深300ETF", "weight_pct": 25.0}
            ],
            "new_market_snapshot": {
                "macro": {}, "style_factor_zscore": {}, "risk_indicators": {}
            },
            "risk_budget": {"max_single_etf_weight_pct": 30.0},
            "type_thresholds": {"平衡型": {}},
            "meta_context": {"days_since_rebalance": 93},
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Mock returns portfolio_design response, so check for its structure
    assert "plans" in body or "action" in body
    assert "disclaimer" in body
    assert body["disclaimer"] == "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"


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
