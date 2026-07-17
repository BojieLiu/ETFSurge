"""
Text Pipeline Path A: keyword-driven macro/policy/geopolitical factor computation.

Reads news headlines from news_fetcher/levistock and computes factor scores
by matching keywords mapped to policy direction, geopolitical risk, etc.

All scores normalized to [0, 1] range.
"""
from __future__ import annotations

from typing import Any

# ── Keyword → score mapping tables ──────────────────────────────

# 中国政策宽松关键词
_EASING_KEYWORDS = [
    "降准", "降息", "全面降准", "定向降准", "逆回购",
    "MLF", "中期借贷便利", "流动性投放", "稳增长",
    "逆周期", "宽松", "放水", "财政刺激", "减税降费",
    "支持实体经济", "加大信贷", "降低融资成本",
    "呵护", "流动性合理充裕",
]

# 中国政策收紧关键词
_TIGHTENING_KEYWORDS = [
    "加息", "收紧", "去杠杆", "防风险", "降杠杆",
    "压缩", "整顿", "规范", "加强监管",
    "收缩流动性", "提高准备金率", "回笼资金",
]

# 美联储鹰派关键词
_FED_HAWKISH_KEYWORDS = [
    "加息", "大幅加息", "继续加息", "加快加息",
    "缩表", "减少购债", "taper", "tighter",
    "鹰派", "hawkish", "收紧货币政策",
    "通胀风险", "遏制通胀", "对抗通胀",
    "必要时继续加息", "进一步收紧",
]

# 美联储鸽派关键词
_FED_DOVISH_KEYWORDS = [
    "暂停加息", "停止加息", "降息", "鸽派",
    "dovish", "宽松", "接近尾声",
    "加息周期结束", "可能降息", "转向宽松",
    "不需要再加息", "考虑降息",
]

# 地缘风险关键词
_GEOPOLITICAL_KEYWORDS = [
    "战争", "军事行动", "武装冲突", "冲突升级",
    "制裁", "反制裁", "地缘政治", "地缘风险",
    "恐怖袭击", "军事打击", "边境紧张",
    "核试验", "导弹", "入侵", "占领",
    "紧急状态", "动员", "戒严",
]

# 黑天鹅/极端事件关键词
_CRISIS_KEYWORDS = [
    "崩盘", "熔断", "金融危机", "债务违约",
    "破产", "清算", "挤兑", "紧急",
    "系统性风险", "停牌", "退市",
]

# 关键数据超预期关键词
_SURPRISE_KEYWORDS = [
    "超预期", "超市场预期", "大超预期",
    "不及预期", "低于预期",
    "PMI", "CPI", "非农", "GDP",
    "社融", "信贷数据", "进出口",
]


def _score_from_keywords(
    text: str,
    keywords_pos: list[str],
    keywords_neg: list[str] | None = None,
) -> float:
    """Score a single text based on keyword matches.

    Returns value in [0, 1].
    """
    text_lower = text.lower()
    pos_count = sum(1 for kw in keywords_pos if kw.lower() in text_lower)
    if keywords_neg:
        neg_count = sum(1 for kw in keywords_neg if kw.lower() in text_lower)
    else:
        neg_count = 0
    total = pos_count - neg_count
    # Normalize to [0, 1] with sigmoid-like mapping
    return min(1.0, max(0.0, 0.5 + total * 0.15))


def _aggregate(headlines: list[str], keywords: list[str]) -> float:
    """Aggregate keyword scores across multiple headlines.

    Returns average score in [0, 1], or neutral value for empty input.
    """
    if not headlines:
        return 0.5
    scores = []
    for h in headlines:
        pos = sum(1 for kw in keywords if kw.lower() in h.lower())
        if pos > 0:
            scores.append(min(1.0, 0.5 + pos * 0.15))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _aggregate_max(headlines: list[str], keywords: list[str]) -> bool:
    """Return True if any headline triggers a keyword match (for crisis flags)."""
    if not headlines:
        return False
    for h in headlines:
        if any(kw.lower() in h.lower() for kw in keywords):
            return True
    return False


class TextPipeline:
    """文本管道路径A：关键词驱动宏观因子计算。"""

    def compute_policy_score(self, headlines: list[str]) -> float:
        """中国政策宽松度评分 [0, 1]"""
        return _aggregate(headlines, _EASING_KEYWORDS)

    def compute_tightening_score(self, headlines: list[str]) -> float:
        """中国政策收紧度评分 [0, 1]"""
        return _aggregate(headlines, _TIGHTENING_KEYWORDS)

    def compute_fed_hawkish_score(self, headlines: list[str]) -> float:
        """美联储鹰派程度 [0, 1]"""
        return _aggregate(headlines, _FED_HAWKISH_KEYWORDS)

    def compute_fed_dovish_score(self, headlines: list[str]) -> float:
        """美联储鸽派程度 [0, 1]"""
        return _aggregate(headlines, _FED_DOVISH_KEYWORDS)

    def compute_geopolitical_score(self, headlines: list[str]) -> float:
        """地缘风险评分 [0, 1]"""
        return _aggregate(headlines, _GEOPOLITICAL_KEYWORDS)

    def compute_crisis_flag(self, headlines: list[str]) -> bool:
        """黑天鹅标记 True/False"""
        return _aggregate_max(headlines, _CRISIS_KEYWORDS)

    def compute_data_surprise_score(self, headlines: list[str]) -> dict[str, Any]:
        """关键数据超预期评分。

        Returns:
            {"score": float, "matched_keywords": list[str]}
        """
        matched = []
        if not headlines:
            return {"score": 0.5, "matched_keywords": []}
        for h in headlines:
            for kw in _SURPRISE_KEYWORDS:
                if kw in h:
                    matched.append(kw)
        score = min(1.0, len(matched) * 0.2) if matched else 0.5
        return {"score": score, "matched_keywords": list(set(matched))}

    def compute_all(self, headlines: list[str]) -> dict[str, Any]:
        """批量计算所有宏观信号。

        Returns:
            {
                "policy_easing": float,
                "policy_tightening": float,
                "fed_hawkish": float,
                "fed_dovish": float,
                "geopolitical_score": float,
                "crisis_flag": bool,
                "data_surprise": dict,
            }
        """
        return {
            "policy_easing": self.compute_policy_score(headlines),
            "policy_tightening": self.compute_tightening_score(headlines),
            "fed_hawkish": self.compute_fed_hawkish_score(headlines),
            "fed_dovish": self.compute_fed_dovish_score(headlines),
            "geopolitical_score": self.compute_geopolitical_score(headlines),
            "crisis_flag": self.compute_crisis_flag(headlines),
            "data_surprise": self.compute_data_surprise_score(headlines),
        }


# Global singleton
pipeline = TextPipeline()
