"""levistock 数据源封装:财联社快讯 + 市场情绪 + 板块热度/风口(免费, CN 稳定)。

所有对外函数均带 TTL 缓存,且底层调用经线程 + 超时包裹,任一源挂起都不会拖垮接口。
"""
from typing import Any

import levistock as lv

from ..core.ttl import CACHE_TTL
from ..core.async_utils import run_in_thread
from ..services.cache_service import sync_memory_cache

_TIMEOUT = 8


def _safe(fn, timeout: int = _TIMEOUT):
    """在线程中执行 fn,超时/异常均返回 None,绝不挂起。"""
    return run_in_thread(fn, timeout=timeout)


def _cached(key: str, producer, ttl_key: str = "news_telegraph"):
    """统一缓存包装，使用 sync_memory_cache 替代本地 _CACHE。"""
    ttl = CACHE_TTL.get(ttl_key, 120)
    hit = sync_memory_cache.get(key)
    if hit is not None:
        return hit
    data = producer()
    sync_memory_cache.set(key, data, ttl)
    return data


_LEVEL_KEYWORDS: dict[int, tuple[str, ...]] = {
    5: (  # 重大/紧急 — 市场剧烈变动或突发性事件
        "重大", "紧急", "突发", "urgent", "特急",
        "崩盘", "熔断", "停牌", "退市", "破产", "违约",
        "制裁", "战争", "军事行动", "恐怖袭击", "台风", "地震", "疫情",
        "暂停交易", "紧急停牌",
        # 英文紧急/灾难词
        "airstrike", "collapse", "killed", "fatal",
    ),
    4: (  # 利好/重要正面 — 政策宽松、大涨、超预期
        "利好", "上调", "降准", "降息", "positive", "超预期",
        "大涨", "涨停", "创新高", "突破", "新高",
        "大幅增长", "大幅上升", "飙升", "暴涨", "证监会", "央行", "国务院", "发改委", "财政部", "商务部",
        "获批", "核准", "签署", "投产", "量产", "落地",
        "净买入", "回购", "增持", "加仓",
        "走强", "牛市", "看涨",
        "降费", "减税", "补贴", "扶持", "放宽",
        "经济复苏", "扩张", "加速", "回暖",
        "降息预期", "量化宽松",
        # 正面商业合作
        "协议", "合作",
        # 英文利好词
        "surge", "partnership", "breakthrough", "soar",
    ),
    3: (  # 利空/重要负面 — 政策收紧、大跌、风险暴露
        "利空", "下调", "暴跌", "negative",
        "大跌", "跌停", "创新低", "跌破", "新低",
        "减持", "净卖出", "流出", "出逃",
        "下滑", "萎缩", "放缓", "减速",
        "暂停", "终止", "取消", "撤回", "中止",
        "违规", "处罚", "调查", "立案", "警示", "通报批评",
        "亏损", "下降", "熊市", "低迷", "疲软",
        "做空", "抛售", "空头", "撤离",
        "加息", "缩表", "收紧",
        "暴雷", "爆雷", "踩雷", "违约",
        # 英文利空词
        "sanctions", "layoffs", "downgrade",
    ),
    2: (  # 提醒/关注 — 数据发布、市场异动 (重大政策信号移至 level 3/4)
        "提醒", "关注", "注意", "风险", "watch",
        "公告", "发布", "通知", "公布", "披露", "预告",
        "展望", "提示", "预警", "提醒",
        "政策", "规则", "办法", "意见", "方案", "措施",
        "调整", "变化", "影响", "改革",
        "交易所", "银保监会", "金管局",
        "数据", "CPI", "PMI", "GDP", "社融", "信贷",
        "指数", "板块", "行业", "赛道",
        "反弹", "拉升", "回落",  # 价格异动中性词（从利好/利空移至提醒）
        "港股", "美股", "外围市场", "欧股", "日股",
        "审议", "通过", "批复",
        "逆回购", "MLF", "LPR", "SLF", "再贷款",
        "北向资金", "主力资金", "融资", "融券",
        "IPO", "上市", "新股",
        "定增", "配股", "可转债", "发债",
        "分红", "派息", "送转",
        "评级", "展望", "目标价",
        "异动", "拉升", "跳水", "冲高", "回落",
        "密集调研", "机构调研", "大宗交易",
        "停牌", "复牌",
        "要约收购", "股权转让", "重组",
        "业绩", "营收", "净利润", "财报",
        "国务院", "发改委", "财政部", "商务部",
        "欧美", "美联储", "欧央行", "鲍威尔",
        # 重磅降级: 从 L5 移至 L2 (重要信号,非紧急)
        "重磅",
        # 公司采购/投资公告
        "采购",
        # 英文提醒词
        "approves", "launches", "announces", "data", "FDA",
    ),
}


def classify_news_level(title: str) -> int:
    """关键词法将快讯标题归类为 1~5 级重要性。

    5=重大/紧急, 4=利好, 3=利空, 2=提醒/关注, 1=其他。
    以标题中匹配到的最高级别为准。
    """
    t = (title or "").lower()
    for level in (5, 4, 3, 2):
        if any(k in t for k in _LEVEL_KEYWORDS[level]):
            return level
    return 1


def _level_of(row: dict[str, Any], title: str) -> int:
    """优先使用数据源自带的 level/rank/importance 字段，否则关键词归类。"""
    for key in ("level", "rank", "importance", "level_num"):
        v = row.get(key)
        if isinstance(v, int) and 1 <= v <= 5:
            return v
        if isinstance(v, str) and v.isdigit():
            iv = int(v)
            if 1 <= iv <= 5:
                return iv
    return classify_news_level(title)


def fetch_cailian_telegraph(limit: int = 30) -> list[dict[str, Any]]:
    """财联社实时电报(快讯)。levistock 已封装财联社签名接口。

    每条快讯附加 level(1~5) 与 stars(=level) 重要性标识。
    优先取 category='important'（编辑筛选重要快讯，+1 level boost），
    不足时从 category='all' 补充并去重。
    """

    def _make_item(r: dict[str, Any], level_boost: int = 0) -> dict[str, Any] | None:
        title = r.get("title", "")
        if not title:
            return None
        level = _level_of(r, title)
        if level_boost:
            level = min(level + level_boost, 5)
        return {
            "title": title,
            "content": r.get("content", ""),
            "time": r.get("time", ""),
            "source": "财联社",
            "level": level,
            "stars": level,
        }

    def _p() -> list[dict[str, Any]]:
        # 第一优先级: important 分类（编辑筛选）+1 level boost
        important_rows = _safe(lambda: lv.news_telegraph_cls(category="important"), 6) or []
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in important_rows:
            item = _make_item(r, level_boost=1)
            if item:
                seen.add(item["title"].strip().lower())
                result.append(item)

        # 第二优先级: all 分类补充（无 boost, 去重）
        if len(result) < limit:
            all_rows = _safe(lambda: lv.news_telegraph_cls(category="all"), 6) or []
            for r in all_rows:
                if len(result) >= limit:
                    break
                item = _make_item(r, level_boost=0)
                if item and item["title"].strip().lower() not in seen:
                    seen.add(item["title"].strip().lower())
                    result.append(item)

        return result[:limit]

    return _cached("telegraph", _p, "news_telegraph")


def fetch_market_emotion() -> dict[str, Any]:
    """市场情绪:涨跌分布、封板率、连板梯队、赚钱效应等。"""

    def _p() -> dict[str, Any]:
        return _safe(lv.market_emotion_cls, 8) or {}

    return _cached("emotion", _p, "news_emotion")


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        rows = _safe(lv.get_sector_heat, 8) or []
        return rows[:limit]

    return _cached("sectors", _p, "sector_heat")


def fetch_market_wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        return _safe(lv.market_wind_cls, 8) or []

    return _cached("wind", _p, "news_wind")
