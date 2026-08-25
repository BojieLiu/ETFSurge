"""行情缓存预热（warmup 一次 + 请求驱动 TTL 回源）。

round35 §12.7 决策 B（2026-08-23）：APScheduler 定时推送链路已删除——调度器自
design-check-pipeline-redesign 危机期禁用一个月无人回切，请求驱动（REST TTL 轮询）
被实证接受；恢复只会复活「空闲空转打免费源」的原始问题（封禁风险）。

本模块现仅保留 warmup 预热入口：调 hub.get_portfolio_realtime() 填充行情缓存，
使启动后首个请求直接命中。不再向 WS 广播 ``{type:'realtime'}``——前端消费分支
已同批删除（market.js），portfolio 频道的 portfolio_changed 广播独立存活于
routers/portfolio.py，与本决策无关。
"""

from ..core.logging import get_logger
from ..services.market_data_hub import market_data_hub

logger = get_logger(__name__)


async def refresh_market_cache() -> None:
    """预热组合行情缓存（无 WS 推送；失败由调用方按预热语义处理）。"""
    try:
        await market_data_hub.get_portfolio_realtime()
    except Exception:
        logger.exception("预热行情缓存失败：hub.get_portfolio_realtime 异常")
