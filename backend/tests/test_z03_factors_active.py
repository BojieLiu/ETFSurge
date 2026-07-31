"""Test Z03: /factors/active exposure of status/sample_count/reason.

Covers:
1. china_specific static factors -> status='static', ic_value=None (not 0), reason, sample_count=0
2. computed factors -> status valid/warn/no_data with reason + sample_count
3. static factors excluded from summary valid/warn/no_data counts
4. ic_threshold=0 for static factors
5. last_computed_at present for computed factors, None for static
"""
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport


class TestFactorsActive:
    """Z03: /factors/active response enrichment."""

    def _make_fake_definition(self, code, category, standardization="zscore",
                              ic_threshold=0.02, name="F"):
        from app.factors.factor_registry import FactorDefinition
        return FactorDefinition(
            code=code, name=name, category=category, subcategory="",
            standardization=standardization, ic_threshold=ic_threshold,
        )

    @pytest.mark.asyncio
    async def test_static_factors_status_and_ic_null(self):
        """china_specific static factors: status='static', ic_value=None, threshold=0."""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        static_codes = [
            "china.policy.five_year_plan",
            "china.policy.strategic_emerging",
            "china.policy.dual_circulation",
        ]
        # Fake registry state
        fake_computers = {c: (lambda x: 0.0) for c in static_codes}
        fake_factors = {
            c: self._make_fake_definition(c, "china_specific") for c in static_codes
        }
        # IC batch intentionally lacks static codes (they have no IC)
        fake_ic_batch = {"technical.ma.sma_5": 0.0321}

        factors_router._CACHE.clear()
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", fake_ic_batch), \
             patch.object(registry, "_sample_counts", {}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors()
            data = body.body if hasattr(body, "body") else body

        import json
        if isinstance(data, bytes):
            data = json.loads(data)

        china_cat = next(c for c in data["categories"] if c["name"] == "china_specific")
        factors = china_cat["factors"]
        assert len(factors) == 3
        for f in factors:
            assert f["status"] == "static"
            assert f["ic_value"] is None, f"{f['code']} ic_value should be None not 0"
            assert f["ic_threshold"] == 0
            assert f["sample_count"] == 0
            assert f["last_computed_at"] is None
            assert "静态" in f["reason"]

        # Static factors not counted in summary
        assert data["summary"]["valid"] == 0
        assert data["summary"]["warn"] == 0
        assert data["summary"]["no_data"] == 0

    @pytest.mark.asyncio
    async def test_computed_factor_statuses(self):
        """valid/warn/no_data statuses with reason + sample_count."""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        codes = ["technical.ma.sma_5", "technical.ma.sma_10", "style.size.ln_cap"]
        fake_computers = {c: (lambda x: 0.0) for c in codes}
        fake_factors = {
            c: self._make_fake_definition(c, c.split(".")[0], ic_threshold=0.02) for c in codes
        }
        fake_ic_batch = {
            "technical.ma.sma_5": 0.0321,   # valid (>= 0.02)
            "technical.ma.sma_10": 0.001,   # warn (< 0.02)
            # style.size.ln_cap missing -> no_data
        }
        fake_sample_counts = {
            "technical.ma.sma_5": 240,
            "technical.ma.sma_10": 240,
        }

        factors_router._CACHE.clear()
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", fake_ic_batch), \
             patch.object(registry, "_sample_counts", fake_sample_counts), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors()
            data = body.body if hasattr(body, "body") else body

        import json
        if isinstance(data, bytes):
            data = json.loads(data)

        flat = {}
        for cat in data["categories"]:
            for f in cat["factors"]:
                flat[f["code"]] = f

        assert flat["technical.ma.sma_5"]["status"] == "valid"
        assert flat["technical.ma.sma_5"]["sample_count"] == 240
        assert flat["technical.ma.sma_5"]["ic_value"] == 0.0321
        assert flat["technical.ma.sma_5"]["last_computed_at"] == "2026-07-31T15:00:00Z"
        assert "≥" in flat["technical.ma.sma_5"]["reason"] or "阈值" in flat["technical.ma.sma_5"]["reason"]

        assert flat["technical.ma.sma_10"]["status"] == "warn"
        assert "阈值" in flat["technical.ma.sma_10"]["reason"]

        assert flat["style.size.ln_cap"]["status"] == "no_data"
        assert flat["style.size.ln_cap"]["ic_value"] is None
        assert flat["style.size.ln_cap"]["sample_count"] == 0

        # Summary counts
        assert data["summary"]["valid"] == 1
        assert data["summary"]["warn"] == 1
        assert data["summary"]["no_data"] == 1

    @pytest.mark.asyncio
    async def test_active_endpoint_http_contract(self):
        """HTTP contract: /api/v1/factors/active has all Z03 fields."""
        from app.main import app
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        codes = ["technical.ma.sma_5", "china.policy.five_year_plan"]
        fake_computers = {c: (lambda x: 0.0) for c in codes}
        fake_factors = {
            codes[0]: self._make_fake_definition(codes[0], "technical", ic_threshold=0.02, name="SMA 5"),
            codes[1]: self._make_fake_definition(codes[1], "china_specific", name="五年计划"),
        }
        factors_router._CACHE.clear()
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", {"technical.ma.sma_5": 0.0321}), \
             patch.object(registry, "_sample_counts", {"technical.ma.sma_5": 240}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/factors/active")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["summary"] is not None
        flat = {}
        for cat in data["categories"]:
            for f in cat["factors"]:
                flat[f["code"]] = f
        # Z03 fields present on every factor
        for f in flat.values():
            for field in ("status", "reason", "sample_count", "last_computed_at", "ic_value"):
                assert field in f, f"missing field {field} in {f['code']}"
        # Static factor excluded from summary
        assert data["summary"]["no_data"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])