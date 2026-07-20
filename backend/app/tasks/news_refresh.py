"""后台定时轮询资讯，向 /ws/news 频道推送快讯。

每 ~30s 拉取一次头条，广播所有条目（不再按 level 过滤），
首轮全量推送，后续仅推送新增条目，避免重复广播。
"""
import asyncio

from ..core.logging import get_logger
from ..fetchers.news_fetcher import fetch_news_headlines
from ..routers.ws import manager

logger = get_logger(__name__)

_last_titles: set = set()


async def refresh_news_cache() -> None:
    global _last_titles
    try:
        items = await asyncio.to_thread(fetch_news_headlines)
    except Exception:
        logger.exception("刷新资讯缓存失败：fetch_news_headlines 异常")
        return

    broadcast_count = 0
    seen: set = set()
    is_first_cycle = not _last_titles

    for it in items or []:
        title = it.get("title", "")
        if not title:
            continue
        seen.add(title)

        # 首轮全量推送（无论之前是否广播过）
        if is_first_cycle:
            try:
                await manager.broadcast("news", {"type": "news", "data": it})
                broadcast_count += 1
            except Exception:
                logger.exception("资讯广播失败")
            continue

        # 后续轮次仅推送新条目
        if title in _last_titles:
            continue
        try:
            await manager.broadcast("news", {"type": "news", "data": it})
            broadcast_count += 1
        except Exception:
            logger.exception("资讯广播失败")

    _last_titles = seen
    if broadcast_count:
        logger.info("资讯广播完成: %d 条", broadcast_count)
