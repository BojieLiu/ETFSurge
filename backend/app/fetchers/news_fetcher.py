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
from datetime import datetime, timedelta, timezone, tzinfo

# F24 (round23 P0-A): 统一资讯时间戳为北京时间（Asia/Shanghai, UTC+8）。
# 东财/新浪等源返回 Unix epoch（UTC 绝对时），旧实现按 UTC 直显 → 比北京时间慢 8h，
# 且与财联社（已为北京字符串）两套时区并存。统一在此转北京，sort_time 保留原始 epoch
# （排序与时区无关，且存储安全）。
_SHA_TZ = timezone(timedelta(hours=8))
from email.utils import parsedate_to_datetime
import feedparser
import requests
import concurrent.futures
from typing import Any

logger = logging.getLogger(__name__)

from ..utils.proxy import no_proxy
from ..utils.decode import decode_df as _decode_df
from ..services.cache_service import cached
from ..core.async_utils import run_in_thread, safe_call
from .levistock_fetcher import classify_news, classify_news_category, classify_news_level, fetch_cailian_telegraph

# HTTP session reuse: avoid SSL handshake overhead on every request
_http_session = requests.Session()
_http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


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
            # F24: epoch 为 UTC 绝对时，转为北京 naive 显示（旧实现按 UTC 直显 → 慢 8h）
            return datetime.fromtimestamp(val, tz=timezone.utc).astimezone(_SHA_TZ).replace(tzinfo=None)
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
    """将不同来源的时间字段统一为 'YYYY-MM-DD HH:MM:SS' 格式的 'time' 键，
    同时添加 'sort_time'（Unix epoch 秒级整数）供前端排序使用。
    """
    raw = None
    for k in _TIME_FIELDS:
        v = item.get(k)
        if v is not None and v != "":
            raw = v
            break
    if raw is None:
        item["sort_time"] = 0
        return
    dt = _parse_time(raw)
    if dt:
        item["time"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        # F24: sort_time 用北京时间语义计算 epoch（与时区无关排序 + 存储一致，
        # 不受运行机本地时区影响）
        item["sort_time"] = int(dt.replace(tzinfo=_SHA_TZ).timestamp())
    else:
        item["sort_time"] = 0


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


def _compute_stars(level: int, time_str: str) -> int:
    """P2-1 (round9 §6.4): stars = 独立「新鲜度」维度，与 level 解耦。

    旧实现 stars=level（纯语义），导致 stars 与 level 完全同分布、无独立信息量
    （实测头条 {2:7,3:1,4:1,5:9} 与 level 一模一样）。新口径按时间新鲜度：
      <1h → 5★、<6h → 4★、<24h → 3★、<72h → 2★、更旧 → 1★
    时间不可解析时回退 level（旧行为，保证字段非空）。
    """
    try:
        from datetime import datetime
        now = datetime.now()
        t = (time_str or "").strip()
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                dt = datetime.strptime(t, fmt)
                break
            except (ValueError, TypeError):
                continue
        if dt is None:
            return max(1, min(int(level or 1), 5))
        hours = (now - dt).total_seconds() / 3600.0
        if hours < 1:
            return 5
        if hours < 6:
            return 4
        if hours < 24:
            return 3
        if hours < 72:
            return 2
        return 1
    except Exception:
        return max(1, min(int(level or 1), 5))


def _attach_level(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为条目补充 level/stars/category 并统一 time 字段格式。"""
    for it in items:
        _normalize_time(it)                        # 统一时间格式
        if "level" not in it:                      # 财联社已经在源头打标
            title = it.get("title", "")
            # F3-1 步骤D: 标题+正文双输入（正文前 200 字）
            cat, level = classify_news(title, it.get("content", ""))
            it["level"] = level
            it["category"] = cat
            it["stars"] = _compute_stars(level, it.get("time", ""))
        else:
            # 财联社源已有 level，更新 stars 加入时间新鲜度；category 亦在源头打标
            it.setdefault("category", classify_news_category(it.get("title", "")))
            it["stars"] = _compute_stars(it.get("level", 1), it.get("time", ""))
        it.setdefault("ai_summary", None)  # Z18: AI 摘要字段，由后台管道 enrich_news_summaries 填充
    return items


def fetch_eastmoney_news() -> list[dict[str, Any]]:
    """东方财富头条（akshare 源，4s 超时，作为财经头条补充源）。

    Z18: 在财联社主源返回不足时，作为第二条财经头条源接入。
    使用 _ak() akshare 线程池 + 超时保护。
    """
    try:
        return _ak(lambda ak: ak.news_eastmoney())
    except Exception:
        return []


def fetch_news_headlines() -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += fetch_cailian_telegraph(15)        # 财联社快讯（主源，0.4s 稳定）
        items += fetch_eastmoney_news()              # 东方财富头条（Z18 新增源，4s 超时）
        # F29 (round23 §2.4 A4): 不再混入 fetch_macro_news()——旧实现使 headlines
        # 与 macro tab 内容重复（实测 macro 3 条全与 headlines 重复）。宏观新闻
        # 归 macro tab 独立呈现（fetch_macro_news 有专门宏观源与过滤）。
        # 统一打标 level/stars（含财联社源的 stars 时间新鲜度刷新）
        items = _attach_level(items)
        items = _filter_fresh(items, max_age_hours=48)  # 剔除旧闻
        # 按 sort_time 降序排列（数值排序，稳定可靠）
        items.sort(key=lambda x: x.get("sort_time", 0), reverse=True)
        result = _dedupe(items)[:30]
        for it in result:
            dedup_key = f"{it.get('sort_time', '')}_{it.get('title', '')}"
            it["id"] = hashlib.md5(dedup_key.encode()).hexdigest()[:12]
        return result

    return cached("headlines", _p, ttl_key="news_headlines")


def fetch_sina_roll_news(num: int = 15) -> list[dict[str, Any]]:
    """新浪财经滚动新闻（HTTP 直连，~0.3s，P1.3 新增源）。

    使用 requests + no_proxy() 避免代理干扰。
    5s 超时，带 try/except 和 JSON 格式校验。
    """
    try:
        url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num={num}"
        with no_proxy():
            resp = _http_session.get(url, timeout=5)
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
                # F24: epoch → 北京时间显示（与 _parse_time 一致）
                time_str = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_SHA_TZ).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                time_str = str(ctime)
            items.append({
                "title": title,
                "content": entry.get("summary", "") or entry.get("intro", "") or entry.get("content", ""),
                "time": time_str,
                "source": "新浪财经",
                "url": entry.get("url", "") or entry.get("wapurl", ""),
            })
        logger.info("[news] 新浪财经返回 %d 条", len(items))
        return _attach_level(items)
    except Exception as e:
        logger.warning("[news] 新浪财经请求失败: %s", e)
        return []


# O7 (round7 §7 P9): 宏观 tab 内容过滤——宏观源（新浪滚动等）混入个股/营销软文。
# 判定规则（按优先级）：
# 1. 命中营销词（开户/红包/限时/抢购/下载APP 等）→ False（软文剔除）
# 2. 命中个股特征（6 位数字代码、公司名+股价/涨停/主力资金/年报 等）→ False
# 3. 命中宏观/政策词（央行/利率/汇率/CPI/非农/OPEC/政策 等）→ True
# 4. 兜底：含「市场/经济/全球/国际/指数」等宏观语境词 → True；否则 False（宁缺毋滥）
_MARKETING_KEYWORDS = (
    "开户", "红包", "限时", "抢购", "下载APP", "送好礼", "免费领取",
    "扫码", "添加微信", "点击链接", "专属优惠", "福利",
)
_STOCK_PATTERNS = (
    "股价", "涨停", "跌停", "主力资金", "半年报", "年报预告", "业绩预告",
    "股东", "高管", "重组", "并购", "回购股份",
)
_MACRO_KEYWORDS = (
    "央行", "利率", "汇率", "逆回购", "MLF", "LPR", "CPI", "PPI", "PMI", "GDP",
    "社融", "信贷", "通胀", "失业", "非农", "OPEC", "原油", "美联储", "欧央行",
    "日本央行", "关税", "政策", "国务院", "发改委", "财政部", "商务部",
    "稳增长", "经济", "市场", "全球", "国际", "指数", "债市", "股市", "宏观",
)
# R15 (round24): 基金营销/ETF日报 类软文——宏观 tab 混入此类非宏观内容（「ETF日报：
# 产业趋势没有变…」）会污染宏观视图。这些短语即便夹带宏观词也不应入宏观 tab。
_MACRO_EXCLUDE = (
    "ETF日报", "基金日报", "基金发售", "基金产品", "公募基金", "私募基金",
    "基金经理", "净值", "募集", "认购", "申购", "赎回", "定投",
)


def _is_macro_relevant(title: str, content: str = "") -> bool:
    """O7: 宏观新闻相关性判定——剔除个股新闻与营销软文。

    P9: 宏观 tab 混入个股/营销内容。宏观源（新浪滚动）是泛财经流，
    需按「宏观语境」过滤：个股/营销 → False，宏观/政策 → True。
    R15: 追加基金营销/ETF日报 排除短语，避免宏观 tab 混非宏观软文。
    """
    text = f"{title or ''} {content or ''}"
    if any(k in text for k in _MARKETING_KEYWORDS):
        return False
    if any(k in text for k in _STOCK_PATTERNS):
        return False
    # R15: 基金营销/ETF日报 软文即便含宏观词也排除
    if any(k in text for k in _MACRO_EXCLUDE):
        return False
    return any(k in text for k in _MACRO_KEYWORDS)


def fetch_macro_news() -> list[dict[str, Any]]:
    """宏观新闻——三级降级链：新浪(直连) → 东方财富宏观 → 财联社兜底。

    P1.4 重写：删除 akshare CCTV/百度（不稳定 + 24s 超时），新浪 HTTP 直连优先。
    改动前 ≤24s → 改动后 ~0.3s（新浪正常时）。
    O7 (round7 §7 P9): 过滤个股/营销内容——宏观 tab 不再混入无关新闻。
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
        # O7: 宏观相关性过滤（剔除个股/营销）
        items = [it for it in items if _is_macro_relevant(it.get("title", ""), it.get("content", ""))]
        return _attach_level(_dedupe(items)[:25])

    return cached("macro", _p, ttl_key="news_macro")


def fetch_global_news() -> list[dict[str, Any]]:
    """全球新闻——二级降级链：RSS → akshare 全球资讯。

    P1.5 重写：增加独立 try/except + 日志，akshare 超时保持 15s 给降级留缓冲。
    F29 (round23 §2.4 A4): 补 id（与 headlines 同款 md5 去重键）——旧实现 id 全缺，
    前端 :key 与去重失效；source 取 feedparser 真实源名（缺省保底 "RSS"）。
    """
    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        feeds = [
            "https://feeds.content.dowjones.io/public/rss/mw_top_stories",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]
        for f in feeds:
            d = safe_call(lambda: feedparser.parse(f), timeout=8)
            if d:
                for e in (d.entries or [])[:8]:
                    _src = getattr(e, "source", None)
                    _src_name = (_src.get("title") if isinstance(_src, dict) else
                                 getattr(_src, "title", None)) or "RSS"
                    items.append({
                        "title": e.get("title", ""),
                        "content": e.get("summary", ""),
                        "source": _src_name,
                        "time": e.get("published", ""),
                        "url": e.get("link", ""),
                    })
        if items:
            logger.info("[news] RSS 全球返回 %d 条", len(items))
        else:
            # 降级：akshare 全球资讯（15s 超时）
            items += _ak(lambda ak: ak.stock_info_global_cls())
            logger.info("[news] akshare 全球资讯返回 %d 条（RSS 降级）", len(items))
        items = _attach_level(_dedupe(items)[:25])
        # F29: 统一补 id（全局新闻无独立 id 字段，用去重键派生，与 headlines 契约一致）
        for it in items:
            dedup_key = f"{it.get('sort_time', '')}_{it.get('title', '')}"
            it["id"] = hashlib.md5(dedup_key.encode()).hexdigest()[:12]
        return items

    return cached("global", _p, ttl_key="news_global")


def fetch_stock_news(symbol: str) -> list[dict[str, Any]]:
    # P2-3 (R4-06): 东方财富 stock_news_em 返回中文键（新闻标题/新闻内容/发布时间/
    # 新闻来源/新闻链接）→ 归一化为英文键（title/content/time/source/url），
    # 与 headlines/macro/global 契约一致（旧实现直接透传 → 前端/客户端读 None）。
    _STOCK_NEWS_KEY_MAP = {
        "新闻标题": "title",
        "新闻内容": "content",
        "发布时间": "time",
        "新闻来源": "source",
        "新闻链接": "url",
    }
    # R5-2-2: 契约键集 == headlines（仅英文键）——中文键（含"关键词/文章来源"等
    # 未映射键）一律删除，不得残留（旧实现只映射 5 个映射键，其余中文键透传）。
    _STOCK_NEWS_ALLOWED_KEYS = {
        "id", "title", "content", "time", "sort_time", "url", "source", "level", "stars",
    }

    def _normalize_stock_news_keys(item: dict) -> dict:
        if not any(k in item for k in _STOCK_NEWS_KEY_MAP):
            return item
        out = dict(item)
        for cn, en in _STOCK_NEWS_KEY_MAP.items():
            if cn in out and en not in out:
                out[en] = out.pop(cn)
        # R5-2-2: 删除全部含中文字符的残留键（关键词/文章来源等）
        out = {
            k: v for k, v in out.items()
            if not any("\u4e00" <= ch <= "\u9fff" for ch in k)
        }
        return out

    def _p() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items += _ak(lambda ak: ak.stock_news_em(symbol=symbol))  # 东方财富个股(主源)
        if not items:
            items += fetch_cailian_telegraph(20)                   # 财联社兜底
        items = [_normalize_stock_news_keys(i) for i in items]
        return _attach_level(_dedupe(items)[:25])

    return cached("stock:" + symbol, _p, ttl_key="news_stock")


def fetch_research_reports(symbol: str) -> list[dict[str, Any]]:
    def _p() -> list[dict[str, Any]]:
        # F29 (round23 §2.4 A4): 旧实现仅走 stock_research_report_em，对 ETF/新代码
        # 常返回空数组（research tab 全空）。加二级降级链：
        # 东财个股研报 → 东财个股新闻（无研报时至少给出相关资讯）→ 空。
        items = _ak(lambda ak: ak.stock_research_report_em(symbol=symbol)) or []
        if items:
            return _attach_level(_dedupe(items)[:25])
        # 降级：该标的无研报 → 返回个股新闻（相关资讯），避免 research tab 静默全空
        items = fetch_stock_news(symbol) or []
        return _attach_level(_dedupe(items)[:25])

    return cached("research:" + symbol, _p, ttl_key="news_stock")
