from __future__ import annotations
"""
F17 R60-R63 (combination-design-review.md F17): 数据源页修复。

- R60: /sources/health 过滤 threadpool_* 探针（不展示为"数据源"）。
- R61: 域名集中常量 EM_PUSH_HOST（实测 push2 502/HTTPS 连接关闭 → 保留 push2delay）。
- R62: fund_flow 熔断 gate 从 push2delay 改为 akshare 源健康。
- R63: 代码库无散落 push2delay 硬编码（仅集中常量定义处）。

无网络，mock。
"""

import re
from unittest.mock import MagicMock, patch

from app.core.market_context import EM_PUSH_HOST


class TestR61DomainConstant:
    def test_em_push_host_centralized(self):
        """R61: 集中常量保留 push2delay（实测 push2 不可达记录在案）。"""
        assert EM_PUSH_HOST == "push2delay.eastmoney.com"

    def test_no_scattered_push2delay_hardcode(self):
        """R63: 代码库无散落 push2delay 硬编码（仅集中常量处 + 注释）。"""
        import os
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        hits = []
        for py in root.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            if "push2delay.eastmoney.com" in text:
                hits.append(str(py.relative_to(root)))
        # 允许: market_context.py（常量定义）、fundamentals_fetcher.py（注释/import）、
        # etf_scanner.py（R5-2-6 双源路由：push2 优先 → push2delay 兜底，集中两处域名）
        allowed = {"core\\market_context.py", "core/market_context.py",
                   "fetchers\\fundamentals_fetcher.py", "fetchers/fundamentals_fetcher.py",
                   "fetchers\\etf_scanner.py", "fetchers/etf_scanner.py",
                   # round9 P2-3: sector_fetcher.fetch_em_sector_changes 双源路由
                   # （EM_PUSH_HOST 主源 + push2 备份）——注释与实现对齐后加入白名单
                   "fetchers\\sector_fetcher.py", "fetchers/sector_fetcher.py"}
        extra = [h for h in hits if h not in allowed]
        assert not extra, f"push2delay 硬编码散落在: {extra}"


class TestR60SourcesHealthFilter:
    def test_threadpool_filtered_from_health(self):
        """R60: /sources/health 不返回 threadpool_* 条目。"""
        from app.routers import admin

        states = {
            "threadpool_main": MagicMock(_lock=MagicMock(), _cool_until=0, _failures=0),
            "threadpool_akshare": MagicMock(_lock=MagicMock(), _cool_until=0, _failures=0),
            "push2delay.eastmoney.com": MagicMock(_lock=MagicMock(), _cool_until=0, _failures=0),
            "akshare": MagicMock(_lock=MagicMock(), _cool_until=0, _failures=0),
        }
        for h in states.values():
            h.cooldown = 60
            h.failure_threshold = 3

        with patch("app.routers.admin.registry") as mock_reg:
            mock_reg.get_states.return_value = states
            import asyncio
            result = asyncio.run(admin.get_sources_health())

        names = [r["name"] for r in result]
        assert not any(n.startswith("threadpool_") for n in names), \
            f"threadpool_* 不得出现在数据源页: {names}"
        assert "push2delay.eastmoney.com" in names and "akshare" in names


class TestR62FundFlowGate:
    def test_fetch_fund_flow_uses_akshare_gate(self):
        """R62: fund_flow 路径 gate 改为 akshare 健康（不再被 push2delay 误伤）。"""
        import inspect
        from app.fetchers import fundamentals_fetcher as ff
        src = inspect.getsource(ff.fetch_fund_flow)
        assert "_akshare_available()" in src, "fund_flow gate 应为 akshare 健康检查"
        assert "_push2_available()" not in src, "fund_flow 不应再被 push2delay gate 误伤"

    def test_advance_decline_keeps_push2_gate(self):
        """R62 回归: 涨跌家数（真实走 push2delay HTTP）保持 push2 gate。"""
        import inspect
        from app.fetchers import fundamentals_fetcher as ff
        src = inspect.getsource(ff.fetch_advance_decline_ratio)
        assert "_push2_h.available" in src, "涨跌家数应保留 push2delay 熔断检查"


# ===== folded from test_round15_guard_baseline.py =====
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
        from app.fetchers.levistock_fetcher import classify_news_level

        # P2-1 (round16 §5 盲区②): 探测旧函数名 _grade_news/grade_news 不存在 →
        # 恒 SKIP 从不生效。真实函数是 classify_news_level(title, content) 返回 int 1-5。
        level = classify_news_level("某某完全不存在的冷门词汇XYZ 123")
        assert isinstance(level, int) and 1 <= level <= 5
        assert level <= 3, f"未知新闻不应拿高星（level={level}）"
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
