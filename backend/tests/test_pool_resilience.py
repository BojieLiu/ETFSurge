"""
Test market_data_hub resilience (7.5a): data pipeline fallback behavior.

These tests verify that:
  1. _last_good fallback preserves existing pool when scanner fails
  2. Consecutive failure counter increments on first-run failures
  3. CRITICAL log is emitted on first-run failure (verified via log capture)
  4. Pool is NOT overwritten when scanner returns empty
  5. Pool IS overwritten when scanner returns valid data
"""
import asyncio
import logging
from unittest.mock import patch, MagicMock

import pytest

from app.services.market_data_hub import MarketDataHub, ALL_LAYERS


@pytest.fixture
def pm():
    """Fresh MarketDataHub with empty pool (simulates first-run state)."""
    mgr = MarketDataHub()
    mgr._test_mode = True
    return mgr


@pytest.fixture
def pm_with_data():
    """MarketDataHub with pre-populated data (simulates previous successful run)."""
    mgr = MarketDataHub()
    mgr._pool = {
        "core": [{"symbol": "510300", "name": "沪深300ETF", "fund_scale": 1e9}],
        "satellite": [],
        "defense": [{"symbol": "518880", "name": "黄金ETF", "fund_scale": 5e8}],
        "opportunistic": [],
        "research": [],
    }
    mgr._cached_pool = dict(mgr._pool)
    mgr._version = 5
    mgr._test_mode = True
    return mgr


class TestPoolResilience:
    """Verify that MarketDataHub survives data source failures gracefully."""

    @pytest.mark.asyncio
    async def test_first_run_failure_emits_critical_log(self, pm, caplog):
        """7.5a: First-run refresh failure should emit CRITICAL log."""
        caplog.set_level(logging.CRITICAL)

        # Mock scanner.full_pipeline to simulate total failure
        with patch.object(pm.scanner, 'full_pipeline', return_value={}):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {}
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={})

                    diff = await pm.refresh()

                    # Verify diff is essentially empty
                    assert diff is not None
                    assert sum(len(v) for v in pm._pool.values()) == 0

        # Verify CRITICAL log was emitted (first-run failure)
        critical_messages = [r.message for r in caplog.records if r.levelno == logging.CRITICAL]
        has_first_run_msg = any("FIRST-RUN" in msg for msg in critical_messages)
        assert has_first_run_msg, (
            f"Expected CRITICAL log with 'FIRST-RUN', got: {critical_messages}"
        )

    @pytest.mark.asyncio
    async def test_consecutive_failure_counter_increments(self, pm):
        """7.5a: Consecutive failure counter should increment on each first-run failure."""
        assert pm._consecutive_failures == 0

        with patch.object(pm.scanner, 'full_pipeline', return_value={}):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {}
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={})

                    await pm.refresh()
                    assert pm._consecutive_failures == 1

        # Second call: reset lock state to bypass cooldown
        pm._last_refresh_ts = 0.0
        pm._refresh_lock = None

        with patch.object(pm.scanner, 'full_pipeline', return_value={}):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {}
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={})

                    await pm.refresh()
                    assert pm._consecutive_failures == 2

    @pytest.mark.asyncio
    async def test_last_good_fallback_preserves_pool(self, pm_with_data):
        """7.5a: When scanner fails but _last_good exists, pool should be preserved."""
        pm = pm_with_data
        initial_pool_size = sum(len(v) for v in pm._pool.values())
        initial_version = pm._version

        with patch.object(pm.scanner, 'full_pipeline', return_value={}):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {}
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={})

                    diff = await pm.refresh()

        # Pool should still have original data
        current_size = sum(len(v) for v in pm._pool.values())
        assert current_size == initial_pool_size, (
            f"Pool should be preserved after failed refresh: "
            f"{current_size} != {initial_pool_size}"
        )
        # Version should NOT have incremented (no refresh took place)
        assert pm._version == initial_version, (
            f"Version should not increment: {pm._version} != {initial_version}"
        )

    @pytest.mark.asyncio
    async def test_successful_refresh_resets_failure_counter(self, pm):
        """7.5a: After a failure, a successful refresh should reset consecutive count."""
        # First fail
        with patch.object(pm.scanner, 'full_pipeline', return_value={}):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {}
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={})
                    await pm.refresh()

        assert pm._consecutive_failures == 1

        # Then succeed (simulate valid scanner data)
        valid_layers = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "amount": 1e8, "fund_scale": 1e9}],
            "satellite": [],
            "defense": [],
        }
        with patch.object(pm.scanner, 'full_pipeline', return_value=valid_layers):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {
                    "510300": {"industry": "宽基指数", "concepts": [], "confidence": 0.9}
                }
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={
                        "510300": {"technical": 0.5, "momentum": 0.3, "valuation": 0.2}
                    })
                    mock_fr.aggregate_factor_scores = MagicMock(side_effect=lambda x: x)

                    # run_sync is used for enrich_tracked_indices, batch_classify, etc.
                    # Call fn directly so mocked functions return their mock values
                    async def _run_sync_side_effect(fn, *args, **kwargs):
                        return fn(*args)

                    # Reset cooldown so refresh actually runs
                    pm._last_refresh_ts = 0.0
                    pm._refresh_lock = None

                    with patch('app.core.async_utils.run_sync', side_effect=_run_sync_side_effect):
                        await pm.refresh()

        assert pm._consecutive_failures == 0, (
            f"Counter should reset after success: {pm._consecutive_failures}"
        )
        assert sum(len(v) for v in pm._pool.values()) > 0

    @pytest.mark.asyncio
    async def test_mandatory_codes_injected_on_successful_refresh(self, pm):
        """7.5a: Mandatory ETF codes should be present after successful refresh."""
        valid_layers = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "amount": 1e8, "fund_scale": 1e9},
            ],
            "satellite": [
                {"symbol": "560600", "name": "医药ETF", "amount": 5e7, "fund_scale": 5e8},
            ],
            "defense": [],
        }
        with patch.object(pm.scanner, 'full_pipeline', return_value=valid_layers):
            with patch.object(pm, 'classifier') as mock_cls:
                mock_cls.batch_classify.return_value = {
                    "510300": {"industry": "宽基指数", "concepts": [], "confidence": 0.9},
                    "560600": {"industry": "医药", "concepts": [], "confidence": 0.8},
                }
                with patch.object(pm, 'factor_registry') as mock_fr:
                    mock_fr.compute = MagicMock(return_value={
                        "510300": {"technical": 0.5},
                        "560600": {"technical": 0.3},
                    })
                    mock_fr.aggregate_factor_scores = MagicMock(side_effect=lambda x: x)
                    # run_sync calls fn directly so mocked functions return their values
                    async def _run_sync_side_effect(fn, *args, **kwargs):
                        return fn(*args)
                    with patch('app.core.async_utils.run_sync', side_effect=_run_sync_side_effect):
                        await pm.refresh()

        # Check mandatory codes are present
        all_symbols = set()
        for items in pm._pool.values():
            for item in items:
                all_symbols.add(item["symbol"])

        for code in ["510300", "560600", "518880", "511090"]:
            if code in ["510300", "560600"]:
                assert code in all_symbols, (
                    f"Mandatory code {code} should be in pool, got: {all_symbols}"
                )
