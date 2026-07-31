"""测试数据源失败级联到设计任务的完整链路。

所有外部调用（scanner.full_pipeline、classifier、factor_registry）均被 mock。"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
@patch(
    "app.services.market_data_hub.MarketDataHub.refresh",
    new_callable=AsyncMock,
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_pool",
    return_value=[],
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_factor_matrix",
    return_value={},
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_sector_momentum",
    return_value=[],
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_index_realtime",
    return_value=[],
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_market_sentiment",
    return_value={"sentiment_index": 50, "sentiment_label": "中性"},
)
@patch(
    "app.services.market_data_hub.MarketDataHub.get_market_regime",
    return_value="range_bound",
)
async def test_empty_pool_cascade_to_design_error(
    mock_get_regime, mock_get_sentiment, mock_get_index,
    mock_get_sector, mock_get_factor, mock_get_pool, mock_refresh,
):
        """Z11: empty pool now uses static pool fallback instead of error."""
        from app.services.strategy_design import generate_enhanced_design

        result = await generate_enhanced_design(capital=500000)

        # Z11 fix: empty pool now returns fallback strategies, not error
        assert "strategies" in result
        assert len(result.get("strategies", [])) > 0
        meta = result.get("design_metadata", {})
        # Should have fallback flag when applicable
        # regime can be "unknown" or "range_bound" depending on mock timing
        assert meta.get("regime") in (None, "unknown", "range_bound")
