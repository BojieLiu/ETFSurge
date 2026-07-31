"""定时刷新板块动量缓存（APScheduler 60s 任务）。

Phase 2 新增：独立于行情刷新的板块数据定时任务。
覆盖行业动量、概念动量、热点板块、板块热度排行。
"""

import logging

logger = logging.getLogger(__name__)


async def refresh_sector_cache() -> None:
    """定时刷新板块动量缓存，60s 周期。

    调用 MarketDataHub.update_sector_cache() 完成全部刷新。
    """
    try:
        from ..services.market_data_hub import market_data_hub
        await market_data_hub.update_sector_cache()
    except Exception as e:
        logger.exception("[sector_refresh] refresh_sector_cache failed: %s", e)
