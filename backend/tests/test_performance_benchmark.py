"""
Performance benchmark test (7.5c): API response time gates.

Tests that critical API endpoints respond within acceptable time bounds
when the backend is running. These are NOT CI-enforced (require backend),
but provide a manual benchmark baseline.

Measured endpoints and their gates:
  - /health: < 3s (cold start includes warmup)
  - /portfolio/etfs: < 1s
  - /portfolio/designs: < 2s
  - /factors/active: < 1s
  - /admin/metrics: < 2s
"""
import time
import urllib.request
import urllib.error
import json
import pytest

BASE = "http://127.0.0.1:8000"


def _fetch(path: str, timeout: int = 10) -> tuple[int, float, bytes]:
    """GET a path, return (status_code, elapsed_secs, body)."""
    url = f"{BASE}{path}"
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            elapsed = time.time() - t0
            return resp.status, elapsed, resp.read()
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        return e.code, elapsed, e.read()
    except Exception as e:
        elapsed = time.time() - t0
        return 0, elapsed, str(e).encode()


# ── Health ──────────────────────────────────────────────────


@pytest.mark.skip(reason="Requires running backend on port 8000")
class TestHealthBenchmark:
    def test_health_response_time(self):
        """/health should respond in < 3s."""
        status, elapsed, _body = _fetch("/health")
        assert status == 200, f"/health returned {status}"
        assert elapsed < 3.0, f"/health took {elapsed:.2f}s (gate=3.0s)"


# ── Portfolio ───────────────────────────────────────────────


@pytest.mark.skip(reason="Requires running backend on port 8000")
class TestPortfolioBenchmark:
    def test_etfs_response_time(self):
        """/portfolio/etfs should respond in < 1s (cached)."""
        status, elapsed, _body = _fetch("/api/v1/portfolio/etfs")
        assert status == 200, f"/portfolio/etfs returned {status}"
        assert elapsed < 1.0, f"/portfolio/etfs took {elapsed:.2f}s (gate=1.0s)"

    def test_designs_list_response_time(self):
        """/portfolio/designs should respond in < 2s."""
        status, elapsed, _body = _fetch("/api/v1/portfolio/designs?limit=5")
        assert status == 200, f"/portfolio/designs returned {status}"
        assert elapsed < 2.0, f"/portfolio/designs took {elapsed:.2f}s (gate=2.0s)"


# ── Factors ─────────────────────────────────────────────────


@pytest.mark.skip(reason="Requires running backend on port 8000")
class TestFactorsBenchmark:
    def test_active_factors_response_time(self):
        """/factors/active should respond in < 1s."""
        status, elapsed, _body = _fetch("/api/v1/factors/active")
        assert status == 200, f"/factors/active returned {status}"
        assert elapsed < 1.0, f"/factors/active took {elapsed:.2f}s (gate=1.0s)"


# ── Admin ───────────────────────────────────────────────────


@pytest.mark.skip(reason="Requires running backend on port 8000")
class TestAdminBenchmark:
    def test_metrics_response_time(self):
        """/admin/metrics should respond in < 2s."""
        status, elapsed, _body = _fetch("/api/v1/admin/metrics")
        assert status == 200, f"/admin/metrics returned {status}"
        assert elapsed < 2.0, f"/admin/metrics took {elapsed:.2f}s (gate=2.0s)"

    def test_metrics_contains_pool_health(self):
        """/admin/metrics should report pool health."""
        status, _elapsed, body = _fetch("/api/v1/admin/metrics")
        assert status == 200
        data = json.loads(body)
        assert "pool" in data, f"Missing 'pool' in metrics: {list(data.keys())}"
        assert "healthy" in data["pool"], f"Missing 'healthy' in pool metrics"
        assert "consecutive_refresh_failures" in data["pool"]
        assert "designs" in data
        assert "success_rate" in data["designs"]
