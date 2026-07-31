"""后台定时轮询资讯，向 /ws/news 频道推送快讯。

每 ~30s 拉取一次头条，首轮全量推送，后续仅推送新增条目。
采用批次推送（news_batch）替代逐条推送（news），
批次内已按 sort_time 降序排列，前端可直接替换/合并。
"""
from ..core.async_utils import run_sync
from ..core.logging import get_logger
from ..services.market_data_hub import market_data_hub
from ..routers.ws import manager

logger = get_logger(__name__)

_last_titles: set = set()


async def refresh_news_cache() -> None:
    global _last_titles
    try:
        items = await run_sync(market_data_hub.get_news_headlines, timeout=30)
    except Exception:
        logger.exception("刷新资讯缓存失败：get_news_headlines 异常")
        return

    is_first_cycle = not _last_titles
    new_items: list[dict] = []
    seen: set = set()

    for it in items or []:
        title = it.get("title", "")
        if not title:
            continue
        seen.add(title)

        # 首轮全量；后续只推送新条目
        if is_first_cycle or title not in _last_titles:
            new_items.append(it)

    _last_titles = seen

    if not new_items:
        return

    # 批次推送——已按 sort_time 降序排列（fetch_news_headlines 保证）
    try:
        await manager.broadcast("news", {"type": "news_batch", "data": new_items})
        logger.info("资讯广播完成: %d 条（batch）", len(new_items))
    except Exception:
        logger.exception("资讯广播失败（batch）")
