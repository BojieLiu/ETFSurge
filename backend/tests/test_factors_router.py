"""
Tests for GET /api/v1/factors/active endpoint.

Validates against the contract defined in api-contracts/factors/active.md.
All external calls are mocked; the test uses FastAPI TestClient directly.
"""
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestActiveFactorsEndpoint:
    """Contract tests for GET /api/v1/factors/active."""

    def test_status_and_top_level_fields(self):
        """Response has 200 + required top-level fields: total, categories, summary, updated_at."""
        resp = client.get("/api/v1/factors/active")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert isinstance(body["total"], int)
        assert "categories" in body
        assert isinstance(body["categories"], list)
        assert "summary" in body
        assert "updated_at" in body

    def test_total_matches_computer_count(self):
        """total equals len(registry._computers) — the number of active compute functions."""
        from app.factors.factor_registry import registry
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        assert body["total"] == len(registry._computers)

    def test_summary_fields(self):
        """summary contains valid, warn, no_data, avg_ic with correct types."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        s = body["summary"]
        assert "valid" in s
        assert "warn" in s
        assert "no_data" in s
        assert "avg_ic" in s
        assert isinstance(s["valid"], int)
        assert isinstance(s["warn"], int)
        assert isinstance(s["no_data"], int)
        assert s["avg_ic"] is None or isinstance(s["avg_ic"], float)

    def test_summary_counts_total(self):
        """valid + warn + no_data + static == total（Z03: 静态因子单独计数）。"""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        s = body["summary"]
        assert s["valid"] + s["warn"] + s["no_data"] + s["static"] == body["total"]

    def test_category_structure(self):
        """Each category has required fields: name, count, factors, valid_count, warn_count, no_data_count."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        for cat in body["categories"]:
            assert "name" in cat
            assert isinstance(cat["name"], str)
            assert "count" in cat
            assert cat["count"] == len(cat["factors"])
            assert "valid_count" in cat
            assert "warn_count" in cat
            assert "no_data_count" in cat
            assert "description" in cat
            assert isinstance(cat["description"], str)

    def test_factor_fields(self):
        """Each factor entry has: code, name, subcategory, description, standardization, ic_threshold, ic_value."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        for cat in body["categories"]:
            for f in cat["factors"]:
                assert "code" in f
                assert isinstance(f["code"], str)
                assert "name" in f
                assert isinstance(f["name"], str)
                assert "subcategory" in f
                assert isinstance(f["subcategory"], str)
                assert "description" in f
                assert isinstance(f["description"], str)
                assert "standardization" in f
                assert isinstance(f["standardization"], str)
                assert "ic_threshold" in f
                assert isinstance(f["ic_threshold"], (int, float))
                assert "ic_value" in f
                assert f["ic_value"] is None or isinstance(f["ic_value"], (int, float))

    def test_ic_value_nullable(self):
        """ic_value can be None (not yet computed)."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        has_null = any(
            f["ic_value"] is None
            for cat in body["categories"]
            for f in cat["factors"]
        )
        # We don't assert has_null because it depends on runtime state,
        # but we verify the field type permits None.
        all_types_valid = all(
            f["ic_value"] is None or isinstance(f["ic_value"], (int, float))
            for cat in body["categories"]
            for f in cat["factors"]
        )
        assert all_types_valid

    def test_category_counts_aggregate(self):
        """Category-level valid+warn+no_data+static == count（Z03: static 单独计数）。"""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        for cat in body["categories"]:
            assert cat["valid_count"] + cat["warn_count"] + cat["no_data_count"] + cat["static_count"] == cat["count"]

    def test_summary_totals_match_category_sums(self):
        """Global summary valid/warn/no_data match sum of category values."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        s = body["summary"]
        cat_valid = sum(c["valid_count"] for c in body["categories"])
        cat_warn = sum(c["warn_count"] for c in body["categories"])
        cat_no_data = sum(c["no_data_count"] for c in body["categories"])
        assert s["valid"] == cat_valid
        assert s["warn"] == cat_warn
        assert s["no_data"] == cat_no_data

    def test_categories_sorted(self):
        """Categories are returned in alphabetical order."""
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        names = [c["name"] for c in body["categories"]]
        assert names == sorted(names)
