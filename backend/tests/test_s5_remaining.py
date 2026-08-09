"""Tests for S5 remaining items: MarketDataHub alias, shares fetch, Hub-aware chart."""

from unittest.mock import MagicMock, patch

import pytest


# ── MarketDataHub alias ─────────────────────────────────────────────────


class TestMarketDataHubAlias:
    """S5 Step 8: MarketDataHub is the canonical data-pipeline entry (renamed from PoolManager)."""

    def test_market_data_hub_importable_as_class_and_singleton(self):
        """MarketDataHub class + market_data_hub singleton should both exist."""
        from app.services.market_data_hub import MarketDataHub, market_data_hub
        assert isinstance(market_data_hub, MarketDataHub)
        # The old pool_manager name must be gone (thorough rename, no alias)
        import app.services.market_data_hub as mdh
        assert not hasattr(mdh, "pool_manager"), "pool_manager alias should be removed"
        import app.services as svc_mod
        assert not hasattr(svc_mod, "pool_manager"), "app.services.pool_manager module should be gone"
        import importlib
        assert importlib.util.find_spec("app.services.pool_manager") is None, \
            "pool_manager.py should be renamed to market_data_hub.py"

    def test_market_data_hub_has_core_methods(self):
        """MarketDataHub should have the unified K-line methods."""
        from app.services.market_data_hub import MarketDataHub
        
        methods = ["get_kline", "get_kline_rows", "refresh_kline", "get_kline_symbols"]
        for m in methods:
            assert hasattr(MarketDataHub, m), f"MarketDataHub missing {m}()"

    def test_get_kline_symbols_exists(self):
        """get_kline_symbols() returns a list."""
        from app.services.market_data_hub import market_data_hub
        symbols = market_data_hub.get_kline_symbols()
        assert isinstance(symbols, list)


# ── Hub-aware get_history ──────────────────────────────────────────────


class TestMarketServiceHubAware:
    """S5 Step 6: get_history first checks Hub K-line cache."""

    @pytest.mark.asyncio
    async def test_get_history_hub_cache_hit(self):
        """When Hub has cached data, skip direct fetch."""
        from app.services import market_data_hub as mdh_module
        with patch.object(mdh_module.market_data_hub, "get_kline_rows") as mock_get_rows:
            # Mock cache hit
            mock_get_rows.return_value = [
                {"date": "2026-07-28", "close": 3.48,
                 "open": 3.45, "high": 3.52, "low": 3.42, "volume": 1e7}
            ]

            from app.services.market_service import get_history
            result = await get_history("510050")
            assert result is not None
            assert len(result) > 0


# ── fetch_etf_shares ────────────────────────────────────────────────────
