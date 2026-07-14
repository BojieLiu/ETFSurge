"""后台定时轮询资讯，向 /ws/news 频道推送重要新快讯。

每 ~30s 拉取一次头条，检测 level>=3 的新条目并广播，避免重复推送。
"""
import asyncio

from ..core.logging import get_logger
from ..fetchers.news_fetcher import fetch_news_headlines
from ..routers.ws import manager

logger = get_logger(__name__)

_last_titles: set = set()


def _level_of(item: dict) -> int:
    try:
        return int(item.get("level", 1) or 1)
    except (TypeError, ValueError):
        return 1


async def refresh_news_cache() -> None:
    global _last_titles
    try:
        items = await asyncio.to_thread(fetch_news_headlines)
    except Exception:
        logger.exception("刷新资讯缓存失败：fetch_news_headlines 异常")
        return

    seen: set = set()
    for it in items or []:
        title = it.get("title", "")
        if not title:
            continue
        seen.add(title)
        # 跳过已广播过的条目
        if title in _last_titles:
            continue
            if _level_of(it) >= 3:
                try:
                    await manager.broadcast("news", {"type": "news", "data": it})
                except Exception:
                    logger.exception("资讯广播失败")
    _last_titles = seen
