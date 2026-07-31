"""TDD tests for issue 5 (per-item news AI impact analysis) and issue 6 (ws broadcast).

LLM and external sources are mocked; no DB/network needed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis import llm as llmmod
from app.routers.ws import ConnectionManager, manager


async def test_analyze_news_impact_structured(monkeypatch):
    payload = {
        "impact_scope": "A股宽基指数",
        "affected_holdings": [
            {"symbol": "159338", "name": "中证A500ETF", "impact_reason": "降准利好宽基"}
        ],
        "summary": "整体利好组合中的宽基ETF",
    }
    mock_agent = MagicMock()
    mock_agent.run_json = AsyncMock(return_value=payload)
    monkeypatch.setattr("app.analysis.llm.get_agent", lambda name: mock_agent)

    result = await llmmod.analyze_news_impact(
        {"title": "央行降准", "content": "全面降准0.5个百分点"},
        [{"symbol": "159338", "name": "中证A500ETF", "asset_type": "A", "target_weight": 0.4}],
    )
    assert result["impact_scope"] == "A股宽基指数"
    assert isinstance(result["affected_holdings"], list)
    assert result["affected_holdings"][0]["symbol"] == "159338"
    assert result["summary"]


async def test_news_impact_endpoint(monkeypatch):
    import app.routers.analysis as anmod
    from app.routers.analysis import NewsImpactRequest, news_impact

    async def fake(news_item, holdings):
        return {"impact_scope": "scope", "affected_holdings": [], "summary": "ok"}

    monkeypatch.setattr(anmod, "analyze_news_impact", fake)
    result = await news_impact(NewsImpactRequest(
        news={"title": "t", "content": "c"}, portfolio=[]))
    assert result["impact_scope"] == "scope"


async def test_manager_broadcast_callable():
    assert callable(manager.broadcast)
    # With no active connections the call must return gracefully.
    await manager.broadcast("news", {"type": "news", "item": {"title": "x"}})

    cm = ConnectionManager()
    assert callable(cm.broadcast)
