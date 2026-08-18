"""Late-bound cross-cluster references for the portfolio package (Batch 1).

Sub-modules resolve cross-cluster dependencies through the facade module
``app.services.portfolio_service`` **at call time** instead of binding them
directly at import time. This preserves the mock semantics that tests rely on:

    patch("app.services.portfolio_service.list_etfs", ...)

replaces the facade module attribute, and every proxy call site reads that
attribute when invoked — exactly as it did when all functions lived in one
module. Import-time binding would freeze the original object into the caller's
module globals and silently break every ``patch`` in the test suite.

This indirection is temporary: it is removed in Batch 5 (Step 3) when consumers
migrate to the new sub-module paths and tests are updated to patch those paths.
"""

import sys


def _facade():
    """Return the facade module, importing it lazily on first access."""
    m = sys.modules.get("app.services.portfolio_service")
    if m is None:
        from app.services import portfolio_service as m
        sys.modules["app.services.portfolio_service"] = m
    return m


def _mk(name):
    def _proxy(*args, **kwargs):
        return getattr(_facade(), name)(*args, **kwargs)

    _proxy.__name__ = name
    _proxy.__qualname__ = name
    _proxy.__module__ = __name__
    return _proxy


# cross-cluster function dependencies
list_etfs = _mk("list_etfs")
build_price_map = _mk("build_price_map")
calculate_allocation = _mk("calculate_allocation")
recompute_cost_after_trade = _mk("recompute_cost_after_trade")
_fetch_realtime_price = _mk("_fetch_realtime_price")
format_factor_summary = _mk("format_factor_summary")
_normalize_confidence = _mk("_normalize_confidence")
_compute_confidence = _mk("_compute_confidence")
