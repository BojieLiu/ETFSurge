from __future__ import annotations
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

    def setup_method(self):
        # 清除 /factors/active 的 60s 模块级缓存：串行跑时前序测试（如本文件折叠来的
        # TestFactorsActive 在 patch._computers 为 2 项时调用该端点并缓存 total=2）会污染
        #缓存，导致本类断言命中旧响应。与 test_sentiment_factors.py:85 同源处理。
        from app.routers import factors as factors_router
        factors_router._CACHE.clear()

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

    def test_avg_ic_is_abs_mean(self):
        """T10 (round23): summary.avg_ic == mean(|ic_value|)（绝对值均值，非带符号均值）。

        旧实现全局/分类两处带符号均值 → 同屏两个相差 5× 的「平均|IC|」（F26/F25-④）。
        负值 IC 因子（如 ATR=-0.39）会暴露带符号均值低估：abs 均值 ≥ 带符号均值。
        """
        resp = client.get("/api/v1/factors/active")
        body = resp.json()
        s = body["summary"]
        vals = [f["ic_value"] for cat in body["categories"] for f in cat["factors"]
                if f["status"] != "static" and f["ic_value"] is not None]
        if not vals:
            assert s["avg_ic"] is None
            return
        calc = round(sum(abs(v) for v in vals) / len(vals), 4)
        assert s["avg_ic"] == calc, f"avg_ic={s['avg_ic']} 应为 mean(|ic|)={calc}"


# ===== folded from test_round14_apply_design_factors.py =====
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch
from app.routers import factors as factors_router
from app.routers.portfolio import apply_design
from app.services.portfolio_service import apply_portfolio_design
class TestFactorMinSampleProtection:
    """F25②: 显著性判据（交易日 + t/IR）替换旧「样本 ≥30 + |IC|≥阈值」。"""

    def test_low_samples_no_downlisting(self):
        """样本 0 但 |IC|=0.45 → no_data（未累积/常量无差异），不是 warn。"""
        with patch.object(factors_router.registry, "_last_ic_batch", {"technical.ma.sma_5": -0.45}):
            with patch.object(factors_router.registry, "_sample_counts", {"technical.ma.sma_5": 0}):
                status, reason = factors_router._status_of(
                    "technical.ma.sma_5", samples=0, t_stat=None, ir=None, ic_val=-0.45)
        assert status == "no_data", f"样本不足应 no_data（实际 {status}）"
        # 文案可为「未累积」或「常量无差异」（取决于全局 registry 的 constant 记录状态）
        assert any(k in reason for k in ("未累积", "常量", "无差异", "未接入")), reason

    def test_enough_samples_significant_valid(self):
        """F25②: 260 交易日 + t≥2 + |IR|≥0.5 → valid（含负向显著）；t<2 → warn。"""
        with patch.object(factors_router.registry, "_sample_counts", {"technical.ma.sma_5": 260}):
            status_neg, _ = factors_router._status_of(
                "technical.ma.sma_5", samples=260, t_stat=2.4, ir=-0.6, ic_val=-0.45)
            status_pos, _ = factors_router._status_of(
                "technical.ma.sma_5", samples=260, t_stat=2.4, ir=0.6, ic_val=0.45)
            status_weak, _ = factors_router._status_of(
                "technical.ma.sma_5", samples=260, t_stat=1.2, ir=0.3, ic_val=0.45)
        # F25②: |IR|≥0.5 且 t≥2 → valid（负向显著 = 预测方向与收益反向，仍统计显著）；
        # t<2 → warn（有样本但统计不显著）
        assert status_neg == "valid"
        assert status_pos == "valid"
        assert status_weak == "warn"

    def test_min_trading_days_constant(self):
        """F25②: 有效门槛 250 交易日 / 可观察下限 60。"""
        assert factors_router.MIN_TRADING_DAYS == 250
        assert factors_router.MIN_OBSERVABLE_DAYS == 60
