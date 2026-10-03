# -*- coding: utf-8 -*-
"""Advice intent classifier — 关键词两档第一档（L1 v2）.

契约: api-contracts/analysis/advice-valuation.md §2-§3.
零成本 substring 匹配；零命中/平票（理论上无平票，优先级全序）→ general，
由调用方决定是否走小模型第二档。本模块只做第一档。
优先级: valuation > product > risk > event > rotation > technical > allocation > general.
"""

from __future__ import annotations

import re

# round60 W2: 「估值」是 S4 估值族最大的口语入口，词表里原本只有 低估/高估/市盈率/
# 市净率 —— 用户说「估值低」「这个估值合理吗」全部落 general（实测 4/81 探针）。
# 同批加入口语化的「选哪个 / 买哪个」（原词表只有书面语的「选哪只 / 买哪只」）。
# 大小写变体（买什么ETF / 买什么etf、ETF推荐 / etf推荐）是子串匹配区分大小写的
# 必然结果，非冗余，各自承重（见 tests 的 keyword meta-test）。
#
# round60 W1: 删除了 8 个**结构性死词**——同组内已被更短条目吸收，删除可证明行为不变
# （81 条探针 0 变化）：价值陷阱⊂陷阱、支撑位⊂支撑、压力位⊂压力、阻力位⊂阻力、
# 买点/卖点/买入/卖出⊂裸词 买/卖。保留它们会制造「这个词生效」的错觉（我自己就中过，
# 是靠变异测试才发现「支撑位」从未承重）。防再犯见 test_advice_goldset_l1.py。
_PRIORITY = ["valuation", "product", "risk", "event",
             "rotation", "technical", "allocation"]

_VALUATION_KWS = ("低估", "高估", "市盈率", "市净率", "估值", "分位", "股息",
                  "陷阱", "错杀", "便宜",
                  "PE", "pe", "PB", "pb", "ROE", "roe", "贵")

_PRODUCT_PHRASES = ("买哪只", "买什么ETF", "买什么etf", "ETF推荐", "etf推荐",
                    "选哪只", "选哪个", "买哪个", "代码是多少", "成分股映射",
                    "日均成交", "流动性不足")
_CODE_RE = re.compile(r"\d{6}")
_CODE_CTX_KWS = ("ETF", "etf", "买", "换成", "持有", "代码")

_RISK_PRIMARY = ("止损", "止盈", "回撤", "对冲", "避险", "波动率",
                 "杠杆", "爆仓", "跌穿", "平仓", "套保", "风险")
# round60 W3: 「风险」升为主词后，原「风险+怎么办/如何应对/怎么控」的辅助门不再
# 需要——它只在「风险」尚未命中时才有意义。取而代之的是**显式排除表**：
# 原来「风险提示有哪些」不判 risk 是巧合（该串不含任何 risk 主词，辅助门根本没被
# 询问），若将来有人为别的目的把「风险提示」加进主词表，这个精确性会静默失效。
# 排除表把巧合变成声明（契约 advice-valuation.md §3.1）。
#
# 只收**能从代码证明是模板话术**的两条：general_analyst.md:6 要求每篇答案都写
# 「潜在风险和适用场景」，故「风险和适用场景」是产品自身词汇；「风险提示」见
# advice-valuation.md §3.1 与 tests/test_advice_p0a_slots.py:155。
# 另曾试列 风险揭示/风险警示/风险收益/风险偏好 四条，但**无法用任何证据判断**它们
# 该不该判 risk（例：「风险收益比怎么算」判 risk 其实也说得通），故不放进排除表——
# 排除表的每一条都是一次假阴性，只收可证的一条。
_RISK_EXCLUDE = ("风险提示", "风险和适用场景")

_EVENT_KWS = ("政策", "降息", "加息", "关税", "利好", "利空", "监管",
              "新闻", "央行", "美联储", "决议")

_ROTATION_KWS = ("轮动", "风格", "主线", "成长", "价值")

_TECHNICAL_KWS = ("支撑", "压力", "阻力", "均线", "破位", "前低", "前高",
                  "布林", "BOLL", "缺口", "量能", "抄底", "企稳")
# 回撤族：必须带后缀（位/到），裸「回撤」归 risk（优先级更前）
_TECHNICAL_RETRACE_KWS = ("回撤位", "回撤到", "回踩到", "反弹到")

_ALLOCATION_KWS = ("配置", "调仓", "加仓", "减仓", "仓位")
_ALLOCATION_BARE = ("买", "卖")  # 仅 product 未命中时计入（防复合问误伤）


def _has_product(query: str) -> bool:
    if any(p in query for p in _PRODUCT_PHRASES):
        return True
    if _CODE_RE.search(query) and any(c in query for c in _CODE_CTX_KWS):
        return True
    return False


def _has_risk(query: str) -> bool:
    # round60 W3: 排除表优先于一切。「风险提示」是 general_analyst.md:3 每篇都有的
    # 固定话术，不该把每篇报告都路由成 risk 意图。
    if any(x in query for x in _RISK_EXCLUDE):
        return False
    # 技术面回撤族（带后缀）不判 risk，由 technical 处理——防「回撤到多少支撑」误判 risk
    if any(k in query for k in _TECHNICAL_RETRACE_KWS):
        return False
    if any(k in query for k in _RISK_PRIMARY):
        return True
    if "防御" in query and any(k in query for k in ("加仓", "减仓", "调仓")):
        return True
    if "安全垫" in query:
        return True
    return False


def _has_technical(query: str) -> bool:
    """Technical intent: 主关键词 + 回撤族（必须带后缀，裸回撤归 risk）。"""
    if any(k in query for k in _TECHNICAL_KWS):
        return True
    if any(k in query for k in _TECHNICAL_RETRACE_KWS):
        return True
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
    if _has_technical(q):
        hit.add("technical")
    if any(k in q for k in _ALLOCATION_KWS):
        hit.add("allocation")
    elif "product" not in hit and any(k in q for k in _ALLOCATION_BARE):
        hit.add("allocation")
    return [i for i in _PRIORITY if i in hit]


def classify(query: str) -> str:
    """主意图：命中首个优先级；无命中 → general。"""
    all_hit = classify_all(query)
    return all_hit[0] if all_hit else "general"
