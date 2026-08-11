"""
Tests for POST /api/v1/portfolio/apply-design (P0).

Verifies:
  - Request body with symbols + weights applies correctly
  - Existing ETFs get updated (action: "updated")
  - New symbols get created (action: "added")
  - Weight is clamped to [0, 0.5]
  - Empty symbols returns empty result
"""

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_db():
    """Create a fully mocked async session with list_etfs returning test records."""
    mock_etf = MagicMock()
    mock_etf.symbol = "510300"
    mock_etf.name = "沪深300ETF"
    mock_etf.target_weight = 0.3
    mock_etf.portfolio_type = "on_exchange"
    mock_etf.is_active = True

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session, [mock_etf]


@pytest.mark.asyncio
async def test_apply_design_updates_existing(mock_db):
    """已有 ETF 更新权重时返回 action: updated."""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,  # first call (inside apply_portfolio_design)
        existing_etfs,  # second call (after commit)
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.4, "portfolio_type": "on_exchange"}],
                       "applied": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.4, "portfolio_type": "on_exchange",
                                    "action": "updated"}],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["510300"],
                        "weights": {"510300": 0.4}},
                db=session,
            )
            assert result["applied"][0]["action"] == "updated"
            assert result["applied"][0]["target_weight"] == 0.4
            assert len(result["symbols"]) == 1


@pytest.mark.asyncio
async def test_apply_design_adds_new(mock_db):
    """新 ETF 自动创建时返回 action: added."""
    session, existing_etfs = mock_db
    merged = existing_etfs[:]
    new_mock = MagicMock()
    new_mock.symbol = "159915"
    new_mock.name = "159915 ETF"
    new_mock.target_weight = 0.2
    new_mock.portfolio_type = "on_exchange"
    new_mock.is_active = True
    merged.append(new_mock)

    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,
        merged,
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [
                           {"symbol": "510300", "name": "沪深300ETF",
                            "target_weight": 0.3, "portfolio_type": "on_exchange"},
                           {"symbol": "159915", "name": "159915 ETF",
                            "target_weight": 0.2, "portfolio_type": "on_exchange"},
                       ],
                       "applied": [
                           {"symbol": "159915", "name": "159915 ETF",
                            "target_weight": 0.2, "portfolio_type": "on_exchange",
                            "action": "added"},
                       ],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["159915", "510300"],
                        "weights": {"159915": 0.2, "510300": 0.3}},
                db=session,
            )
            added = [a for a in result["applied"] if a["action"] == "added"]
            assert len(added) == 1
            assert added[0]["symbol"] == "159915"


@pytest.mark.asyncio
async def test_apply_design_weight_clamped(mock_db):
    """权重超出 [0, 0.5] 范围时被夹紧."""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,
        existing_etfs,
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.5, "portfolio_type": "on_exchange"}],
                       "applied": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.5, "portfolio_type": "on_exchange",
                                    "action": "updated"}],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["510300"],
                        "weights": {"510300": 0.9}},  # 0.9 → clamped to 0.5
                db=session,
            )
            assert result["applied"][0]["target_weight"] == 0.5


@pytest.mark.asyncio
async def test_apply_design_empty_symbols(mock_db):
    """round14 P0-A: 空 symbols 应 400（修复前返回 200 空操作 + 前端假成功，
    前后端断裂根因——旧断言固化了 bug 行为，已更新）。"""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", return_value=existing_etfs):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [],
                       "applied": [],
                       "message": "组合设计中没有指定持仓",
                   })):
            from app.routers.portfolio import apply_design
            with pytest.raises(HTTPException) as exc:
                await apply_design(
                    design={"portfolio_type": "on_exchange",
                            "symbols": [],
                            "weights": {}},
                    db=session,
                )
            assert exc.value.status_code == 400
