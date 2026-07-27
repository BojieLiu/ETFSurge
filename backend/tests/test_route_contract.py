"""
test_route_contract.py — Tests for API Route Contract Verification (方案 C1)

Tests the compare_routes logic and contract parsing without needing a running backend.
Uses synthetic route lists to verify mismatch detection.
"""
import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from check_routes import compare_routes, _parse_contract_method, load_expected_routes


# ── _parse_contract_method ──────────────────────────────────────


class TestParseContractMethod:
    def test_get_with_path(self):
        result = _parse_contract_method("GET /health")
        assert result == ("GET", "/health")

    def test_post_with_path(self):
        result = _parse_contract_method("POST /api/v1/portfolio/calculate")
        assert result == ("POST", "/api/v1/portfolio/calculate")

    def test_put_with_path(self):
        result = _parse_contract_method("PUT /api/v1/portfolio/etfs/{symbol}")
        assert result == ("PUT", "/api/v1/portfolio/etfs/{symbol}")

    def test_delete_with_path(self):
        result = _parse_contract_method("DELETE /api/v1/portfolio/etfs/{symbol}")
        assert result == ("DELETE", "/api/v1/portfolio/etfs/{symbol}")

    def test_patch_with_path(self):
        result = _parse_contract_method("PATCH /api/v1/portfolio/etfs/{symbol}")
        assert result == ("PATCH", "/api/v1/portfolio/etfs/{symbol}")

    def test_indented_line(self):
        result = _parse_contract_method("  GET /api/v1/market/realtime")
        assert result == ("GET", "/api/v1/market/realtime")

    def test_not_a_route(self):
        assert _parse_contract_method("## 目录") is None
        assert _parse_contract_method("") is None
        assert _parse_contract_method("| GET /health | ok |") is None


# ── load_expected_routes ────────────────────────────────────────


class TestLoadExpectedRoutes:
    def test_load_from_temp_dir(self):
        """Should parse routes from markdown files in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory structure
            os.makedirs(os.path.join(tmpdir, "market"))
            os.makedirs(os.path.join(tmpdir, "portfolio"))

            # Write contract files
            with open(os.path.join(tmpdir, "market", "realtime.md"), "w", encoding="utf-8") as f:
                f.write("# Market Realtime\n\nGET /api/v1/market/realtime\n")
                f.write("GET /api/v1/market/indices/global\n")
            with open(os.path.join(tmpdir, "portfolio", "calculate.md"), "w", encoding="utf-8") as f:
                f.write("# Portfolio Calculate\n\nPOST /api/v1/portfolio/calculate\n")

            expected = load_expected_routes(tmpdir)
            expected_set = set(expected)

            assert ("GET", "/api/v1/market/realtime") in expected_set
            assert ("GET", "/api/v1/market/indices/global") in expected_set
            assert ("POST", "/api/v1/portfolio/calculate") in expected_set
            assert len(expected) == 3


# ── compare_routes ──────────────────────────────────────────────


class TestCompareRoutes:
    def test_exact_match(self):
        actual = [("GET", "/health"), ("GET", "/api/v1/market/realtime")]
        expected = [("GET", "/health"), ("GET", "/api/v1/market/realtime")]
        issues = compare_routes(actual, expected)
        assert len(issues) == 0

    def test_missing_from_contract(self):
        actual = [("GET", "/health"), ("GET", "/api/v1/market/realtime")]
        expected = [("GET", "/health")]
        issues = compare_routes(actual, expected)
        assert len(issues) == 1
        assert issues[0]["type"] == "missing_from_contract"
        assert "/api/v1/market/realtime" in issues[0]["path"]

    def test_not_found_in_app(self):
        actual = [("GET", "/health")]
        expected = [("GET", "/health"), ("GET", "/api/v1/market/realtime")]
        issues = compare_routes(actual, expected)
        assert len(issues) == 1
        assert issues[0]["type"] == "not_found_in_app"
        assert "/api/v1/market/realtime" in issues[0]["path"]

    def test_both_mismatches(self):
        actual = [("GET", "/health"), ("GET", "/api/v1/news")]
        expected = [("GET", "/health"), ("GET", "/api/v1/admin")]
        issues = compare_routes(actual, expected)
        assert len(issues) == 2
        types = {i["type"] for i in issues}
        assert "missing_from_contract" in types
        assert "not_found_in_app" in types

    def test_duplicate_routes(self):
        """Duplicate entries should be deduplicated via set."""
        actual = [("GET", "/health"), ("GET", "/health")]
        expected = [("GET", "/health")]
        issues = compare_routes(actual, expected)
        assert len(issues) == 0

    def test_empty_lists(self):
        assert compare_routes([], []) == []
        assert len(compare_routes([("GET", "/test")], [])) == 1
        assert len(compare_routes([], [("GET", "/test")])) == 1
