"""
F19 R68-R72 (combination-design-review.md F19): 因子数据管道修复。

- R68: fetch_market_sentiment 生成 sentiment_history（20 日滚动）——panic_greed_diff
      不再因结构性缺字段永远 no_data。
- R69: 因子 compute 注入段注入 advance_decline（stock_divergence 优先路径）。
- R70: _fetch_market_data 删除假市值 fallback（or 100e9 / 80e9）；gap 机制记录
      ln_mcap/ln_float_mcap 缺口；factors.py GAP_FIELD_MAP 标注缺失字段。
- R71: _enrich_symbol_extra 失败/空结果不写 24h 成功缓存。

无网络，mock 数据源。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fetchers import fundamentals_fetcher as ff
from app.fetchers.fundamentals_fetcher import fetch_market_sentiment


class TestR68SentimentHistory:
    @pytest.mark.asyncio
    async def test_fetch_market_sentiment_includes_history(self, monkeypatch):
        """R68: 返回结构含 sentiment_history（管道级断言——旧实现从不生成该字段）。"""
        async def _fake_run_sync(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "fetch_advance_decline_ratio":
                return 0.6
            if name == "_fetch_volume_ratio":
                return 1.1
            if name == "fetch_margin_change":
                return 0.01
            return None

        monkeypatch.setattr(ff, "run_sync", _fake_run_sync)
        result = await fetch_market_sentiment()
        hist = result.get("sentiment_history")
        assert hist is not None, "sentiment_history 必须存在（R68）"
        assert len(hist) >= 1, "sentiment_history 至少含当日值"
        assert isinstance(hist, list) and all(isinstance(v, float) for v in hist)

    @pytest.mark.asyncio
    async def test_sentiment_history_accumulates(self, monkeypatch):
        """R68: 多次调用滚动累积（满足 panic_greed_diff 的 len>=5 要求）。"""
        async def _fake_run_sync(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            return {"fetch_advance_decline_ratio": 0.5,
                    "_fetch_volume_ratio": 1.0,
                    "fetch_margin_change": 0.0}.get(name, None)

        monkeypatch.setattr(ff, "run_sync", _fake_run_sync)
        # 重置滚动数组，连续调用 6 次
        ff._sentiment_rolling.clear()
        for _ in range(6):
            await fetch_market_sentiment()
        hist = ff._sentiment_rolling
        assert len(hist) >= 5, f"6 次调用后滚动数组应 >=5: {len(hist)}"
        assert len(hist) <= 20, "滚动数组上限 20"


class TestR70FakeMarketValueRemoved:
    def test_no_fake_mv_fallback_in_source(self):
        """R70: 源码不再含 `or 100e9` / `or 80e9` 假市值 fallback（注释提及除外）。"""
        import inspect
        import re
        from app.factors import factor_registry
        src = inspect.getsource(factor_registry.FactorRegistry._fetch_market_data)
        # 剥离注释行后再检查（注释里提到旧值不算残留）
        code_only = re.sub(r"#.*$", "", src, flags=re.M)
        assert "or 100e9" not in code_only, "假市值 fallback `or 100e9` 必须删除"
        assert "or 80e9" not in code_only, "假流通市值 fallback `or 80e9` 必须删除"

    def test_gap_field_map_registered(self):
        """R70: factors.py GAP_FIELD_MAP 含 ln_mcap/ln_float_mcap 映射。"""
        from app.routers.factors import GAP_FIELD_MAP
        assert "style.size.ln_mcap" in GAP_FIELD_MAP
        assert "style.size.ln_float_mcap" in GAP_FIELD_MAP
        assert "fund_scale/total_mv" in GAP_FIELD_MAP["style.size.ln_mcap"]

    def test_ln_mcap_zero_guard(self):
        """R70/R85: _compute_ln_mcap 对 0 市值返回 None 不崩溃（mv>0 守卫，
        R85 改缺数据填 None——区分「真实 0」与「无数据」）。"""
        from app.factors.factor_registry import _compute_ln_mcap
        assert _compute_ln_mcap({"total_mv": 0}) is None
        assert _compute_ln_mcap({}) is None


class TestR71FailureCache:
    @pytest.mark.asyncio
    async def test_failed_shares_not_cached(self):
        """R71: 份额拉取失败/空结果不写 24h 缓存。"""
        from app.services.market_data_hub import MarketDataHub

        hub = MarketDataHub()
        hub._FUND_SHARES_CACHE.clear()
        base_extra = {"510300": {}}

        with patch("app.fetchers.china_market.fetch_etf_shares_outstanding",
                   new=MagicMock(return_value=None)), \
             patch("app.core.async_utils.run_sync",
                   new=AsyncMock(side_effect=lambda fn, *a, **kw: None)), \
             patch.object(hub, "get_market_history", new=AsyncMock(return_value=[])):
            out = await hub._enrich_symbol_extra(["510300"], base_extra)

        assert "510300" not in hub._FUND_SHARES_CACHE, \
            "失败结果不得写入 24h 成功缓存（R71）"
        assert "shares_change_20d" not in out.get("510300", {})

    @pytest.mark.asyncio
    async def test_success_shares_cached(self):
        """R71 回归: 成功结果正常写缓存。"""
        from app.services.market_data_hub import MarketDataHub

        hub = MarketDataHub()
        hub._FUND_SHARES_CACHE.clear()
        base_extra = {"510300": {}}

        with patch("app.fetchers.china_market.fetch_etf_shares_outstanding",
                   new=MagicMock(return_value={"shares_change_20d": 0.05})), \
             patch("app.core.async_utils.run_sync",
                   new=AsyncMock(side_effect=lambda fn, *a, **kw: {"shares_change_20d": 0.05})), \
             patch.object(hub, "get_market_history", new=AsyncMock(return_value=[])):
            out = await hub._enrich_symbol_extra(["510300"], base_extra)

        assert "510300" in hub._FUND_SHARES_CACHE, "成功结果应写入缓存"
        assert out["510300"]["shares_change_20d"] == 0.05
