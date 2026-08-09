"""TDD tests for timeout & cancellation resilience fixes.

All external calls (mootdx, akshare, feedparser) are mocked;
no network needed.

Key regression scenarios:
  - Thread pool not exhausted after consecutive timeouts (P0 fix)
  - Per-call executor doesn't leak threads
"""
import concurrent.futures
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.core.async_utils import run_sync
from app.services.market_service import _call


# ── Fix 3: _call catches CancelledError ──────────────────────────


async def test_call_returns_none_on_cancelled_error():
    """_call must return None when CancelledError escapes run_sync.

    In Python 3.8+ CancelledError inherits from BaseException,
    not Exception — a bare ``except Exception`` would miss it.
    """
    with patch("app.services.market_service.run_sync",
               side_effect=asyncio.CancelledError()):
        result = await _call(lambda: None)
    assert result is None


async def test_call_returns_none_on_timeout():
    """_call must return None when run_sync raises TimeoutError."""
    with patch("app.services.market_service.run_sync",
               side_effect=asyncio.TimeoutError()):
        result = await _call(lambda: None)
    assert result is None


async def test_call_passthrough_on_success():
    """_call must return the normal result on success."""
    result = await _call(lambda: 42)
    assert result == 42


# ── Fix 2: _MOOTDX_LOCK non-blocking acquire ────────────────────


# ── Fix 4: _ak() timeout wrapping ────────────────────────────────

def _make_future(result=None, exc=None, delay=0):
    """Helper: create a Future that resolves with result or raises exc."""
    f = concurrent.futures.Future()
    if exc:
        f.set_exception(exc)
    else:
        f.set_result(result)
    return f


def test_ak_returns_empty_on_run_in_thread_timeout(monkeypatch):
    """_ak() must return [] when the dedicated executor times out.

    _ak() uses _akshare_executor.submit() with timeout;
    a TimeoutError must produce [].
    """
    from app.fetchers.news_fetcher import _ak
    import app.fetchers.news_fetcher as nfmod

    # Simulate a future that never completes within the timeout
    slow_future = concurrent.futures.Future()
    monkeypatch.setattr(
        nfmod._akshare_executor, "submit",
        lambda fn: slow_future,
    )

    assert _ak(lambda ak: [{"title": "test"}]) == []
    # Clean up: resolve the hanging future so the executor doesn't leak
    slow_future.set_result(None)


def test_ak_returns_data_on_success(monkeypatch):
    """_ak() must return akshare data when the executor succeeds."""
    from app.fetchers.news_fetcher import _ak
    import app.fetchers.news_fetcher as nfmod

    fake_data = [{"title": "news", "content": "body"}]
    monkeypatch.setattr(
        nfmod._akshare_executor, "submit",
        lambda fn: _make_future(result=fake_data),
    )

    assert _ak(lambda ak: fake_data) == fake_data


def test_ak_calls_run_in_thread_with_timeout(monkeypatch):
    """_ak() must respect its timeout parameter."""
    from app.fetchers.news_fetcher import _ak
    import app.fetchers.news_fetcher as nfmod

    # Override timeout to a short value, then submit a slow future
    slow_future = concurrent.futures.Future()
    monkeypatch.setattr(nfmod, "_AK_TIMEOUT", 0.1)
    monkeypatch.setattr(
        nfmod._akshare_executor, "submit",
        lambda fn: slow_future,
    )

    result = _ak(lambda ak: [], timeout=0.1)
    assert result == []
    slow_future.set_result(None)


# ── Fix 5: _ak() sequential timeout bounding ─────────────────────


def test_ak_sequential_timeouts_return_empty(monkeypatch):
    """Multiple slow _ak() calls must each return [] on timeout."""
    from app.fetchers.news_fetcher import _ak
    import app.fetchers.news_fetcher as nfmod

    # All submits return the same hanging future
    slow_future = concurrent.futures.Future()
    monkeypatch.setattr(nfmod, "_AK_TIMEOUT", 0.05)
    monkeypatch.setattr(
        nfmod._akshare_executor, "submit",
        lambda fn: slow_future,
    )

    for i in range(5):
        assert _ak(lambda ak: [{}]) == [], f"iteration {i} should return []"

    slow_future.set_result(None)


# ── async_utils: run_sync timeout behavior ──────────────────────


async def test_run_sync_timeout_raises_timeout_error():
    """run_sync must raise asyncio.TimeoutError when fn exceeds timeout."""
    def _slow():
        import time
        time.sleep(10)

    start = asyncio.get_event_loop().time()
    with pytest.raises(asyncio.TimeoutError):
        await run_sync(_slow, timeout=0.5)
    elapsed = asyncio.get_event_loop().time() - start
    # Should return near the timeout, not the full 10 s
    assert elapsed < 5, f"run_sync blocked for {elapsed:.1f}s instead of timing out"


# ── P0: run_in_thread thread exhaustion ──────────────────────────


def test_run_in_thread_returns_none_on_timeout():
    """run_in_thread must return None when the function exceeds timeout.

    Critical: must NOT leak threads or exhaust the shared executor.
    """
    from app.core.async_utils import run_in_thread

    def _very_slow():
        import time
        time.sleep(100)

    result = run_in_thread(_very_slow, timeout=0.3)
    assert result is None


def test_run_in_thread_still_usable_after_consecutive_timeouts():
    """After N consecutive timeouts, run_in_thread must still work.

    Regression guard: per-call executor (P0 fix) must not leak threads.
    """
    from app.core.async_utils import run_in_thread

    def _very_slow():
        import time
        time.sleep(100)

    def _fast():
        return 42

    # 10 consecutive timeouts
    for i in range(10):
        r = run_in_thread(_very_slow, timeout=0.2)
        assert r is None, f"iteration {i} should timeout"

    # After 10 timeouts, a normal call must still succeed
    result = run_in_thread(_fast, timeout=2)
    assert result == 42, f"Expected 42, got {result}"
