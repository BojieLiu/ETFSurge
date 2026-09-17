# -*- coding: utf-8 -*-
"""Advice intent classifier — 关键词两档第一档（L1 v2）.

契约: api-contracts/analysis/advice-valuation.md §2-§3.
零成本 substring 匹配；零命中/平票（理论上无平票，优先级全序）→ general，
由调用方决定是否走小模型第二档。本模块只做第一档。
优先级: valuation > product > risk > event > rotation > allocation > general.
"""

from __future__ import annotations

import re

_PRIORITY = ["valuation", "product", "risk", "event",
             "rotation", "allocation"]

_VALUATION_KWS = ("低估", "高估", "市盈率", "市净率", "分位", "股息",
                  "价值陷阱", "陷阱", "错杀", "便宜",
                  "PE", "pe", "PB", "pb", "ROE", "roe", "贵")

_PRODUCT_PHRASES = ("买哪只", "买什么ETF", "买什么etf", "ETF推荐", "etf推荐",
                    "选哪只", "代码是多少", "成分股映射", "日均成交",
                    "流动性不足")
_CODE_RE = re.compile(r"\d{6}")
_CODE_CTX_KWS = ("ETF", "etf", "买", "换成", "持有", "代码")

_RISK_PRIMARY = ("止损", "止盈", "回撤", "对冲", "避险", "波动率",
                 "杠杆", "爆仓", "跌穿", "平仓", "套保")
_RISK_AUX_NEED = ("怎么办", "如何应对", "怎么控")

_EVENT_KWS = ("政策", "降息", "加息", "关税", "利好", "利空", "监管",
              "新闻", "央行", "美联储", "决议")

_ROTATION_KWS = ("轮动", "风格", "主线", "成长", "价值")

_ALLOCATION_KWS = ("配置", "调仓", "加仓", "减仓", "仓位", "买点", "卖点",
                   "买入", "卖出")
_ALLOCATION_BARE = ("买", "卖")  # 仅 product 未命中时计入（防复合问误伤）


def _has_product(query: str) -> bool:
    if any(p in query for p in _PRODUCT_PHRASES):
        return True
    if _CODE_RE.search(query) and any(c in query for c in _CODE_CTX_KWS):
        return True
    return False


def _has_risk(query: str) -> bool:
    if any(k in query for k in _RISK_PRIMARY):
        return True
    if "风险" in query and any(k in query for k in _RISK_AUX_NEED):
        return True
    if "防御" in query and any(k in query for k in ("加仓", "减仓", "调仓")):
        return True
    if "安全垫" in query:
        return True
    # “风险提示/风险和适用场景”系固定话术，单出不判 risk
    return False


def classify_all(query: str) -> list[str]:
    """返回命中的意图（按优先级排序，可复合）；无命中返回 []。"""
    q = query or ""
    hit: set[str] = set()
    if any(k in q for k in _VALUATION_KWS):
        hit.add("valuation")
    if _has_product(q):
        hit.add("product")
    if _has_risk(q):
        hit.add("risk")
    if any(k in q for k in _EVENT_KWS):
        hit.add("event")
    if any(k in q for k in _ROTATION_KWS):
        hit.add("rotation")
    if any(k in q for k in _ALLOCATION_KWS):
        hit.add("allocation")
    elif "product" not in hit and any(k in q for k in _ALLOCATION_BARE):
        hit.add("allocation")
    return [i for i in _PRIORITY if i in hit]


def classify(query: str) -> str:
    """主意图：命中首个优先级；无命中 → general。"""
    all_hit = classify_all(query)
    return all_hit[0] if all_hit else "general"
