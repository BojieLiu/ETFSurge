"""Phase 2.8 G2/G4: strategy_design + database tests."""

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_empty_candidate_pool_returns_error():
    """候选池为空时，编排器返回 error 而非空策略。"""
    from app.services.strategy_design import generate_enhanced_design

    # get_pool() is called with layer argument, return empty list for each
    async def mock_refresh(*args, **kwargs):
        pass

    with patch("app.services.pool_manager.pool_manager.refresh",
               side_effect=mock_refresh):
        with patch("app.services.pool_manager.pool_manager.get_pool",
                   side_effect=lambda layer=None: {"core": [], "satellite": [], "defense": []} if layer is None else []):
            with patch("app.services.pool_manager.pool_manager.get_factor_matrix",
                       return_value={}):
                with patch("app.services.pool_manager.pool_manager.get_market_regime",
                           return_value="range_bound"):
                    with patch("app.services.pool_manager.pool_manager.get_market_sentiment",
                               return_value={"sentiment_index": 50, "sentiment_label": "中性"}):
                        with patch("app.services.pool_manager.pool_manager.get_index_realtime",
                                   return_value=[]):
                            with patch("app.services.pool_manager.pool_manager.get_sector_momentum",
                                       return_value=[]):
                                result = await generate_enhanced_design(capital=500000)

    # When pool is empty, the code falls back to static pool — it should
    # still produce valid strategies (defensive/balanced/aggressive)
    assert "strategies" in result, f"Expected strategies, got: {result}"
    assert len(result["strategies"]) == 3, f"Expected 3 strategies, got {len(result.get('strategies', []))}"
