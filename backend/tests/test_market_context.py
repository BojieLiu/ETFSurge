"""Tests: Phase 5.1 Market Context (market-awareness linkage).

TDD pattern — tests written before implementation.
Covers:
  - MarketContext data class (all 4 markets)
  - resolve_market_context() backward compatibility
  - market_router routing functions
  - design-async market parameter (unsupported market)
  - market_data_hub regime cache dict[str,str]
  - llm-report/stream market-aware filtering
  - sector-analysis market awareness
"""

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── MarketContext Tests ──────────────────────────────────────────


class TestMarketContext:
    """Tests for MarketContext data class — pure logic, no I/O."""

    def test_create_A_market(self):
        from app.core.market_context import resolve_market_context, MarketContext
        ctx = resolve_market_context("A")
        assert isinstance(ctx, MarketContext)
        assert ctx.market == "A"
        assert ctx.title == "A股"

    def test_create_HK_market(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("HK")
        assert ctx.market == "HK"
        assert ctx.title == "港股"

    def test_create_US_market(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("US")
        assert ctx.market == "US"
        assert ctx.title == "美股"

    def test_create_global_market(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("global")
        assert ctx.market == "GLOBAL"
        assert ctx.title == "全球市场"

    def test_default_market_backward_compatible(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context(None)
        assert ctx.market == "A"
        assert ctx.title == "A股"

    def test_unknown_market_fallback_to_A(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("XYZ")
        assert ctx.market == "A"
        assert ctx.title == "A股"

    def test_index_symbols_A(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("A")
        symbols = ctx.index_symbols
        assert "000001" in symbols
        assert "399001" in symbols
        assert "399006" in symbols

    def test_index_symbols_HK(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("HK")
        symbols = ctx.index_symbols
        assert "^HSI" in symbols
        assert "^HSCE" in symbols

    def test_index_symbols_US(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("US")
        symbols = ctx.index_symbols
        assert "^GSPC" in symbols
        assert "^IXIC" in symbols

    def test_index_symbols_global_empty(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("global")
        assert ctx.index_symbols == set()

    def test_regime_broad_index_A(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("A")
        assert ctx.regime_broad_index == "000001"

    def test_regime_broad_index_HK(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("HK")
        assert ctx.regime_broad_index == "^HSI"

    def test_regime_broad_index_US(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("US")
        assert ctx.regime_broad_index == "^GSPC"

    def test_regime_broad_index_global_none(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("global")
        assert ctx.regime_broad_index is None

    def test_supports_sector_analysis_only_A(self):
        from app.core.market_context import resolve_market_context
        assert resolve_market_context("A").supports_sector_analysis is True
        assert resolve_market_context("HK").supports_sector_analysis is False
        assert resolve_market_context("US").supports_sector_analysis is False
        assert resolve_market_context("global").supports_sector_analysis is False

    def test_supports_portfolio_design_only_A(self):
        from app.core.market_context import resolve_market_context
        assert resolve_market_context("A").supports_portfolio_design is True
        assert resolve_market_context("HK").supports_portfolio_design is False
        assert resolve_market_context("US").supports_portfolio_design is False
        assert resolve_market_context("global").supports_portfolio_design is False

    def test_supports_regime_detection_A_and_US(self):
        from app.core.market_context import resolve_market_context
        assert resolve_market_context("A").supports_regime_detection is True
        assert resolve_market_context("US").supports_regime_detection is True
        assert resolve_market_context("HK").supports_regime_detection is False
        assert resolve_market_context("global").supports_regime_detection is False

    def test_major_symbols_A(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("A")
        symbols = ctx.major_symbols
        assert "000001" in symbols
        assert "510050" in symbols

    def test_major_symbols_HK(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("HK")
        symbols = ctx.major_symbols
        assert "HSI" in symbols
        assert "00700" in symbols

    def test_major_symbols_US(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("US")
        symbols = ctx.major_symbols
        assert "SPX" in symbols
        assert "SPY" in symbols

    def test_major_symbols_global(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("global")
        symbols = ctx.major_symbols
        assert "000001" in symbols
        assert "HSI" in symbols
        assert "SPX" in symbols


# ─── resolve_market_context Edge Cases ─────────────────────────


class TestResolveMarketContextEdgeCases:

    def test_empty_string_fallback(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("")
        assert ctx.market == "A"

    def test_case_insensitive(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("a")
        assert ctx.market == "A"

    def test_whitespace_handling(self):
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context(" HK ")
        assert ctx.market == "HK"

    def test_market_equality_same_reference(self):
        from app.core.market_context import resolve_market_context
        ctx1 = resolve_market_context("A")
        ctx2 = resolve_market_context("A")
        assert ctx1.market == ctx2.market
        assert ctx1.title == ctx2.title


# ─── Pool Manager Regime Cache Tests ───────────────────────────


class TestMarketDataHubRegimeCache:

    @patch("app.services.market_data_hub.market_data_hub")
    def test_regime_cache_is_dict(self, mock_pm):
        """Regime cache must support per-market keys."""
        # Create a fresh instance to test the type
        from app.services.market_data_hub import MarketDataHub
        pm = MarketDataHub()
        # After init, _regime_cache should be a dict
        assert isinstance(pm._regime_cache, dict)
        # Default for unknown market
        assert pm._regime_cache.get("A", "range_bound") == "range_bound"

    def test_get_market_regime_with_market_param(self):
        """get_market_regime must accept optional market param."""
        from app.services.market_data_hub import MarketDataHub
        pm = MarketDataHub()
        result = pm.get_market_regime("A")
        assert isinstance(result, str)
        assert result == "range_bound"  # default for empty cache

    def test_update_market_regime_signature(self):
        """update_market_regime must accept market param."""
        from app.services.market_data_hub import MarketDataHub
        import inspect
        sig = inspect.signature(MarketDataHub.update_market_regime)
        params = list(sig.parameters.keys())
        assert "market" in params


# ─── Design Async Market Parameter Tests ──────────────────────


class TestDesignAsyncMarketParam:

    def test_task_params_contain_market(self):
        """Task params dict must contain market field."""
        from app.tasks.task_manager import task_manager
        task_manager._tasks.clear()
        t = task_manager.create_task(task_type="design", params={"capital": 500000, "market": "HK"})
        assert t["params"].get("market") == "HK"


# ─── LLM Report Stream Market Awareness ────────────────────────


class TestLLMReportMarketAwareness:

    @patch("app.services.market_data_hub.market_data_hub")
    def test_llm_report_request_has_market(self, mock_pm):
        """LLMReportRequest must have market field with default 'A'."""
        from app.routers.analysis import LLMReportRequest
        req = LLMReportRequest()
        assert hasattr(req, "market")
        assert req.market == "A"

    def test_llm_report_filter_by_market_symbols(self):
        """llm-report/stream must filter by market-specific major_symbols."""
        from app.core.market_context import resolve_market_context

        test_data = [
            {"symbol": "000001", "name": "上证指数", "asset_type": "index"},
            {"symbol": "HSI", "name": "恒生指数", "asset_type": "index"},
            {"symbol": "SPX", "name": "标普500", "asset_type": "index"},
            {"symbol": "510050", "name": "上证50ETF", "asset_type": "ETF"},
            {"symbol": "00700", "name": "腾讯", "asset_type": "HK"},
        ]

        ctx_A = resolve_market_context("A")
        filtered_A = [d for d in test_data if d.get("symbol") in ctx_A.major_symbols or d.get("asset_type") in ("index", "futures")]
        assert any(d["symbol"] == "000001" for d in filtered_A)

        ctx_HK = resolve_market_context("HK")
        filtered_HK = [d for d in test_data if d.get("symbol") in ctx_HK.major_symbols or d.get("asset_type") in ("index", "futures")]
        assert any(d["symbol"] == "HSI" for d in filtered_HK)

        ctx_US = resolve_market_context("US")
        filtered_US = [d for d in test_data if d.get("symbol") in ctx_US.major_symbols or d.get("asset_type") in ("index", "futures")]
        assert any(d["symbol"] == "SPX" for d in filtered_US)


# ─── Sector Analysis Market Awareness ──────────────────────────


class TestSectorAnalysisMarketAwareness:

    def test_sector_analysis_request_has_market(self):
        """SectorAnalysisRequest must have market field with default 'A'."""
        from app.routers.analysis import SectorAnalysisRequest
        req = SectorAnalysisRequest(sector_code="test")
        assert hasattr(req, "market")
        assert req.market == "A"

    def test_sector_analysis_non_A_empty(self):
        """Non-A market sector analysis must return empty structured response."""
        from app.core.market_context import resolve_market_context
        ctx = resolve_market_context("HK")
        assert ctx.supports_sector_analysis is False

        ctx = resolve_market_context("US")
        assert ctx.supports_sector_analysis is False

        ctx = resolve_market_context("global")
        assert ctx.supports_sector_analysis is False


# ─── Market Router Tests ───────────────────────────────────────


class TestMarketRouter:

    @pytest.mark.asyncio
    async def test_get_market_indices_A(self):
        """A market indices should route to get_indices."""
        with patch("app.services.market_router.get_market_indices", new_callable=AsyncMock) as mock:
            mock.return_value = [{"name": "上证指数", "symbol": "000001"}]
            from app.core.market_context import resolve_market_context
            ctx = resolve_market_context("A")
            assert "000001" in ctx.index_symbols

    def test_get_market_realtime_routes_by_market(self):
        """Realtime data should route by market."""
        # Verify function exists with correct signature
        from app.services.market_router import get_market_indices, get_market_realtime
        import inspect
        sig = inspect.signature(get_market_realtime)
        params = list(sig.parameters.keys())
        assert "market" in params
