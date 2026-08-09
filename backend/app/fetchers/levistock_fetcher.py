"""levistock 数据源封装:财联社快讯 + 市场情绪 + 板块热度/风口(免费, CN 稳定)。

所有对外函数均带 TTL 缓存,且底层调用经线程 + 超时包裹,任一源挂起都不会拖垮接口。
"""
from typing import Any

import levistock as lv

from ..core.logging import get_logger
from ..core.async_utils import safe_call
from ..services.cache_service import cached

logger = get_logger(__name__)
_TIMEOUT = 8


def _safe(fn, timeout: int = _TIMEOUT):
    """在线程中执行 fn,超时/异常均返回 None,绝不挂起（P1-2：统一走 safe_call,long 池）。"""
    return safe_call(fn, timeout=timeout, executor="long")



_LEVEL_KEYWORDS: dict[int, tuple[str, ...]] = {
    5: (  # 重大/紧急 — 市场剧烈变动或突发性事件
        "重大", "紧急", "突发", "urgent", "特急",
        "崩盘", "熔断", "退市", "破产",
        "战争", "军事行动", "恐怖袭击", "台风", "地震", "疫情",
        "暂停交易", "紧急停牌",
        # F3-1 步骤A: 补地缘军事事件词（明确攻击/宣战级）
        "袭击", "空袭", "开战", "宣战", "airstrike", "collapse", "killed", "fatal",
    ),
    4: (  # 利好/重要正面 — 政策宽松、大涨、超预期
        "利好", "上调", "降准", "降息", "positive", "超预期",
        "大涨", "涨停", "创新高", "突破", "新高",
        "大幅增长", "大幅上升", "飙升", "暴涨", "证监会", "央行",
        "获批", "核准", "签署", "投产", "量产", "落地",
        "净买入", "回购", "增持", "加仓",
        "走强", "牛市", "看涨",
        "降费", "减税", "补贴", "扶持", "放宽",
        "经济复苏", "扩张", "加速", "回暖",
        "降息预期", "量化宽松",
        # 正面商业合作
        "协议", "合作",
        # F3-1 步骤A: 地缘军事/制裁事件（组合直接相关才可能升 L5，其余归 L4）
        "冲突", "军事", "干预", "制裁", "战", "核",
        # O7 (round7 §7 P9): 国际重磅宏观事件——利率决议/非农/OPEC
        #（此前国际新闻无关键词命中 → 全 L1 1★，重磅国际事件被降级）
        "利率决议", "非农", "OPEC",
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
        # F3-1 步骤A: 边境/军演/国防（日常军事动态归 L3）
        "边境", "军演", "国防",
        # 英文利空词
        "sanctions", "layoffs", "downgrade",
    ),
    2: (  # 提醒/关注 — 数据发布、市场异动
        "提醒", "关注", "注意", "风险", "watch",
        "通知", "披露", "预告",
        "展望", "提示", "预警",
        "规则", "办法", "意见", "方案", "措施",
        "调整", "变化", "影响", "改革",
        "交易所", "银保监会", "金管局",
        "CPI", "PMI", "GDP", "社融", "信贷",
        "行业", "赛道",
        "反弹", "拉升", "回落",  # 价格异动中性词
        "港股", "美股", "外围市场", "欧股", "日股",
        "审议", "通过", "批复",
        "逆回购", "MLF", "LPR", "SLF", "再贷款",
        "北向资金", "主力资金", "融资", "融券",
        "IPO", "上市", "新股",
        "定增", "配股", "可转债", "发债",
        "分红", "派息", "送转",
        "评级", "目标价",
        "异动", "拉升", "跳水", "冲高", "回落",
        "密集调研", "机构调研", "大宗交易",
        "停牌", "复牌",
        "要约收购", "股权转让", "重组",
        "营收", "净利润",
        "国务院", "发改委", "财政部", "商务部",
        "欧美", "欧央行", "鲍威尔",
        # O7 (round7 §7 P9): 国际宏观数据词（重要但非紧急）——
        # 通胀/失业/原油/海外央行 归 L2 而非 L1
        "美联储", "失业", "通胀", "原油", "欧央行", "日本央行",
        # 重磅降级: 从 L5 移至 L2 (重要信号,非紧急)
        "重磅",
        # 公司采购/投资公告
        "采购",
        # 英文提醒词
        "approves", "launches", "announces", "FDA",
    ),
}


# F3-1 步骤A: 跨级去重（每个词只属于一个 level；供单测断言）
_LEVEL_WORD_OWNERSHIP: dict[str, int] = {
    _word: _lv
    for _lv, _words in _LEVEL_KEYWORDS.items()
    for _word in _words
}


def classify_news_level(title: str, content: str = "") -> int:
    """关键词法将快讯标题/正文归类为 1~5 级重要性。

    5=重大/紧急, 4=利好, 3=利空, 2=提醒/关注, 1=其他。
    以标题中匹配到的最高级别为准。

    F3-1 步骤D: 增加 content 双输入——正文关键词（如「军事行动」）同样计级，
    取标题与正文中的最高命中级别。

    P2-1 (round9 §6.4): 分级校准——命中 L5/L4 关键词但标题含弱化词
    （或将/可能/传闻/考虑/讨论/有望/预期/拟）→ 降一级（L5→L4，L4→L3）。
    旧实现 L5 占 50%（实测 {2:7,3:1,4:1,5:9}、无 L1），「或将」「有望」类
    未实现事件被虚高标注为重大/利好。
    """
    # 弱化词降级（P2-1）：未实现/推测性事件不标重大或利好
    # 弱化词降级（P2-1）：未实现/推测性事件不标重大或利好。
    # 注意：不含「预期」——「业绩超预期」是已实现的利好词（L4 词表），
    # 「预期」单独出现是中性，不能降级已确认的利好。
    _WEAKENERS = ("或将", "可能", "传闻", "考虑", "讨论", "有望", "据悉", "拟")
    t = ((title or "") + " " + (content or "")[:200]).lower()
    for level in (5, 4, 3, 2):
        # O7 (round7 §7 P9): 关键词统一 lower 再匹配——旧代码 t 已 lower 但
        # 词表保留原始大小写（CPI/PMI/OPEC/FDA 等），大写英文词永不命中 →
        # 国际重磅新闻全 L1（「美国5月CPI…」命中不到 "CPI"）。lower 后修复。
        if any((k.lower() if isinstance(k, str) else k) in t for k in _LEVEL_KEYWORDS[level]):
            if level >= 4 and any(w in (title or "") for w in _WEAKENERS):
                # P2-1: 弱化词降级（L5→L4，L4→L3），不越过 3
                return max(level - 1, 3)
            return level
    return 1


def _level_of(row: dict[str, Any], title: str) -> int:
    """双轨打标：本地关键词分类与源 level 交叉校验（F3-1 步骤B）。

    源 level 仅作参考：与本地分类差值 ≥2 时以本地为准（记 WARNING 观察误标漂移）；
    源 level 仅在未命中任何关键词（本地=1）或差值 <2 时采信。
    """
    local = classify_news_level(title)
    for key in ("level", "rank", "importance", "level_num"):
        v = row.get(key)
        if isinstance(v, int) and 1 <= v <= 5:
            src_level = v
        elif isinstance(v, str) and v.isdigit():
            src_level = int(v)
        else:
            continue
        if src_level != local and abs(src_level - local) >= 2:
            logger.warning(
                "[levistock] level 分歧 source=%d local=%d title=%s → 采用本地",
                src_level, local, (title or "")[:30],
            )
            return local
        return src_level
    return local


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
        # P2-1: stars 走独立「新鲜度」维度（news_fetcher._compute_stars），与 level 解耦
        from .news_fetcher import _compute_stars
        return {
            "title": title,
            "content": r.get("content", ""),
            "time": r.get("time", ""),
            "source": "财联社",
            "level": level,
            "stars": _compute_stars(level, r.get("time", "")),
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

    return cached("telegraph", _p, ttl_key="news_telegraph")


def fetch_market_emotion() -> dict[str, Any]:
    """市场情绪:涨跌分布、封板率、连板梯队、赚钱效应等。"""

    def _p() -> dict[str, Any]:
        return _safe(lv.market_emotion_cls, 8) or {}

    return cached("emotion", _p, ttl_key="news_emotion")


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        rows = _safe(lv.get_sector_heat, 8) or []
        return rows[:limit]

    return cached("sectors", _p, ttl_key="sector_heat")


def fetch_market_wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        return _safe(lv.market_wind_cls, 8) or []

    return cached("wind", _p, ttl_key="news_wind")
