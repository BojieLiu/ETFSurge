# -*- coding: utf-8 -*-
"""round31 R98: global 桶摘要缺口（英文标题欠分类 + rule 兜底覆盖）。

根因（§4.6）：`_ENGLISH_CATEGORY_KEYWORDS` 缺 export/budget/curb 等英文宏观/贸易词，
global RSS 英文标题部分落入 other（level 1）——既欠分类（重要度被压平），又不被
enrich_news_summaries 的 R90 rule 兜底（level≥3 才覆盖）命中 → ai_summary 恒 null。

修复：英文词表补 export/exports/budget/deficit/fiscal/spending/import（→ neutral，
宏观数据类）与 curb/curbs/restrict/restriction（→ negative，限制即利空）；
global 桶 level≥3 条目 rule 兜底覆盖由 R90 pass 承担（本测试补 global 场景断言）。

无网络：纯函数 / monkeypatch 断言。
"""
import pytest


class TestEnglishKeywordExpansionR98:
    def test_japan_exports_no_longer_other(self):
        """「Japan exports...」→ neutral（不再 other/level1 欠分类）。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("Japan exports rise for third month, beating forecasts")
        assert cat != "other", f"exports 应命中分类，实际 {cat}"
        assert level >= 2

    def test_us_budget_no_longer_other(self):
        """「US budget deficit...」→ neutral（宏观财政类）。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("US budget deficit widens as spending outpaces revenue")
        assert cat != "other", f"budget 应命中分类，实际 {cat}"
        assert level >= 2

    def test_curb_exports_is_negative(self):
        """「China curbs rare-earth exports」→ negative（限制即利空，level≥3）。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("China curbs rare-earth exports to US amid trade tension")
        assert cat in ("negative", "risk"), f"curb 应判 negative/risk，实际 {cat}"
        assert level >= 3

    def test_beats_remains_positive(self):
        """「beats」仍在 positive（回归保障，R98 词表补漏不破坏存量）。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("Meta beats earnings estimates, shares jump")
        assert cat == "positive", f"beats 应判 positive，实际 {cat}"
        assert level >= 3


class TestGlobalRuleSummaryCoverageR98:
    def _make_item(self, title, level):
        return {
            "id": f"g-{hash(title) % 100000}",
            "title": title,
            "content": "global news summary body.",
            "level": level,
            "stars": 4,
            "ai_summary": None,
            "ai_summary_source": None,
            "bucket": "global",
        }

    @pytest.mark.asyncio
    async def test_global_level3_gets_rule_summary(self, monkeypatch):
        """global 桶 level≥3 条目 ai_summary 非 null（rule 兜底覆盖，R98 ①）。"""
        from app.services.hub._news import NewsMixin

        mixin = NewsMixin()
        # 「curb」→ negative lv3 → 应被 R90 pass rule 兜底
        items = [
            self._make_item("China curbs rare-earth exports to US", 3),
            self._make_item("Japan exports surge on weak yen", 4),
        ]
        mixin._news_buckets = {"headlines": [], "macro": [], "global": items}
        mixin._news_cache_ts = 0

        async def _llm_fail(*a, **k):
            raise RuntimeError("quota")

        monkeypatch.setattr("app.analysis.llm.generate_news_summary", _llm_fail)
        await mixin.enrich_news_summaries(cap=6)

        for it in items:
            assert it.get("ai_summary"), f"{it['title']} ai_summary 仍为 null"
            assert it.get("ai_summary_source") in ("rule", "llm")
