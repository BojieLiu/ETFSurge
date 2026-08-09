# -*- coding: utf-8 -*-
"""round10 P0-A: llm-advice 注入槽位契约——_build_advice_stream_prompt 必须消费
build_full_context 注入的全部槽位（market_regime/market_sentiment/market_data/
hot_plates/sector_heat/news/fund_flow），空槽才显式降级。

验收口径（docs/round10-container-rediagnosis.md §10 P0-A）：三市场投顾返回
不再出现「暂无实时指数数据/暂无板块热力数据/市场状态未知」模板；hot_plates /
sector_heat 有数据时要进 prompt。
"""
import pytest

from app.analysis.llm import _build_advice_stream_prompt


def test_prompt_includes_regime_and_sentiment():
    ctx = {
        "market_regime": "range_bound",
        "market_sentiment": {"sentiment_label": "中性", "sentiment_index": 50},
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
    }
    prompt = _build_advice_stream_prompt("当前A股怎么配置", ctx)
    assert "市场状态: range_bound" in prompt
    assert "市场情绪: 中性 (50/100)" in prompt


def test_prompt_includes_hot_plates():
    """hot_plates 注入后 prompt 含「热点板块」段（P0-A 槽位消费）。"""
    ctx = {
        "market_regime": "bullish",
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "hot_plates": [
            {"name": "人工智能", "change_pct": 6.2, "reason": "资金流入"},
            {"name": "半导体", "change_pct": 4.8},
        ],
    }
    prompt = _build_advice_stream_prompt("今天有哪些热点", ctx)
    assert "热点板块" in prompt
    assert "人工智能" in prompt
    assert "半导体" in prompt
    assert "+6.20%" in prompt


def test_prompt_includes_sector_heat():
    """sector_heat 注入后 prompt 含「板块热力（涨幅榜）」段。"""
    ctx = {
        "market_regime": "volatile",
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "sector_heat": [
            {"name": "CRO/CMO", "change_pct": 10.84},
            {"name": "通信", "change_pct": 3.76},
        ],
    }
    prompt = _build_advice_stream_prompt("板块分析", ctx)
    assert "板块热力" in prompt
    assert "CRO/CMO" in prompt
    assert "10.84%" in prompt


def test_prompt_empty_slots_no_placeholder_text():
    """空槽时不输出「暂无实时指数数据」等占位符——引擎依赖注入数据而非硬编码占位。"""
    ctx = {
        "market_regime": "",
        "market_sentiment": {},
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "hot_plates": [],
        "sector_heat": [],
    }
    prompt = _build_advice_stream_prompt("今天行情如何", ctx)
    assert "暂无实时指数数据" not in prompt
    assert "暂无板块热力" not in prompt
    assert "市场状态未知" not in prompt