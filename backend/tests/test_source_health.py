"""TDD tests for P2: active health probe for data sources.

All source calls are mocked; no network needed.
"""
from unittest.mock import patch, MagicMock
import pytest

from app.services.source_health import register_probe, run_probes, _PROBES


def setup_method():
    _PROBES.clear()


def test_register_probe_adds_entry():
    """register_probe adds a (name, fn, timeout) tuple."""
    _PROBES.clear()
    register_probe("test_source", lambda: True, timeout=3)
    assert len(_PROBES) == 1
    assert _PROBES[0][0] == "test_source"
    assert _PROBES[0][2] == 3


def test_run_probes_records_success():
    """run_probes records success when probe function returns truthy."""
    _PROBES.clear()
    register_probe("good_source", lambda: ["data"], timeout=3)

    with patch("app.services.source_health.registry") as mock_reg:
        import time
        # Override time.time to get a predictable value
        with patch("app.services.source_health.time.time", return_value=100.0):
            import asyncio
            asyncio.run(run_probes())

    mock_reg._health.assert_called_once_with("good_source")
    mock_reg._health.return_value.record_success.assert_called_once()


def test_run_probes_records_failure_on_empty_result():
    """run_probes records failure when probe returns falsy."""
    _PROBES.clear()
    register_probe("bad_source", lambda: [], timeout=3)

    with patch("app.services.source_health.registry") as mock_reg:
        with patch("app.services.source_health.time.time", return_value=100.0):
            import asyncio
            asyncio.run(run_probes())

    mock_reg._health.return_value.record_failure.assert_called_once_with(100.0)


def test_run_probes_records_failure_on_exception():
    """run_probes records failure when probe raises."""
    _PROBES.clear()

    def failing():
        raise ConnectionError("timeout")

    register_probe("broken_source", failing, timeout=3)

    with patch("app.services.source_health.registry") as mock_reg:
        with patch("app.services.source_health.time.time", return_value=100.0):
            import asyncio
            asyncio.run(run_probes())

    mock_reg._health.return_value.record_failure.assert_called_once_with(100.0)


def test_run_probes_handles_multiple_sources():
    """run_probes handles multiple sources independently."""
    _PROBES.clear()
    register_probe("src_a", lambda: ["ok"], timeout=3)
    register_probe("src_b", lambda: [], timeout=3)  # empty = failure

    with patch("app.services.source_health.registry") as mock_reg:
        with patch("app.services.source_health.time.time", return_value=100.0):
            import asyncio
            asyncio.run(run_probes())

    # src_a should succeed, src_b should fail
    calls = mock_reg._health.call_args_list
    assert len(calls) == 2

    def _name(call):
        return call[0][0]

    names = [_name(c) for c in calls]
    assert "src_a" in names
    assert "src_b" in names
