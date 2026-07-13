"""多源资讯聚合:财联社(levistock) + 东方财富 + 新浪 + CCTV/RSS。

- 每个源独立线程 + 超时包裹,任一源挂起都不会拖垮接口;
- 多源结果去重,统一 TTL 缓存;
- 财联社快讯作为头条主源(免费、实时性最佳)。
"""
import time
import concurrent.futures as cf
import feedparser
from typing import Any

from ..utils.proxy import no_proxy
from .akshare_fetcher import _decode_df
from .levistock_fetcher import fetch_cailian_telegraph

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = {"headlines": 120, "macro": 300, "global": 300, "stock": 300}
_SRC_TIMEOUT = 5


def _safe(fn, timeout: int = _SRC_TIMEOUT):
    try:
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(fn).result(timeout=timeout)
    except Exception:
        return None


def _ak(fn) -> list[dict[str, Any]]:
    """调用一个 akshare 新闻函数,失败返回空。"""
    try:
        with no_proxy():
            import akshare as ak

            df = fn(ak)
        _decode_df(df)
        return df.to_dict(orient="records")
    except Exception:
        return []


def _cached(key: str, producer) -> list[dict[str, Any]]:
    now = time.time()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    data = producer()
    _CACHE[key] = (now + _TTL.get(key, 120), data)
    return data


def _title_of(item: dict) -> str:
    for k in ("title", "标题", "name", "名称"):
        v = item.get(k)
        if v:
            return str(v)
    return ""


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        t = _title_of(it)
        if t and t in seen:
            continue
        if t:
            seen.add(t)
        out.append(it)
    return out


def fetch_news_headlines() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        # 仅使用财联社快讯（levistock），0.4s 稳定返回，彻底去掉会卡的 akshare 回退
        return fetch_cailian_telegraph(30)

    return _cached("headlines", _p)


def fetch_macro_news() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.news_cctv())              # CCTV
        items += _ak(lambda ak: ak.news_economic_baidu())    # 百度宏观
        items += _ak(lambda ak: ak.news_economic_cls())      # 东方财富宏观
        if not items:
            items = fetch_news_headlines()
        return _dedupe(items)[:25]

    return _cached("macro", _p)


def fetch_global_news() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        feeds = [
            "https://feeds.content.dowjones.io/public/rss/mw_top_stories",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]
        for f in feeds:
            d = _safe(lambda: feedparser.parse(f), 8)
            if d:
                for e in (d.entries or [])[:8]:
                    items.append(
                        {
                            "title": e.get("title", ""),
                            "source": "RSS",
                            "time": e.get("published", ""),
                        }
                    )
        if not items:
            items += _ak(lambda ak: ak.stock_info_global_cls())
        return _dedupe(items)[:25]

    return _cached("global", _p)


def fetch_stock_news(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.stock_news_em(symbol=symbol))  # 东方财富个股(主源)
        if not items:
            items += fetch_cailian_telegraph(20)                   # 财联社兜底
        return _dedupe(items)[:25]

    return _cached("stock:" + symbol, _p)


def fetch_research_reports(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        return _ak(lambda ak: ak.stock_research_report_em(symbol=symbol))

    return _cached("research:" + symbol, _p)
