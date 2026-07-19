"""Tests for async strategy check (P14-P16)."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_p14_strategy_check_worker_imports():
    """strategy_check_worker module loads without ImportError."""
    from app.tasks.strategy_check_worker import strategy_check_worker, _notify
    assert strategy_check_worker is not None
    assert _notify is not None


def test_p15_strategy_check_model():
    """StrategyCheckRecord model fields match schema."""
    from app.models.strategy_check import StrategyCheckRecord
    record = StrategyCheckRecord(
        capital=500000,
        summary="test summary",
        market_regime="correction",
        suggestions_json="[]",
        holdings_json="[]",
        risk_warnings_json="[]",
    )
    assert record.summary == "test summary"
    assert record.market_regime == "correction"

    d = record.to_dict()
    assert d["type"] == "check"
    assert d["capital"] == 500000
    assert isinstance(d["suggestions"], list)
    assert isinstance(d["holdings_analysis"], list)
    assert isinstance(d["risk_warnings"], list)


@pytest.mark.asyncio
async def test_p16_strategy_check_async_router_imports():
    """Async strategy-check router endpoints compile."""
    # Just verify the module can be imported without errors
    from app.routers import portfolio as portfolio_router
    # Check route paths registered
    routes = [r.path for r in portfolio_router.router.routes]
    # Routes include the router prefix
    assert any("/strategy-check-async" in r for r in routes)
    assert any("/strategy-check-result/" in r for r in routes)
    assert any(r.endswith("/strategy-checks") for r in routes)
    assert any("/strategy-checks/" in r for r in routes)
