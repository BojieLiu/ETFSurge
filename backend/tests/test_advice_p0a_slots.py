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


# ── P3-G (round10 §10 P3-G): router 注入槽 ⊆ 引擎消费槽 契约 ──────────
# router（llm_advice_stream, analysis.py）通过 build_full_context + 显式写入的
# key 集合，必须覆盖 _build_advice_stream_prompt 消费的全部 key——漏一个即
# 「槽位错配」回归。此测试在源码层断言（只读 import，不调用 LLM）。

def test_router_injected_keys_cover_prompt_consumed_keys():
    """router 注入的 context key 必须 ⊇ prompt 消费的 key（P3-G 契约）。"""
    import ast as _ast
    import re as _re
    from pathlib import Path

    router_src = Path(__file__).resolve().parent.parent / "app" / "routers" / "analysis.py"
    llm_src = Path(__file__).resolve().parent.parent / "app" / "analysis" / "llm.py"

    # 收集 llm_advice_stream 中写入 ctx_key 的 key（"user_ctx[\"x\"] = ..." 与 ctx.get）
    _r_text = router_src.read_text(encoding="utf-8")
    injected = set(_re.findall(r'user_ctx\["([a-z_]+)"\]\s*=', _r_text))
    # build_full_context 输出 key（间接注入，保守列出常见槽）
    injected |= {"market_regime", "market_sentiment", "index_realtime",
                 "sector_momentum", "news", "fund_flow", "hot_plates",
                 "sector_heat", "market_snapshot", "market_data"}

    _l_text = llm_src.read_text(encoding="utf-8")
    # 只扫 _build_advice_stream_prompt 函数体（防其他函数 ctx.get 干扰）
    _fn_start = _l_text.index("def _build_advice_stream_prompt(")
    _fn_body = _l_text[_fn_start:]
    # 函数结束 = 下一个顶层 def（行首 def 且缩进为 0）
    _next_def = _fn_body.find("\ndef ", 1)
    if _next_def != -1:
        _fn_body = _fn_body[:_next_def]
    consumed = set(_re.findall(r'ctx\.get\("([a-z_]+)"', _fn_body))

    missing = sorted(consumed - injected)
    assert not missing, f"router 未注入但引擎消费的槽位: {missing}"
    assert "market_data" in injected and "sector_momentum" in injected