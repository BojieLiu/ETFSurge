"""
Text Pipeline Path B: LLM-powered news sentiment analysis.

Uses DeepSeek API (via llm_complete_with_system) to classify news headlines
by sentiment, sector impact, and geopolitical relevance.

This complements Path A (keyword-based) with deeper semantic understanding.
"""
from __future__ import annotations

import json
import asyncio
import logging
from typing import Any

from ..analysis.llm import llm_complete_with_system
from .text_pipeline import pipeline as path_a

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是专业的金融新闻分析助手。分析每条新闻标题，输出 JSON：
{
  "sentiment": "positive" | "negative" | "neutral",
  "score": 0.0-1.0,
  "sectors": ["受影响行业"],
  "category": "policy" | "economic" | "geopolitical" | "market" | "other",
  "reason": "简短理由"
}

规则：
- positive (0.6-1.0): 政策宽松、增长超预期、利好
- negative (0.0-0.4): 收紧、地缘冲突、利空
- neutral (0.4-0.6): 中性消息、无明确方向
- sectors: 影响的申万行业，最多3个
- 只输出 JSON，不要额外文字"""


class NewsLLMAnalyzer:
    """LLM 驱动的新闻情绪分析器。"""

    async def _call_llm(self, headline: str) -> str:
        """调用 DeepSeek API 分析单条新闻。"""
        try:
            prompt = self._build_prompt(headline)
            result = await llm_complete_with_system(_SYSTEM_PROMPT, prompt, force_json=True)
            return result or ""
        except Exception as e:
            logger.warning("LLM news analysis failed: %s", e)
            return ""

    def _build_prompt(self, headline: str) -> str:
        """构建 LLM 提示词。"""
        return f"分析这条金融新闻：{headline}"

    def _parse_response(self, text: str) -> dict[str, Any]:
        """解析 LLM 返回的 JSON。"""
        if not text:
            return {"sentiment": "neutral", "score": 0.5, "sectors": [], "category": "other", "reason": ""}
        try:
            data = json.loads(text)
            return {
                "sentiment": data.get("sentiment", "neutral"),
                "score": float(data.get("score", 0.5)),
                "sectors": data.get("sectors", []),
                "category": data.get("category", "other"),
                "reason": data.get("reason", ""),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"sentiment": "neutral", "score": 0.5, "sectors": [], "category": "other", "reason": ""}

    async def batch_analyze(
        self,
        headlines: list[str],
        max_workers: int = 5,
    ) -> dict[int, dict[str, Any]]:
        """批量分析多条新闻。

        Args:
            headlines: 新闻标题列表。
            max_workers: 并发数。

        Returns:
            {index: {sentiment, score, sectors, category, reason}}
        """
        if not headlines:
            return {}

        sem = asyncio.Semaphore(max_workers)

        async def _analyze_one(idx: int, headline: str) -> tuple[int, dict[str, Any]]:
            async with sem:
                raw = await self._call_llm(headline)
                result = self._parse_response(raw)
                return idx, result

        tasks = [_analyze_one(i, h) for i, h in enumerate(headlines)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[int, dict[str, Any]] = {}
        for r in results:
            if isinstance(r, tuple):
                idx, result = r
                output[idx] = result
        return output

    def aggregate(self, results: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """聚合多条新闻情绪为综合指标。

        Returns:
            {
                "avg_score": float,
                "positive_count": int,
                "negative_count": int,
                "neutral_count": int,
                "total": int,
                "sector_hits": {sector: count},
            }
        """
        if not results:
            return {"avg_score": 0.5, "positive_count": 0, "negative_count": 0,
                    "neutral_count": 0, "total": 0, "sector_hits": {}}

        scores = []
        pos = neg = neu = 0
        sector_hits: dict[str, int] = {}

        for r in results.values():
            scores.append(r.get("score", 0.5))
            s = r.get("sentiment", "neutral")
            if s == "positive":
                pos += 1
            elif s == "negative":
                neg += 1
            else:
                neu += 1
            for sector in r.get("sectors", []):
                sector_hits[sector] = sector_hits.get(sector, 0) + 1

        return {
            "avg_score": sum(scores) / len(scores) if scores else 0.5,
            "positive_count": pos,
            "negative_count": neg,
            "neutral_count": neu,
            "total": len(results),
            "sector_hits": sector_hits,
        }

    def breakdown_by_category(
        self,
        results: dict[int, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """按类别拆分情绪：policy / economic / geopolitical / market / other。

        Returns:
            {category: {"avg_score": float, "count": int, "items": [...]}}
        """
        categories: dict[str, list[dict]] = {}
        for r in results.values():
            cat = r.get("category", "other")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        output = {}
        for cat, items in categories.items():
            scores = [i.get("score", 0.5) for i in items]
            output[cat] = {
                "avg_score": sum(scores) / len(scores) if scores else 0.5,
                "count": len(items),
            }
        return output

    async def full_pipeline(
        self,
        headlines: list[str],
    ) -> dict[str, Any]:
        """完整管道：关键词分析（路径A）+ LLM 分析（路径B）。

        Returns 合并了路径A和路径B的结果。
        """
        path_b_results = await self.batch_analyze(headlines)
        path_b_agg = self.aggregate(path_b_results)
        path_b_breakdown = self.breakdown_by_category(path_b_results)
        path_a_result = path_a.compute_all(headlines)

        return {
            "path_a": path_a_result,
            "path_b": {
                "per_news": {str(k): v for k, v in path_b_results.items()},
                "aggregate": path_b_agg,
                "category_breakdown": path_b_breakdown,
            },
            "combined_sentiment": {
                "keyword_score": path_a_result.get("policy_easing", 0.5),
                "llm_avg_score": path_b_agg.get("avg_score", 0.5),
                "llm_positive_pct": (
                    path_b_agg["positive_count"] / path_b_agg["total"]
                    if path_b_agg.get("total", 0) > 0 else 0.5
                ),
            },
        }


# Global singleton
news_llm = NewsLLMAnalyzer()
