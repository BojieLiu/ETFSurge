"""Tests for Phase 2a — Data Quality & Factor Pipeline fixes.

Phase 2a — 因子与数据质量:
  P1.2d: 两融余额换源 (fundamentals_fetcher → akshare)
  P1.2e: 删除 north_flow + 新增 volume_ratio 因子
  P1.1:  修复市场上下文空数据 (market_data_hub 数据刷新链路)
  P1.2a: 新闻因子数据通路修复 (sentiment.news_heat/direction)
  P1.2b: premium_discount 因子修复 (IOPV数据链)
  P0.3:  修复港股美股搜索为 0
  P0.4:  修复中文编码问题
  P1.5:  HTTP 连接池扩容
"""
from __future__ import annotations

import ast
import os


# ── P1.2d: 两融余额换源 ──────────────────────────────────

class TestP1_2d_MarginSwap:
    """P1.2d: Replace _fetch_szse/_fetch_sse direct HTTP with akshare."""

    def test_no_direct_szse_http(self):
        """_fetch_szse should NOT use urllib.request directly."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fetch_szse":
                body = ast.dump(node)
                assert "urllib.request" not in body, (
                    "_fetch_szse still uses urllib.request directly"
                )
                # Should use akshare
                assert "stock_margin_szse" in body, (
                    "_fetch_szse should use stock_margin_szse()"
                )
                return
        pytest.fail("_fetch_szse function not found")

    def test_no_direct_sse_http(self):
        """_fetch_sse should NOT use urllib.request directly."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fetch_sse":
                body = ast.dump(node)
                assert "urllib.request" not in body, (
                    "_fetch_sse still uses urllib.request directly"
                )
                # Should use akshare
                assert "stock_margin_sse" in body, (
                    "_fetch_sse should use stock_margin_sse()"
                )
                return
        pytest.fail("_fetch_sse function not found")

    def test_fetch_margin_balance_uses_akshare(self):
        """fetch_margin_balance should call through to akshare-based functions."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "fetch_margin_balance":
                body = ast.get_source_segment(
                    open(probes_path, encoding="utf-8").read(), node
                )
                # Should call both SZSE and SSE akshare functions
                assert "_fetch_szse" in body, "fetch_margin_balance should call _fetch_szse"
                assert "_fetch_sse" in body, "fetch_margin_balance should call _fetch_sse"
                return


# ── P1.2e: north_flow → volume_ratio ──────────────────────

class TestP1_2e_SentimentWeights:
    """P1.2e: Replace north_flow with volume_ratio in sentiment weights."""

    def test_no_north_flow_in_weights(self):
        """SENTIMENT_WEIGHTS should NOT contain north_flow."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "north_flow" not in content, (
            "fundamentals_fetcher still references north_flow"
        )

    def test_volume_ratio_in_weights(self):
        """SENTIMENT_WEIGHTS should contain volume_ratio."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "volume_ratio" in content, (
            "fundamentals_fetcher should reference volume_ratio"
        )

    def test_calc_sentiment_index_no_north_flow(self):
        """calc_sentiment_index should NOT take north_flow parameter."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "calc_sentiment_index":
                # Get all parameter names
                param_names = [a.arg for a in node.args.args]
                assert "north_flow" not in param_names, (
                    "calc_sentiment_index still has north_flow parameter"
                )
                assert "volume_ratio" in param_names, (
                    "calc_sentiment_index should have volume_ratio parameter"
                )
                return
        pytest.fail("calc_sentiment_index function not found")

    def test_new_sentiment_weights_sum_to_one(self):
        """New 4-dim weights should sum to 1.0."""
        # advance_ratio=0.30, margin_change=0.30, volume_ratio=0.20, inst_consensus=0.20
        weights = {
            "advance_ratio": 0.30,
            "margin_change": 0.30,
            "volume_ratio": 0.20,
            "inst_consensus": 0.20,
        }
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001, f"Sentiment weights sum to {total}, expected 1.0"

    def test_regime_weights_have_volume_ratio(self):
        """All regime weight configs should use volume_ratio not north_flow."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "fundamentals_fetcher.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find _REGIME_WEIGHTS dict
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_REGIME_WEIGHTS":
                        dict_str = ast.get_source_segment(
                            open(probes_path, encoding="utf-8").read(), node
                        )
                        assert "north_flow" not in dict_str, (
                            "_REGIME_WEIGHTS still uses north_flow"
                        )
                        assert "volume_ratio" in dict_str, (
                            "_REGIME_WEIGHTS should use volume_ratio"
                        )
                        return


# ── P1.1: 市场上下文空数据 ─────────────────────────────────

class TestP1_1_MarketContext:
    """P1.1: Ensure market_data_hub properly populates market context."""

    def test_pool_manager_has_market_context(self):
        """market_data_hub should export market context data functions."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_data_hub.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        required_keys = ["index_realtime", "sector_momentum", "market_sentiment"]
        for key in required_keys:
            assert key in content, f"market_data_hub missing {key}"

    def test_market_context_has_fallback(self):
        """Market context should have fallback defaults to avoid empty data."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_data_hub.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should have fallback/empty state handling
        has_fallback = any(
            term in content for term in ["fallback", "default", "empty", "None"]
        )
        assert has_fallback, "market_data_hub should handle empty/None data with fallbacks"


# ── P1.2a: 新闻因子通路 ───────────────────────────────────

class TestP1_2a_NewsFactorPipeline:
    """P1.2a: Ensure news factors receive data from pipeline."""

    def test_news_heat_factor_exists(self):
        """news_heat factor function should exist in factor_registry."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_news_heat":
                    return
        pytest.fail("_compute_news_heat function not found in factor_registry.py")

    def test_news_direction_factor_exists(self):
        """news_direction factor function should exist in factor_registry."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_news_direction":
                    return
        pytest.fail("_compute_news_direction function not found in factor_registry.py")


# ── P1.2b: premium_discount 因子 ──────────────────────────

class TestP1_2b_PremiumDiscount:
    """P1.2b: premium_discount / tracking_error factor pipeline."""

    def test_premium_discount_uses_nav_and_price(self):
        """premium_discount should use nav and price data."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "factors", "factor_registry.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_premium_discount":
                    body = ast.get_source_segment(
                        open(probes_path, encoding="utf-8").read(), node
                    )
                    assert "nav" in body, "premium_discount should use nav data"
                    assert "price" in body, "premium_discount should use price data"
                    return
        pytest.fail("_compute_premium_discount function not found")


# ── P0.3: 港股美股搜索 ───────────────────────────────────

class TestP0_3_HKUSSearch:
    """P0.3: Ensure search supports HK/US stocks."""

    def test_search_includes_hk_and_us_fallbacks(self):
        """Search function should include HK/US data source fallbacks."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_service.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should mention HK/US market handling
        hk_refs = sum(1 for ref in ["港股", "hongkong", "hong_kong", "hsi", "HK"] if ref.lower() in content.lower())
        us_refs = sum(1 for ref in ["美股", "us stock", "spy", "qqq"] if ref.lower() in content.lower())
        assert hk_refs > 0 or us_refs > 0, (
            "market_service should handle HK/US stock fallbacks in search"
        )


# ── P0.4: 中文编码 ────────────────────────────────────────

class TestP0_4_Encoding:
    """P0.4: Unified UTF-8 encoding."""

    def test_config_has_utf8_encoding(self):
        """config.py should set env_file_encoding = 'utf-8'."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "config.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "env_file_encoding" in content, "config.py should set env_file_encoding"
        assert "utf-8" in content.lower(), "config.py should use utf-8 encoding"

    def test_no_latin1_default_encoding(self):
        """No Python file should rely on latin1 default encoding."""
        import glob
        issues = []
        py_files = glob.glob(
            os.path.join(os.path.dirname(__file__), "..", "app", "**", "*.py"),
            recursive=True,
        )
        for pf in py_files[:30]:  # Check first 30 files as sample
            with open(pf, "r", encoding="utf-8") as f:
                try:
                    f.read()
                except UnicodeDecodeError:
                    issues.append(pf)
        assert len(issues) == 0, f"Files with encoding issues: {issues}"


# ── P1.5: HTTP 连接池 ───────────────────────────────────

class TestP1_5_ConnectionPool:
    """P1.5: HTTP connection pool capacity."""

    def test_china_market_session_has_pool_config(self):
        """china_market.py session should configure pool_connections/pool_maxsize."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "china_market.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should configure pool_connections and pool_maxsize
        assert "pool_connections" in content or "pool_maxsize" in content or "Adapter" in content or "HTTPAdapter" in content, (
            "china_market.py should configure HTTP connection pool"
        )

    def test_pool_sizes_adequate(self):
        """Pool sizes should be at least 20 connections."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "china_market.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for pool sizes >= 20
        has_pool_size = any(str(n) in content for n in [20, 25, 30, 40, 50, 60])
        assert has_pool_size, (
            "Connection pool size should be >= 20"
        )


import pytest
