"""多源资讯聚合:财联社(levistock) + 新浪(直连) + 东方财富 + RSS。

- 每个源独立线程 + 超时包裹,任一源挂起都不会拖垮接口;
- 多源结果去重,统一 TTL 缓存;
- 财联社快讯作为头条主源(免费、实时性最佳);
- 新浪财经 HTTP 直连作为宏观源（~0.3s，替代原 akshare CCTV/百度）。
"""
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import feedparser
import requests
import concurrent.futures
from typing import Any

logger = logging.getLogger(__name__)

from ..utils.proxy import no_proxy
from ..utils.decode import decode_df as _decode_df
from ..services.cache_service import sync_memory_cache
from ..core.ttl import CACHE_TTL
from ..core.async_utils import run_in_thread
from .levistock_fetcher import classify_news_level, fetch_cailian_telegraph

_SRC_TIMEOUT = 5


def _safe(fn, timeout: int = _SRC_TIMEOUT):
    return run_in_thread(fn, timeout=timeout)


_AK_TIMEOUT = 4

# akshare 专用线程池（4 workers），隔离僵尸线程以防堵塞主共享线程池
_akshare_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def get_akshare_pool_stats() -> dict:
    """返回 akshare 专用线程池的实时统计信息。"""
    max_w = _akshare_executor._max_workers
    alive = len(_akshare_executor._threads) if hasattr(_akshare_executor, '_threads') else 0
    pending = _akshare_executor._work_queue.qsize() if hasattr(_akshare_executor, '_work_queue') else -1
    return {
        "max_workers": max_w,
        "alive_threads": alive,
        "pending_tasks": pending,
    }


def _ak(fn, timeout: int = _AK_TIMEOUT) -> list[dict[str, Any]]:
    """调用一个 akshare 新闻函数, 带超时保护, 失败返回空。

    使用专用线程池 _akshare_executor 隔离 akshare 的慢请求，
    避免僵尸线程耗尽主共享线程池 _shared_executor。
    """
    def _p():
        with no_proxy():
            import akshare as ak
            df = fn(ak)
        _decode_df(df)
        return df.to_dict(orient="records")
    future = _akshare_executor.submit(_p)
    try:
        return future.result(timeout=timeout) or []
    except concurrent.futures.TimeoutError:
        return []
    except Exception:
        return []


def _cached(key: str, producer, ttl_key: str = "news_headlines") -> list[dict[str, Any]]:
    """统一缓存包装，使用 sync_memory_cache 替代本地 _CACHE。"""
    ttl = CACHE_TTL.get(ttl_key, 120)
    hit = sync_memory_cache.get(key)
    if hit is not None:
        return hit
    data = producer()
    sync_memory_cache.set(key, data, ttl)
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


def _normalize_title(title: str) -> str:
    """归一化标题用于去重：去空白/常见前缀/标点，忽略大小写。"""
    import re
    t = title.strip()
    # 去除常见前缀
    t = re.sub(r'^(快讯|最新|速报|播报|早报|晚报|盘前|盘中|盘后)[:：\s]*', '', t)
    # 统一空格
    t = re.sub(r'\s+', ' ', t)
    # 去除尾部标点
    t = t.rstrip('，。,。！？…:：;；')
    return t.lower()


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        t = _title_of(it)
        if t:
            norm = _normalize_title(t)
            if norm in seen:
                continue
            seen.add(norm)
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
        result = _dedupe(items)[:30]
        for it in result:
            dedup_key = f"{it.get('time', '')}_{it.get('title', '')}"
            it["id"] = hashlib.md5(dedup_key.encode()).hexdigest()[:12]
        return result

    return _cached("headlines", _p)


def fetch_sina_roll_news(num: int = 15) -> list[dict[str, Any]]:
    """新浪财经滚动新闻（HTTP 直连，~0.3s，P1.3 新增源）。

    使用 requests + no_proxy() 避免代理干扰。
    5s 超时，带 try/except 和 JSON 格式校验。
    """
    try:
        url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num={num}"
        with no_proxy():
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict) or "result" not in data:
            logger.warning("[news] 新浪财经返回格式异常")
            return []
        items: list[dict[str, Any]] = []
        for entry in data["result"].get("data", []):
            title = entry.get("title", "")
            if not title:
                continue
            # 转换 ctime（Unix 秒级时间戳）为 ISO 格式
            ctime = entry.get("ctime", "")
            try:
                ts = int(ctime)
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                time_str = str(ctime)
            items.append({
                "title": title,
                "content": entry.get("content", ""),
                "time": time_str,
                "source": "新浪财经",
            })
        logger.info("[news] 新浪财经返回 %d 条", len(items))
        return _attach_level(items)
    except Exception as e:
        logger.warning("[news] 新浪财经请求失败: %s", e)
        return []


def fetch_macro_news() -> list[dict[str, Any]]:
    """宏观新闻——三级降级链：新浪(直连) → 东方财富宏观 → 财联社兜底。

    P1.4 重写：删除 akshare CCTV/百度（不稳定 + 24s 超时），新浪 HTTP 直连优先。
    改动前 ≤24s → 改动后 ~0.3s（新浪正常时）。
    """
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        # 第一优先级：新浪财经（~0.3s 稳定 HTTP 直连）
        items += fetch_sina_roll_news(15)
        # 第二优先级：东方财富宏观（akshare，降级时出现）
        if not items:
            items += _ak(lambda ak: ak.news_economic_cls())
        # 兜底：财联社快讯（纯文本，0.4s）
        if not items:
            items = fetch_cailian_telegraph(10)
        return _attach_level(_dedupe(items)[:25])

    return _cached("macro", _p, "news_macro")


def fetch_global_news() -> list[dict[str, Any]]:
    """全球新闻——二级降级链：RSS → akshare 全球资讯。

    P1.5 重写：增加独立 try/except + 日志，akshare 超时保持 15s 给降级留缓冲。
    """
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
                    items.append({
                        "title": e.get("title", ""),
                        "source": "RSS",
                        "time": e.get("published", ""),
                    })
        if items:
            logger.info("[news] RSS 全球返回 %d 条", len(items))
        else:
            # 降级：akshare 全球资讯（15s 超时）
            items += _ak(lambda ak: ak.stock_info_global_cls())
            logger.info("[news] akshare 全球资讯返回 %d 条（RSS 降级）", len(items))
        return _attach_level(_dedupe(items)[:25])

    return _cached("global", _p, "news_global")


def fetch_stock_news(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.stock_news_em(symbol=symbol))  # 东方财富个股(主源)
        if not items:
            items += fetch_cailian_telegraph(20)                   # 财联社兜底
        return _attach_level(_dedupe(items)[:25])

    return _cached("stock:" + symbol, _p, "news_stock")


def fetch_research_reports(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        return _ak(lambda ak: ak.stock_research_report_em(symbol=symbol))

    return _cached("research:" + symbol, _p, "news_stock")
