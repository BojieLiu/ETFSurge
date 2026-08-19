# -*- coding: utf-8 -*-
"""round30 R90: 资讯分类欠分类 + 摘要缺口。

根因（§6）：`_CATEGORY_KEYWORDS` 未覆盖「连涨/袭击/致命/威胁」等；英文词表缺
"attack(s)"；enrich_news_summaries 分桶配额（cap=6 → macro=2/global=1）使配额外
level≥3 高重要性条目 ai_summary 恒 null。

修复：
  ① 补词：连涨/提价→positive；袭击/致命/威胁→risk；英文 attack(s)→risk/major；
  ② enrich_news_summaries 追加「配额外 level≥3 全量 rule 兜底」pass。

无网络：纯函数断言。
"""
import pytest


class TestKeywordExpansionR90:
    def test_lianzhang_is_positive(self):
        """「广州新房五连涨」→ positive（level≥3），不得再 other。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("广州新房五连涨，市场回暖信号明显")
        assert cat == "positive", f"连涨应判 positive，实际 {cat}"
        assert level >= 3

    def test_fatal_combo_is_risk(self):
        """「经济学家评特朗普政策'致命组合拳'」→ risk/negative，不得 positive。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news('经济学家评特朗普政策"致命组合拳"：美国经济面临压力')
        assert cat in ("risk", "negative"), f"致命应判 risk/negative，实际 {cat}"
        assert level >= 3

    def test_attacks_english_is_risk(self):
        """「Iran attacks US targets」→ risk≥4（英文 attack(s) 命中）。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("Iran attacks US targets in new escalation")
        assert cat == "risk", f"attacks 应判 risk，实际 {cat}"
        assert level >= 4

    def test_weixie_is_risk(self):
        """「威胁」类地缘/安全标题 → risk。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, level = classify_news("美方威胁升级对华关税，全球市场承压")
        assert cat == "risk", f"威胁应判 risk，实际 {cat}"


class TestRuleSummaryCoverageR90:
    def _make_item(self, bucket, level, title, content="正文内容。"):
        return {
            "id": f"{bucket}-{level}",
            "title": title,
            "content": content,
            "level": level,
            "stars": 3,
            "ai_summary": None,
            "ai_summary_source": None,
            "bucket": bucket,
        }

    @pytest.mark.asyncio
    async def test_rule_summary_covers_quota_overflow_level3(self, monkeypatch):
        """macro/global 配额外 level≥3 条目 ai_summary 非 null（rule 兜底全量覆盖）。"""
        from app.services.hub._news import NewsMixin

        mixin = NewsMixin()
        # macro 5 条 level>=3（配额仅 2）→ 其余 3 条必须被 rule 兜底
        macro = [self._make_item("macro", 3, f"宏观政策头条{i}") for i in range(5)]
        global_news = [self._make_item("global", 4, f"Global headline{i}") for i in range(3)]
        mixin._news_buckets = {"headlines": [], "macro": macro, "global": global_news}
        mixin._news_cache_ts = 0

        # LLM 生成失败（配额空窗）→ rule 兜底（_news 模块内 `from ...analysis.llm
        # import generate_news_summary`，patch app.analysis.llm.generate_news_summary）
        async def _llm_fail(*a, **k):
            raise RuntimeError("quota")
        monkeypatch.setattr("app.analysis.llm.generate_news_summary", _llm_fail)

        await mixin.enrich_news_summaries(cap=6)

        # 所有 level>=3 条目 ai_summary 非 null
        for it in macro + global_news:
            assert it.get("ai_summary"), f"{it['title']} ai_summary 仍为 null"
            assert it.get("ai_summary_source") in ("rule", "llm")
