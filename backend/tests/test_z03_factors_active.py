"""Test Z03: /factors/active exposure of status/sample_count/reason.

Covers:
1. china_specific static factors -> status='static', ic_value=None (not 0), reason, sample_count=0
2. computed factors -> status valid/warn/no_data with reason + sample_count
3. static factors excluded from summary valid/warn/no_data counts
4. ic_threshold=0 for static factors
5. last_computed_at present for computed factors, None for static
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
            body = await factors_router.get_active_factors(db=MagicMock())
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
        """F25②: valid/warn/no_data 分档——samples≥250 且 t≥2 且 |IR|≥0.5 → valid；
        样本不足 → no_data（积累中）；t/IR 不显著 → warn。"""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        codes = ["technical.ma.sma_5", "technical.ma.sma_10", "style.size.ln_cap"]
        fake_computers = {c: (lambda x: 0.0) for c in codes}
        fake_factors = {
            c: self._make_fake_definition(c, c.split(".")[0], ic_threshold=0.02) for c in codes
        }
        fake_ic_batch = {
            "technical.ma.sma_5": 0.0321,   # 250+ 天 + 显著 → valid
            "technical.ma.sma_10": 0.001,   # 250+ 天但不显著（t<2）→ warn
            # style.size.ln_cap missing -> no_data
        }
        fake_sample_counts = {
            "technical.ma.sma_5": 250,
            "technical.ma.sma_10": 250,
        }
        fake_series_stats = {
            "technical.ma.sma_5": {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 2.3},
            "technical.ma.sma_10": {"ic_mean": 0.001, "ic_std": 0.05, "ir": 0.02, "t_stat": 0.3},
        }

        factors_router._CACHE.clear()
        mock_db = MagicMock()
        factors_router._db_ic_sample_counts = AsyncMock(return_value=fake_sample_counts)
        factors_router._db_ic_series_stats = AsyncMock(return_value=fake_series_stats)
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", fake_ic_batch), \
             patch.object(registry, "_sample_counts", fake_sample_counts), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors(db=mock_db)
            data = body.body if hasattr(body, "body") else body

        import json
        if isinstance(data, bytes):
            data = json.loads(data)

        flat = {}
        for cat in data["categories"]:
            for f in cat["factors"]:
                flat[f["code"]] = f

        # F25②: 250 天 + t≥2 + |IR|≥0.5 → valid（统计显著）
        assert flat["technical.ma.sma_5"]["status"] == "valid"
        assert flat["technical.ma.sma_5"]["sample_count"] == 250
        assert flat["technical.ma.sma_5"]["ic_value"] == 0.0321
        assert flat["technical.ma.sma_5"]["last_computed_at"] == "2026-07-31T15:00:00Z"
        assert flat["technical.ma.sma_5"]["t_stat"] == 2.3
        assert flat["technical.ma.sma_5"]["ir"] == 0.64
        assert "统计显著" in flat["technical.ma.sma_5"]["reason"]

        # F25②: 250 天但 t<2 → warn（有样本但统计不显著）
        assert flat["technical.ma.sma_10"]["status"] == "warn"
        assert "不显著" in flat["technical.ma.sma_10"]["reason"]

        assert flat["style.size.ln_cap"]["status"] == "no_data"
        assert flat["style.size.ln_cap"]["ic_value"] is None
        assert flat["style.size.ln_cap"]["sample_count"] == 0

        # Summary counts
        assert data["summary"]["valid"] == 1
        assert data["summary"]["warn"] == 1
        assert data["summary"]["no_data"] == 1
        # F25②④/F32: summary 门槛与分档
        assert data["summary"]["min_samples"] == 250
        assert data["summary"]["observable_days"] == 60
        assert data["summary"]["significant"] == 1

    @pytest.mark.asyncio
    async def test_active_endpoint_http_contract(self):
        """HTTP contract: /api/v1/factors/active has all Z03 + F25 fields."""
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
        # F25②: HTTP 契约测试经 FastAPI DI 注入真实 get_db——mock DB 序列统计，
        # 避免依赖本地 dev DB 的 factor_ic_records 迁移状态（隔离外部状态）
        factors_router._db_ic_sample_counts = AsyncMock(return_value={"technical.ma.sma_5": 250})
        factors_router._db_ic_series_stats = AsyncMock(return_value={
            "technical.ma.sma_5": {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 2.3},
        })
        with patch.object(registry, "_computers", fake_computers), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", {"technical.ma.sma_5": 0.0321}), \
             patch.object(registry, "_sample_counts", {"technical.ma.sma_5": 250}), \
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
            for field in ("status", "reason", "sample_count", "last_computed_at", "ic_value",
                          "ic_mean", "ic_std", "ir", "t_stat"):
                assert field in f, f"missing field {field} in {f['code']}"
        # sma_5: 250 天 + 显著 → valid；static 因子不计入 summary
        assert flat["technical.ma.sma_5"]["status"] == "valid"
        assert data["summary"]["valid"] == 1
        assert data["summary"]["no_data"] == 0
        assert data["summary"]["min_samples"] == 250  # F32


if __name__ == "__main__":
    pytest.main([__file__, "-v"])