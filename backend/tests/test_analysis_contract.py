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

CANNED_JSON = (
    '{"plans": [{"style": "进攻型"}], "impact_scope": "A股宽基", '
    '"affected_holdings": [], "summary": "示例", "action": "HOLD"}'
)


@pytest.fixture
def client():
    """TestClient with LLM + all data fetchers mocked."""
    with patch(
        "app.analysis.runtime.llm_complete_with_system",
        new=AsyncMock(return_value=CANNED_JSON),
    ), patch(
        "app.routers.analysis._fetch_all_market",
        new=AsyncMock(return_value=([], [], [])),
    ), patch(
        "app.routers.analysis._collect_news",
        return_value=[],
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
        "app.routers.analysis.get_asset_realtime",
        new=AsyncMock(return_value={"symbol": "600519", "name": "贵州茅台", "price": 1700, "change_pct": 0.5}),
    ), patch(
        "app.routers.analysis.get_history",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.routers.analysis.fetch_news_headlines",
        return_value=[],
    ), patch(
        "app.routers.analysis.fetch_macro_news",
        return_value=[],
    ):
        yield TestClient(app)


def test_llm_report(client):
    r = client.post("/api/v1/analysis/llm-report", json={"symbols": ["510050"]})
    assert r.status_code == 200
    body = r.json()
    assert "report" in body
    assert "market_data" in body and "indices" in body and "commodities" in body


def test_llm_advice(client):
    r = client.post("/api/v1/analysis/llm-advice?query=现在该加仓吗")
    assert r.status_code == 200
    assert "advice" in r.json()


def test_llm_news_analysis(client):
    r = client.post("/api/v1/analysis/llm-news-analysis")
    assert r.status_code == 200
    body = r.json()
    assert "analysis" in body and "news_count" in body


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


def test_portfolio_design(client):
    r = client.post("/api/v1/analysis/portfolio-design", json={"capital": 500000})
    assert r.status_code == 200
    body = r.json()
    assert "plans" in body
    assert "indices" in body and "commodities" in body


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
    assert "action" in body


def test_sector_analysis(client):
    r = client.post(
        "/api/v1/analysis/sector-analysis",
        json={"sector_code": "BK0001", "sector_type": "industry", "sector_name": "银行"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "report" in body and "sector_name" in body


def test_symbol_analysis(client):
    r = client.post(
        "/api/v1/analysis/symbol-analysis",
        json={"symbol": "600519", "name": "贵州茅台", "asset_type": "A"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "report" in body and "symbol" in body
