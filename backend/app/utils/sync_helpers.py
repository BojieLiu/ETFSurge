"""Bridge module: sync helpers for thread-pool calls.

This module provides run_sync_in_thread() used by strategy_design.py
to call I/O-bound functions without blocking the event loop.
"""

from app.core.async_utils import run_in_thread

def run_sync_in_thread(fn, *args, **kwargs):
    """Run a synchronous function in a per-call thread pool with timeout."""
    return run_in_thread(fn, *args, **kwargs, executor="long")
