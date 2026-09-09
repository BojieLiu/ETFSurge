"""Prompt 标注/结构（聚合文件）——P1-4 小测试合并（round53 实施批，docs/redundant-review.md §4.2 T2）。

原文件 docstring 见下方来源注释；用例名/类名全部不变。
"""
from app.analysis import llm
from app.routers import analysis as analysis_router
from app.services.market_data_hub import _parse_concept_tags
import inspect
import pytest
import re


# 来源: tests/test_sector_prompt_annotation.py（O26）—— P1-4 小测试合并（用例名不变）
# O26 (docs/archived/round8-rediagnosis.md §7 §5.1H): 板块技术分析点位口径标注。
# 
# 现象: 板块分析报告报"指数报收 50118.43 点"，但全文无「板块指数点位」显式标签——
# 专业读者易误读为成分股或沪深大盘。验收: 报告 prompt 首段含「板块指数（BKxxxx）
# 点位」表述；技术面注明均线周期。


# 来源: tests/test_report_format_prompt.py（F8 R24 / F11 R38）—— P1-4 小测试合并（用例名不变）
# 无网络，纯断言 prompt 文本。


# 来源: tests/test_concept_tags_flat.py（O9）—— P1-4 小测试合并（用例名不变）
# O9 (docs/archived/round8-rediagnosis.md §7 P9-新): stock-hot-rank.concept_tags 平铺填充。
# 
# 现象: contract F2-6 声明 concept_tags 字段，实际 50/50 全空——数据源 tag 是嵌套
# dict {"concept_tag": [...], "popularity_tag": "..."}，_parse_concept_tags 对 dict
# 输入直接返回 []。
# 
# 修复（已拍板：后端平铺填充，不改契约字段）: 识别嵌套 dict/list 的 concept_tag
# 键并平铺为字符串数组。


import inspect
import pytest

from app.routers import analysis as analysis_router


class TestSectorPromptAnnotation:
    def test_sector_prompt_annotates_index_point(self):
        """prompt 首段含「板块指数（BKxxxx，东财板块行情）点位」显式口径。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "板块指数（{resolved_code}，东财板块行情）" in src
        assert "点位为" in src
        assert "非成分股均价" in src
        assert "亦非沪深大盘指数" in src

    def test_sector_prompt_notes_ma_period(self):
        """技术面注明均线周期（最近 30 个交易日日线）。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "均线周期为最近 30 个交易日日线" in src

    def test_sector_prompt_keeps_constituents_news(self):
        """成分股/资讯注入保留（O26 只加标注，不删既有注入）。"""
        src = inspect.getsource(analysis_router.sector_analysis_stream)
        assert "成分股：{json.dumps(constituents" in src
        assert "资讯：{json.dumps(news" in src


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


import pytest

from app.services.market_data_hub import _parse_concept_tags


class TestParseConceptTags:
    def test_nested_dict_flat(self):
        """嵌套 dict {"concept_tag": [...]} 平铺为字符串数组。"""
        tag = {"concept_tag": ["消费电子概念", "苹果概念"], "popularity_tag": "涨停"}
        assert _parse_concept_tags(tag) == ["消费电子概念", "苹果概念"]

    def test_dict_without_concept_tag(self):
        assert _parse_concept_tags({"popularity_tag": "涨停"}) == []

    def test_list_of_dicts_flat(self):
        """list 内元素是 dict 时提取 concept_tag 字段。"""
        tag = [{"concept_tag": "半导体"}, {"concept_tag": "国产替代"}]
        assert _parse_concept_tags(tag) == ["半导体", "国产替代"]

    def test_plain_list_unchanged(self):
        assert _parse_concept_tags(["A", "B"]) == ["A", "B"]

    def test_string_dict_literal(self):
        """str 形式 dict 字面量（历史缓存格式）也能解析。"""
        tag = "{'concept_tag': ['消费电子概念', '苹果概念']}"
        assert _parse_concept_tags(tag) == ["消费电子概念", "苹果概念"]

    def test_none_empty(self):
        assert _parse_concept_tags(None) == []
        assert _parse_concept_tags("") == []
