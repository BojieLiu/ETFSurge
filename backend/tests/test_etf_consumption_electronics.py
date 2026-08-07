"""
O15 (docs/round8-rediagnosis.md §7 §5.1A): 562950 消费电子不再误归「食品饮料」。

根因: etf_scanner.INDEX_KEYWORDS 无「消费电子」键 + _extract_index_keyword 按
dict 插入序遍历——'消费电子ETF易方达' 的 tracked_index 回填为 '消费'（丢 '电子'），
classifier 的 tracked_index 优先路径命中 ('消费','食品饮料') 直接返回。

修复: INDEX_KEYWORDS 加「消费电子」+ _extract_index_keyword 改最长匹配优先；
classifier 侧 ('消费电子','电子') 精确规则 round7 O23 已有（前置在 ('消费',...) 前）。

验收: ① 562950 industry='电子' 且 tracked_index != '消费'；② 新增 562950 分类单测；
③ _extract_index_keyword('消费电子ETF') 返回 '消费电子' 而非 '消费'。
"""

import pytest

from app.fetchers.etf_scanner import _extract_index_keyword, INDEX_KEYWORDS
from app.services.etf_classifier import classifier


class TestExtractIndexKeyword:
    def test_consumption_electronics_longest_match(self):
        """③: '消费电子ETF' → '消费电子'（最长匹配优先，不被 '消费' 截走）。"""
        assert _extract_index_keyword("消费电子ETF易方达") == "消费电子"
        assert _extract_index_keyword("消费电子ETF") == "消费电子"

    def test_plain_consumption_still_matches(self):
        """普通消费 ETF 仍命中 '消费'。"""
        assert _extract_index_keyword("消费50ETF") == "消费"
        assert _extract_index_keyword("主要消费ETF") == "消费"

    def test_keyword_present(self):
        assert "消费电子" in INDEX_KEYWORDS
        assert "消费" in INDEX_KEYWORDS


class TestClassify562950:
    def test_562950_industry_electronics(self):
        """①: 562950（消费电子ETF易方达）→ industry='电子'、tracked_index='消费电子'。"""
        result = classifier.batch_classify([{
            "symbol": "562950", "name": "消费电子ETF易方达", "tracked_index": "消费电子",
        }])
        entry = result["562950"]
        assert entry["industry"] == "电子", f"562950 应归电子，实得 {entry['industry']}"
        assert entry["industry"] != "食品饮料"

    def test_562950_empty_tracked_index_via_name(self):
        """tracked_index 为空时从名称提取（'消费电子'）→ 仍归电子。"""
        result = classifier.batch_classify([{
            "symbol": "562950", "name": "消费电子ETF易方达", "tracked_index": "",
        }])
        assert result["562950"]["industry"] == "电子"

    def test_plain_consumption_etf_unaffected(self):
        """普通消费 ETF 仍归食品饮料（不破坏既有分类）。"""
        result = classifier.batch_classify([{
            "symbol": "159928", "name": "消费ETF", "tracked_index": "中证消费",
        }])
        assert result["159928"]["industry"] == "食品饮料"
