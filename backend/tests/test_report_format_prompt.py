# -*- coding: utf-8 -*-
"""F8 R24 / F11 R38: 市场研判报告编号 1-based + AI 顾问 prompt 表格约束。

无网络，纯断言 prompt 文本。
"""
from app.analysis import llm


def test_report_prompt_sections_start_at_1():
    """R24: 报告章节编号从 1. 开始（不能是 0.）。"""
    prompt = llm._build_report_prompt(
        indices=[{"symbol": "000300", "name": "沪深300", "price": 3800.0}],
        commodities=[{"symbol": "GOLD", "name": "黄金", "price": 700.0}],
        market_data=[{"symbol": "510300", "name": "沪深300ETF", "price": 3.8}],
        indicators={},
        news=[],
        macro_news=[],
        market="A",
    )
    assert "## 1. 市场全景速览" in prompt
    assert "## 6. 操作建议" in prompt
    assert "## 0." not in prompt
    # 章节编号 1-6 连续且不重复
    import re
    heads = re.findall(r"^## (\d+)\. ", prompt, flags=re.M)
    assert heads == ["1", "2", "3", "4", "5", "6"], f"章节编号异常: {heads}"


def test_advice_prompt_table_constraint():
    """R38: generate_advice prompt 含表格约束（标准 Markdown 表格 + 层级限制）。"""
    src = llm.generate_advice.__doc__ or ""
    import inspect
    body = inspect.getsource(llm.generate_advice)
    # prompt 是运行时 f-string，直接断言源码中的约束文本
    assert "如无必要不要使用表格" in body or "标准 Markdown 表格" in body
    assert "`| 列 | 列 |`" in body
    assert "三级以内层级" in body
