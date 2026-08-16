"""round25 R31: 三桶 AI 摘要分桶配额——headlines 不再独占 cap。

问题（round25 §5.1 实证）：R17 `enrich_news_summaries(cap=6)` 三桶合并后按重要性取前 6
→ headlines 恒占满，macro 0/3、global 0/8 摘要——R17 验收「三桶均有摘要覆盖」未达。

修复（round25 R31）：分桶配额 headlines=ceil(cap*0.5) / macro=ceil(cap*0.33) / global
=剩余（cap=6 → 3/2/1），保证三桶均有摘要覆盖。
"""

import asyncio
from unittest.mock import patch

import pytest

from app.services.market_data_hub import MarketDataHub


def _news(title, stars=4, level=0, nid=None):
    return {"id": nid or title, "title": title, "content": f"{title} content",
            "stars": stars, "level": level}


class TestEnrichNewsSummariesBucketQuota:
    """R31: 分桶配额——三桶均有摘要覆盖。"""

    @pytest.mark.asyncio
    async def test_macro_and_global_get_summaries(self):
        """cap=6：headlines 6 条重要 + macro 3 条重要 + global 8 条重要 →
        macro/global 至少各 1 条摘要（负向：全在 headlines → FAIL）。"""
        hub = MarketDataHub()
        hub._news_buckets = {
            "headlines": [_news(f"h{i}", stars=5) for i in range(6)],
            "macro": [_news(f"m{i}", stars=4) for i in range(3)],
            "global": [_news(f"g{i}", stars=4) for i in range(8)],
        }
        hub._news_cache_ts = 0

        async def _fake_gen(title, content):
            return f"summary:{title}"
        with patch("app.analysis.llm.generate_news_summary", side_effect=_fake_gen):
            total = await hub.enrich_news_summaries(cap=6)

        assert total <= 6, "cap=6 摘要总数不得超过 6"
        macro_ok = [n for n in hub._news_buckets["macro"] if n.get("ai_summary")]
        global_ok = [n for n in hub._news_buckets["global"] if n.get("ai_summary")]
        assert len(macro_ok) >= 1, f"macro 桶必须至少 1 条摘要（R31 分桶配额），实际 0"
        assert len(global_ok) >= 1, f"global 桶必须至少 1 条摘要（R31 分桶配额），实际 0"
        # headlines 拿配额 3（不独占）
        head_ok = [n for n in hub._news_buckets["headlines"] if n.get("ai_summary")]
        assert len(head_ok) == 3, f"headlines 配额 3（cap=6 → 3/2/1），实际 {len(head_ok)}"

    @pytest.mark.asyncio
    async def test_headlines_cap_balanced(self):
        """headlines 不再占满 cap——只拿一半配额（cap=6 → 3）。"""
        hub = MarketDataHub()
        hub._news_buckets = {
            "headlines": [_news(f"h{i}", stars=5) for i in range(10)],
            "macro": [_news(f"m{i}", stars=4) for i in range(2)],
            "global": [],
        }
        hub._news_cache_ts = 0

        async def _fake_gen(title, content):
            return "s"
        with patch("app.analysis.llm.generate_news_summary", side_effect=_fake_gen):
            await hub.enrich_news_summaries(cap=6)

        head_ok = [n for n in hub._news_buckets["headlines"] if n.get("ai_summary")]
        assert len(head_ok) == 3, f"headlines 不得独占 cap（R31），实际 {len(head_ok)}"

    @pytest.mark.asyncio
    async def test_cap_one_still_works(self):
        """cap=1 极端：headlines 配额 1，macro/global 0（不炸）。"""
        hub = MarketDataHub()
        hub._news_buckets = {
            "headlines": [_news("h1", stars=5)],
            "macro": [_news("m1", stars=4)],
            "global": [],
        }
        hub._news_cache_ts = 0

        async def _fake_gen(title, content):
            return "s"
        with patch("app.analysis.llm.generate_news_summary", side_effect=_fake_gen):
            total = await hub.enrich_news_summaries(cap=1)
        assert total == 1

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_crash(self):
        """LLM 失败静默跳过（continue），不中断其它桶。"""
        hub = MarketDataHub()
        hub._news_buckets = {
            "headlines": [_news("h1", stars=5), _news("h2", stars=5)],
            "macro": [_news("m1", stars=4)],
            "global": [],
        }
        hub._news_cache_ts = 0
        calls = {"n": 0}

        async def _fake_gen(title, content):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("llm down")
            return "s"
        with patch("app.analysis.llm.generate_news_summary", side_effect=_fake_gen):
            total = await hub.enrich_news_summaries(cap=4)
        assert total >= 1, "LLM 单条失败不得中断整个 enrich"