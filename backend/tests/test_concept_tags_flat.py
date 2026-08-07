"""
O9 (docs/archived/round8-rediagnosis.md §7 P9-新): stock-hot-rank.concept_tags 平铺填充。

现象: contract F2-6 声明 concept_tags 字段，实际 50/50 全空——数据源 tag 是嵌套
dict {"concept_tag": [...], "popularity_tag": "..."}，_parse_concept_tags 对 dict
输入直接返回 []。

修复（已拍板：后端平铺填充，不改契约字段）: 识别嵌套 dict/list 的 concept_tag
键并平铺为字符串数组。
"""

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
