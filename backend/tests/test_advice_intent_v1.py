# -*- coding: utf-8 -*-
"""L1 v2 意图分类契约（TDD 先红）.

契约: api-contracts/analysis/advice-valuation.md §2-§3、§10 正反例.
优先级: valuation > product > risk > event > rotation > allocation > general.
classify_all 返回按优先级排好的命中意图（可复合）；classify 取首个.
"""
from app.analysis.intent import classify, classify_all


def test_valuation_queries():
    assert classify("现在有哪些板块是指数比较低估的？") == "valuation"
    assert classify("沪深300现在PE分位多少，贵吗？") == "valuation"
    assert classify("这些低估的是不是价值陷阱？") == "valuation"


def test_composite_valuation_wins_over_product():
    # 低估+ETF映射复合：valuation 主路由（sess-1ef0 实证）
    assert classify("哪些板块低估？买哪只ETF？") == "valuation"
    assert classify_all("哪些板块低估？买哪只ETF？") == ["valuation", "product"]


def test_risk_queries():
    assert classify("止损线设哪") == "risk"
    assert classify("回撤太大怎么办") == "risk"


def test_product_queries():
    assert classify("买哪只银行ETF") == "product"
    assert classify("512800现在能买吗") == "product"


def test_negative_cases():
    assert classify("风险提示有哪些") == "general"  # 固定话术不判 risk
    assert classify("买点到了吗") == "allocation"  # 裸买归 allocation
    assert classify("881001怎么看") == "general"  # 裸板块码不判 product
    assert classify("今天天气不错") == "general"


def test_other_intents():
    assert classify("市场风格是成长还是价值？") == "rotation"
    assert classify("降息对组合有什么影响？") == "event"
    assert classify("当前市场怎么调仓？") == "allocation"
