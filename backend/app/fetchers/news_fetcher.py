"""多源资讯聚合:财联社(levistock) + 东方财富 + 新浪 + CCTV/RSS。

- 每个源独立线程 + 超时包裹,任一源挂起都不会拖垮接口;
- 多源结果去重,统一 TTL 缓存;
- 财联社快讯作为头条主源(免费、实时性最佳)。
"""
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import concurrent.futures as cf
import feedparser
from typing import Any

from ..utils.proxy import no_proxy
from .akshare_fetcher import _decode_df
from .levistock_fetcher import classify_news_level, fetch_cailian_telegraph

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


_TIME_FIELDS = ("time", "date", "ctime", "published", "发布时间", "日期", "create_time", "timestamp")


def _parse_time(val: Any) -> datetime | None:
    """尝试将各种日期格式解析为 datetime，失败返回 None。"""
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
        except (OSError, ValueError, OverflowError):
            pass

    s = str(val).strip()
    if not s:
        return None

    # YYYYMMDD  (e.g. "20240424")
    if re.match(r"^\d{8}$", s):
        try:
            return datetime.strptime(s, "%Y%m%d")
        except ValueError:
            pass

    # YYYY-MM-DD HH:MM:SS  (财联社标准格式)
    if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", s):
        try:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            pass

    # YYYY年MM月DD日
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # RFC 2822 (RSS feeds, e.g. "Tue, 14 Jul 2026 10:00:00 GMT")
    try:
        dt = parsedate_to_datetime(s)
        if dt:
            return dt.replace(tzinfo=None)
    except Exception:
        pass

    # 相对时间：刚刚 / X分钟前 / X小时前 / X天前
    now = datetime.now()
    if "刚刚" in s:
        return now
    m = re.match(r"(\d+)\s*分钟前", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.match(r"(\d+)\s*小时前", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"(\d+)\s*天前", s)
    if m:
        return now - timedelta(days=int(m.group(1)))

    return None


def _normalize_time(item: dict) -> None:
    """将不同来源的时间字段统一为 'YYYY-MM-DD HH:MM:SS' 格式的 'time' 键。"""
    raw = None
    for k in _TIME_FIELDS:
        v = item.get(k)
        if v is not None and v != "":
            raw = v
            break
    if raw is None:
        return
    dt = _parse_time(raw)
    if dt:
        item["time"] = dt.strftime("%Y-%m-%d %H:%M:%S")


def _filter_fresh(items: list[dict[str, Any]], max_age_hours: int = 48) -> list[dict[str, Any]]:
    """过滤掉 time 字段超出 max_age_hours 的旧条目。"""
    now = datetime.now()
    out = []
    for it in items:
        t = it.get("time", "")
        if not t:
            out.append(it)
            continue
        try:
            dt = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
            if (now - dt).total_seconds() < max_age_hours * 3600:
                out.append(it)
        except (ValueError, IndexError):
            out.append(it)
    return out


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


def _attach_level(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为条目补充 level/stars 并统一 time 字段格式。"""
    for it in items:
        _normalize_time(it)                        # 统一时间格式
        if "level" not in it:                      # 财联社已经在源头打标
            title = it.get("title", "")
            level = classify_news_level(title)
            it["level"] = level
            it["stars"] = level
    return items


def fetch_news_headlines() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += fetch_cailian_telegraph(15)        # 财联社快讯（主源，0.4s 稳定）
        items += fetch_macro_news()                  # 宏观：CCTV + 百度
        items += fetch_global_news()                 # 全球：RSS + akshare
        items = _filter_fresh(items, max_age_hours=48)  # 剔除旧闻
        items.sort(key=lambda x: x.get("time", ""), reverse=True)  # 最新在前
        return _dedupe(items)[:30]

    return _cached("headlines", _p)


def fetch_macro_news() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.news_cctv())              # CCTV
        items += _ak(lambda ak: ak.news_economic_baidu())    # 百度宏观
        items += _ak(lambda ak: ak.news_economic_cls())      # 东方财富宏观
        if not items:
            items = fetch_cailian_telegraph(10)  # 避免与 fetch_news_headlines 循环依赖
        return _attach_level(_dedupe(items)[:25])

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
        return _attach_level(_dedupe(items)[:25])

    return _cached("global", _p)


def fetch_stock_news(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.stock_news_em(symbol=symbol))  # 东方财富个股(主源)
        if not items:
            items += fetch_cailian_telegraph(20)                   # 财联社兜底
        return _attach_level(_dedupe(items)[:25])

    return _cached("stock:" + symbol, _p)


def fetch_research_reports(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        return _ak(lambda ak: ak.stock_research_report_em(symbol=symbol))

    return _cached("research:" + symbol, _p)
