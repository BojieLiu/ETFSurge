"""测试数据源失败级联到设计任务的完整链路。

所有外部调用（scanner.full_pipeline、classifier、factor_registry）均被 mock。"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
@patch(
    "app.services.pool_manager.PoolManager.refresh",
    new_callable=AsyncMock,
)
@patch(
    "app.services.pool_manager.PoolManager.get_pool",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.get_factor_matrix",
    return_value={},
)
@patch(
    "app.services.pool_manager.PoolManager.get_sector_momentum",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.get_index_realtime",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.get_market_sentiment",
    return_value={"sentiment_index": 50, "sentiment_label": "中性"},
)
@patch(
    "app.services.pool_manager.PoolManager.get_market_regime",
    return_value="range_bound",
)
async def test_empty_pool_cascade_to_design_error(
    mock_get_regime, mock_get_sentiment, mock_get_index,
    mock_get_sector, mock_get_factor, mock_get_pool, mock_refresh,
):
    """验证 pool_manager 刷新后候选池为空 → strategy_design 返回 error。

    这是真实故障（数据源不可用）的单元级再现。"""
    from app.services.strategy_design import generate_enhanced_design

    result = await generate_enhanced_design(capital=500000)

    assert result.get("error") == "无候选标的"
    assert len(result.get("strategies", [])) == 0
    assert "数据管道" in result.get("detail", "")
    assert "market_context" in result
