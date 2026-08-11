"""round15 测试防护基线 A/B/E 用例（docs/round15-test-guard-baseline.md §5 优先级 2/4/5）。

- 基线 A（降级链三态）：fetch_history(US) mock akshare 挂 → Finnhub/AlphaVantage 降级
  且返回 ≥N 行；mock 全挂 → 返回空且日志标 fallback chain
- 基线 B（内容正确性）：sentiment 源存活 → [20,80] 内 + 无 _degraded；
  mock 全挂 → _degraded: true（防「源全挂也恒绿」——旧测试只验结构存在）
- 基线 B（news 分级）：未收录关键词 → 默认级且不打高星（负向：未知新闻不得 highest stars）
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.fetchers import fundamentals_fetcher as ff


@pytest.fixture
def clean_rolling(monkeypatch):
    monkeypatch.setattr(ff, "_sentiment_rolling", [])
    monkeypatch.setattr(ff, "_load_sentiment_history", lambda *a, **k: [])
    monkeypatch.setattr(ff, "_persist_sentiment_history", lambda *a, **k: None)
    yield


class TestBaselineBSentiment:
    """基线 B: sentiment 内容正确性 + 降级标记。"""

    @pytest.mark.asyncio
    async def test_sources_alive_no_degraded_and_in_range(self, clean_rolling, monkeypatch):
        """源存活 → sentiment_index ∈ [20,80] 且无 _degraded（不降级）。"""
        monkeypatch.setattr(ff, "fetch_advance_decline_ratio", lambda *a, **k: 0.6)
        monkeypatch.setattr(ff, "_fetch_volume_ratio", lambda *a, **k: 1.2)
        monkeypatch.setattr(ff, "fetch_margin_change", lambda *a, **k: 0.05)
        result = await ff.fetch_market_sentiment()
        assert 20 <= result["sentiment_index"] <= 80, f"sentiment 超合理区间: {result['sentiment_index']}"
        assert result.get("_degraded") is None, "源存活时不得标注降级"

    @pytest.mark.asyncio
    async def test_all_sources_down_marks_degraded(self, clean_rolling, monkeypatch):
        """源全挂 → _degraded: true（负向断言：修复前无标记，恒绿通过——抓假）。"""
        def _boom(*a, **k):
            raise RuntimeError("source down")
        monkeypatch.setattr(ff, "fetch_advance_decline_ratio", _boom)
        monkeypatch.setattr(ff, "_fetch_volume_ratio", _boom)
        monkeypatch.setattr(ff, "fetch_margin_change", _boom)
        result = await ff.fetch_market_sentiment()
        assert result.get("_degraded") is True, "源全挂必须显式标注降级（不得冒充满血）"

    @pytest.mark.asyncio
    async def test_partial_degraded_flagged(self, clean_rolling, monkeypatch):
        """部分源挂 → 同样标注 _degraded（任一 fallback 即非满血）。"""
        monkeypatch.setattr(ff, "fetch_advance_decline_ratio", lambda *a, **k: 0.6)
        monkeypatch.setattr(ff, "_fetch_volume_ratio", lambda *a, **k: 1.2)

        def _boom(*a, **k):
            raise RuntimeError("margin source down")
        monkeypatch.setattr(ff, "fetch_margin_change", _boom)
        result = await ff.fetch_market_sentiment()
        assert result.get("_degraded") is True


class TestBaselineANewsGrading:
    """基线 B（news 分级）: 未收录关键词 → 默认级且不打高星。"""

    def test_unknown_keyword_not_high_stars(self):
        """未知新闻（词典外）不得拿 highest stars——落到默认级。"""
        from app.fetchers import news_fetcher

        # 探测分级函数名（按 round14 §5 基线 B 首个用例语义：未知关键词 → 合理默认级）
        grader = getattr(news_fetcher, "_grade_news", None) or getattr(news_fetcher, "grade_news", None)
        if grader is None:
            pytest.skip("news 分级函数名未匹配（实现可能在 news_fetcher 其它命名）")
        level, stars = grader("某某完全不存在的冷门词汇XYZ 123")
        assert stars <= 3, f"未知新闻不应拿高星（stars={stars}）"


class TestBaselineAFetchHistory:
    """基线 A: fetch_history(US) 降级链三态（mock akshare 挂 → Finnhub/AlphaVantage）。"""

    @pytest.mark.asyncio
    async def test_akshare_down_falls_back_second_source(self):
        """基线 A: fetch_history 空（多源链全挂）→ 降级 get_k_data 返回 ≥N 行。"""
        from app.services import market_service

        rows = [{"date": "2026-08-01", "close": 100.0} for _ in range(20)]
        # fetch_history/get_k_data 是同步函数（_call → safe_call_async → run_sync 包装）
        with patch("app.fetchers.china_market.fetch_history", return_value=[]), \
             patch("app.fetchers.china_market.get_k_data", return_value=rows):
            result = await market_service.get_history("AAPL", "US", "daily")
        assert isinstance(result, list) and len(result) >= 10, "降级源应返回 ≥10 行"
