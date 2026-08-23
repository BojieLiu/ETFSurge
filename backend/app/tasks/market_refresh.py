"""后台定时刷新行情缓存（APScheduler 任务）。

交易时段每 3 秒批量拉取一次关注列表（组合持仓 + 主流指数）的实时行情，
写入 Redis + 内存缓存，并通过 WebSocket 推送给订阅的客户端。
"""

from ..core.logging import get_logger
from ..routers.ws import manager
from ..services.market_data_hub import market_data_hub

logger = get_logger(__name__)


async def refresh_market_cache() -> None:
    try:
        quotes = await market_data_hub.get_portfolio_realtime()
    except Exception:
        logger.exception("刷新行情缓存失败：hub.get_portfolio_realtime 异常")
        return
    if quotes:
        try:
            await manager.broadcast("portfolio", {"type": "realtime", "data": quotes})
        except Exception:
            logger.exception("行情缓存广播失败")
