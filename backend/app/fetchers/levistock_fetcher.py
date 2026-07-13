"""levistock 数据源封装:财联社快讯 + 市场情绪 + 板块热度/风口(免费, CN 稳定)。

所有对外函数均带 TTL 缓存,且底层调用经线程 + 超时包裹,任一源挂起都不会拖垮接口。
"""
import time
import concurrent.futures as cf
from typing import Any

import levistock as lv

_TTL = {"telegraph": 120, "emotion": 60, "sectors": 120, "wind": 120}
_CACHE: dict[str, tuple[float, Any]] = {}
_TIMEOUT = 8


def _safe(fn, timeout: int = _TIMEOUT):
    """在线程中执行 fn,超时/异常均返回 None,绝不挂起。"""
    try:
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(fn).result(timeout=timeout)
    except Exception:
        return None


def _cached(key: str, producer, ttl: int | None = None):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    data = producer()
    _CACHE[key] = (now + (ttl or _TTL.get(key, 120)), data)
    return data


def fetch_cailian_telegraph(limit: int = 30) -> list[dict[str, Any]]:
    """财联社实时电报(快讯)。levistock 已封装财联社签名接口。"""

    def _p() -> list[dict[str, Any]]:
        rows = _safe(lv.news_telegraph_cls, 6) or []
        out = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "time": r.get("time", ""),
                "source": "财联社",
            }
            for r in rows
        ]
        return out[:limit]

    return _cached("telegraph", _p)


def fetch_market_emotion() -> dict[str, Any]:
    """市场情绪:涨跌分布、封板率、连板梯队、赚钱效应等。"""

    def _p() -> dict[str, Any]:
        return _safe(lv.market_emotion_cls, 8) or {}

    return _cached("emotion", _p)


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        rows = _safe(lv.get_sector_heat, 8) or []
        return rows[:limit]

    return _cached("sectors", _p)


def fetch_market_wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        return _safe(lv.market_wind_cls, 8) or []

    return _cached("wind", _p)
