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

# round23 §10.2 D1: 原 _safe 二次包装（safe_call 的零逻辑透传）已删——调用点直接
# 调 core.async_utils.safe_call(fn, timeout=..., executor="long")。



# F22/F23 (round23 P0-A): 将「level 既表重要性又表分类」拆分为两个正交维度——
# category（极性/类型）+ level（重要性 1-5，单调）。旧实现 level=4 同时是「利好」与
# 「重要」阈值，导致利空(3)永不推送、战争被标红为利好（F22/F23）。
# 词表按 category 组织；分类优先级 major > risk > positive > negative > neutral。
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "major": (  # 重大/紧急 — 市场剧烈变动或突发性事件
        "重大", "紧急", "突发", "urgent", "特急",
        "崩盘", "熔断", "退市", "破产",
        "战争", "军事行动", "恐怖袭击", "台风", "地震", "疫情",
        "暂停交易", "紧急停牌",
        # R72 (round29): 自然灾难类（强震/海啸/洪水/灾难）补词——「哥伦比亚强震已致304人死亡」应判 major=5
        "强震", "海啸", "洪水", "灾难", "灾害", "余震",
        # F3-1 步骤A: 补地缘军事事件词（明确攻击/宣战级）
        "袭击", "空袭", "开战", "宣战", "airstrike", "collapse", "killed", "fatal",
    ),
    "risk": (  # F23: 地缘/军事/制裁（独立类别，不得标利好红）
        # 自 L4(利好) 移出：冲突/军事/干预/制裁/战/核；自 L3(利空) 移出：边境/军演/国防
        "冲突", "军事", "干预", "制裁", "sanctions",
        # 显式多字 token，避免裸 "战"/"核" 误命中 挑战/战略/核查
        "战争", "开战", "宣战", "战事", "交战", "停战",
        "核冲突", "核威胁", "核武", "核威慑", "核弹",
        "边境", "军演", "国防", "地缘", "导弹", "演习", "博弈",
        # R72 (round29): 地缘扣留/扣押类——「俄方：瑞典扣留涉俄货船」应判 risk≥4
        "扣留", "扣押", "截扣", "扣押货船",
        # R90 (round30): 威胁/致命类——「美方威胁升级关税」「致命组合拳」应判 risk≥4
        "威胁", "致命", "恐吓",
    ),
    "positive": (  # 利好/重要正面 — 政策宽松、大涨、超预期
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
        # O7 (round7 §7 P9): 国际重磅宏观事件——利率决议/非农/OPEC
        "利率决议", "非农", "OPEC",
        # R90 (round30): 「广州新房五连涨」等量价走强词——旧未覆盖 → level1 other
        "连涨", "提价", "量价齐升", "景气上行",
        # 英文利好词
        "surge", "partnership", "breakthrough", "soar",
    ),
    "negative": (  # 利空/重要负面 — 政策收紧、大跌、风险暴露
        "利空", "下调", "暴跌", "negative",
        "大跌", "跌停", "创新低", "跌破", "新低",
        # R72 (round29): 市场连跌/收跌/走弱类——「欧洲股市录得去年末以来最长连跌」应判 negative≥3
        "连跌", "收跌", "走弱", "连阴", "普跌", "重挫",
        "减持", "净卖出", "流出", "出逃",
        "下滑", "萎缩", "放缓", "减速",
        "暂停", "终止", "取消", "撤回", "中止",
        "违规", "处罚", "调查", "立案", "警示", "通报批评",
        "亏损", "下降", "熊市", "低迷", "疲软",
        "做空", "抛售", "空头", "撤离",
        "加息", "缩表", "收紧",
        "暴雷", "爆雷", "踩雷", "违约",
        # 英文利空词
        "layoffs", "downgrade",
    ),
    "neutral": (  # 提醒/关注 — 数据发布、市场异动
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
        # O7 (round7 §7 P9): 国际宏观数据词（重要但非紧急）
        "美联储", "失业", "通胀", "原油", "欧央行", "日本央行",
        # 重磅降级: 从 L5 移至 L2 (重要信号,非紧急)
        "重磅",
        # 公司采购/投资公告
        "采购",
        # 英文提醒词
        "approves", "launches", "announces", "FDA",
    ),
}

# category → 重要性 level（F22：level 单调，与前端点推送/筛选对齐）
_CATEGORY_LEVEL: dict[str, int] = {
    "major": 5,
    "risk": 4,
    "positive": 4,
    "negative": 3,
    "neutral": 2,
    "other": 1,
}

# F22: 跨级去重（每个词只属于一个 category；供单测断言）
_CATEGORY_WORD_OWNERSHIP: dict[str, str] = {
    _word: _cat
    for _cat, _words in _CATEGORY_KEYWORDS.items()
    for _word in _words
}

# 弱化词降级（P2-1 round9 §6.4）：未实现/推测性事件不标重大或利好
_WEAKENERS = ("或将", "可能", "传闻", "考虑", "讨论", "有望", "据悉", "拟")

# R16 (round24): 英文标题分类器——全球资讯多为英文 RSS（道琼斯/CNBC），
# 中文词表永远不命中，导致 global 7/8 落入「other」。按优先级 major>risk>
# positive>negative>neutral 命中英文关键词。
_ENGLISH_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "major": ("fed", "fomc", "ecb", "boj", "rate decision", "rate cut", "rate hike",
              "central bank", "stimulus", "bailout", "quantitative easing"),
    "risk": ("war", "conflict", "sanction", "tariff", "recession", "crash", "selloff",
             "plunge", "crisis", "default", "geopolitical", "bankruptcy", "layoffs",
             "hormuz", "strait", "missile", "invasion", "attacked", "struck",
             "warship", "embargo", "blockade", "ceasefire", "deploy",
             # R90 (round30): "Iran attacks US targets" 旧未命中（只有 attacked）→ level2
             "attack", "attacks", "strike", "strikes", "threat", "threaten",
             "escalat", "retaliate", "retaliation"),
    "positive": ("rally", "surge", "gain", "beats", "record high", "recovery", "boom",
                 "upgrade", "soar", "jumps", "rises", "advance"),
    "negative": ("falls", "drop", "loss", "miss", "downgrade", "slump", "decline",
                 "slides", "tumbles", "sinks", "cut jobs",
                 # R98 (round31): 出口/贸易限制类（「curb rare-earth exports」→
                 # 限制即利空，不再 other 掉）
                 "curb", "curbs", "restrict", "restriction"),
    "neutral": ("inflation", "cpi", "ppi", "pmi", "gdp", "jobs", "nonfarm", "earnings",
                "economy", "market", "oil", "crude", "yield", "treasury", "bond",
                "stocks", "shares", "rate", "trade", "growth", "index", "bank",
                "election", "elections", "reform", "charter", "crypto", "currency",
                # R98 (round31): 宏观数据/贸易/财政类英文词——「Japan exports」、
                # 「US budget deficit」不再落入 other（level 1 欠分类，且不被 R90
                # rule 兜底覆盖）
                "export", "exports", "budget", "deficit", "fiscal", "spending",
                "import", "imports", "trade balance"),
}


def _classify_news_english(title: str, content: str = "") -> str:
    """R16 (round24): 英文标题/正文分类器，补中文词表对 global RSS 的覆盖空白。"""
    t = ((title or "") + " " + (content or "")[:200]).lower()
    for c in ("major", "risk", "positive", "negative", "neutral"):
        if any(k in t for k in _ENGLISH_CATEGORY_KEYWORDS[c]):
            return c
    return "other"


def classify_news(title: str, content: str = "") -> tuple[str, int]:
    """F22/F23 (round23 P0-A): 关键词法将快讯归类为 (category, level)。

    - category ∈ {major, risk, positive, negative, neutral, other}（极性/类型）
    - level ∈ 1~5（重要性，单调；前端按 level>=4 推送/筛选）

    分类优先级 major > risk > positive > negative > neutral，命中最高优先级 category。
    命中 level>=4 关键词但标题含弱化词（或将/可能/…）→ 降一级（不低于 3）。

    F3-1 步骤D: content 双输入（正文前 200 字同样计级）。
    O7 (round7 §7 P9): 关键词统一 lower 再匹配（CPI/PMI/OPEC/FDA 等大写英文词）。
    R16 (round24): 中文未命中（英文标题）→ 英文分类器兜底，避免 global 全 other。
    """
    t = ((title or "") + " " + (content or "")[:200]).lower()
    cat = "other"
    for c in ("major", "risk", "positive", "negative", "neutral"):
        # O7: 词表统一 lower 再匹配，避免大写英文词永不命中
        if any((k.lower() if isinstance(k, str) else k) in t for k in _CATEGORY_KEYWORDS[c]):
            cat = c
            break
    # R16: 中文词表未命中（多为英文 RSS 标题）→ 英文分类器兜底
    if cat == "other" and any(ch.isalpha() and ord(ch) < 128 for ch in (title or "")):
        cat = _classify_news_english(title, content)
    level = _CATEGORY_LEVEL[cat]
    if level >= 4 and any(w in (title or "") for w in _WEAKENERS):
        # P2-1: 弱化词降级（5→4，4→3），不越过 3
        level = max(level - 1, 3)
    return (cat, level)


def classify_news_level(title: str, content: str = "") -> int:
    """返回资讯重要性 1-5（category 推导出的 level 维度）。"""
    return classify_news(title, content)[1]


def classify_news_category(title: str, content: str = "") -> str:
    """返回资讯类型 category（major/risk/positive/negative/neutral/other）。"""
    return classify_news(title, content)[0]


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
        # F22: category 维度（极性/类型），与 level（重要性）正交
        category = classify_news_category(title)
        # P2-1: stars 走独立「新鲜度」维度（news_fetcher._compute_stars），与 level 解耦
        from .news_fetcher import _compute_stars
        return {
            "title": title,
            "content": r.get("content", ""),
            "time": r.get("time", ""),
            "source": "财联社",
            "level": level,
            "category": category,
            "stars": _compute_stars(level, r.get("time", "")),
        }

    def _p() -> list[dict[str, Any]]:
        # 第一优先级: important 分类（编辑筛选）+1 level boost
        important_rows = safe_call(lambda: lv.news_telegraph_cls(category="important"), timeout=6, executor="long") or []
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in important_rows:
            item = _make_item(r, level_boost=1)
            if item:
                seen.add(item["title"].strip().lower())
                result.append(item)

        # 第二优先级: all 分类补充（无 boost, 去重）
        if len(result) < limit:
            all_rows = safe_call(lambda: lv.news_telegraph_cls(category="all"), timeout=6, executor="long") or []
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
    """市场情绪:涨跌分布、封板率、连板梯队、赚钱效应等。

    F20 (round23 §2.3): levistock 直传的 `up_ratio` 实为「涨停封板率」（如 65%）
    而非「上涨占比」（真实约 26%）——命名歧义易误导投资者。重命名透明化为
    `limit_up_seal_rate`（保留原 up_ratio 兼容既有消费者）。
    """

    def _p() -> dict[str, Any]:
        data = safe_call(lv.market_emotion_cls, timeout=8, executor="long") or {}
        if data and "up_ratio" in data and "limit_up_seal_rate" not in data:
            data["limit_up_seal_rate"] = data["up_ratio"]
            data["limit_up_seal_rate_note"] = "涨停封板率 = 涨停家数/(涨停家数+开板家数)，非上涨占比"
        return data

    return cached("emotion", _p, ttl_key="news_emotion")


def fetch_sector_heat(limit: int = 20) -> list[dict[str, Any]]:
    """板块热度排行(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        rows = safe_call(lv.get_sector_heat, timeout=8, executor="long") or []
        return rows[:limit]

    return cached("sectors", _p, ttl_key="sector_heat")


def fetch_market_wind() -> list[dict[str, Any]]:
    """今日风口/主线板块(财联社)。"""

    def _p() -> list[dict[str, Any]]:
        return safe_call(lv.market_wind_cls, timeout=8, executor="long") or []

    return cached("wind", _p, ttl_key="news_wind")
