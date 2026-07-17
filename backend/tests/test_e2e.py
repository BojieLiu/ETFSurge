"""End-to-end test: portfolio-design through Vite proxy.

Skips gracefully if no dev server is running on port 5173.
"""
import urllib.request
import json
import socket

import pytest

API_URL = "http://localhost:5173/api/v1/analysis/portfolio-design"
CHECK_TIMEOUT = 3  # quick check before real request


def _server_running(host="localhost", port=5173):
    """Quick TCP connectivity check — 2 seconds max."""
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        return True
    except (OSError, socket.error):
        return False


@pytest.mark.skipif(not _server_running(), reason="Frontend dev server not running on localhost:5173")
class TestPortfolioDesignE2E:

    @pytest.fixture
    def design_result(self):
        """POST to portfolio-design endpoint, cache response."""
        req = urllib.request.Request(
            API_URL,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data

    def test_status_ok(self, design_result):
        assert "portfolios" in design_result, f"Missing 'portfolios' key: {list(design_result.keys())}"

    def test_returns_three_portfolios(self, design_result):
        portfolios = design_result["portfolios"]
        assert isinstance(portfolios, list)
        assert len(portfolios) == 3, f"Expected 3 portfolios, got {len(portfolios)}"

    def test_portfolio_types(self, design_result):
        types = {pf["type"] for pf in design_result["portfolios"]}
        assert types == {"defensive", "balanced", "aggressive"}, f"Unexpected types: {types}"

    def test_weights_sum_to_one(self, design_result):
        for pf in design_result["portfolios"]:
            etf_w = sum(e["weight"] for e in pf["etfs"])
            cash_w = pf.get("cash_weight", 0) or 0
            total = round(etf_w + cash_w, 10)
            assert abs(total - 1.0) < 0.01, (
                f'{pf["type"]}: ETF weights={etf_w:.4f} cash={cash_w:.4f} total={total:.4f} (not 1.0)'
            )

    def test_each_portfolio_has_etfs(self, design_result):
        for pf in design_result["portfolios"]:
            assert len(pf["etfs"]) >= 8, f'{pf["type"]}: only {len(pf["etfs"])} ETFs (expected >=8)'
            assert len(pf["etfs"]) <= 15, f'{pf["type"]}: {len(pf["etfs"])} ETFs (expected <=15)'

    def test_core_has_510300(self, design_result):
        """每个方案核心层必须包含沪深300 ETF."""
        for pf in design_result["portfolios"]:
            core = [e for e in pf["etfs"] if e.get("layer") == "core"]
            core_codes = {e["symbol"] for e in core}
            assert "510300" in core_codes, f'{pf["type"]} missing 510300 in core'

    def test_fixed_defense(self, design_result):
        """每个方案防御层必须包含黄金ETF."""
        for pf in design_result["portfolios"]:
            defense = [e for e in pf["etfs"] if e.get("layer") == "defense"]
            defense_codes = {e["symbol"] for e in defense}
            assert "518880" in defense_codes, f'{pf["type"]} missing 518880 in defense'

    def test_v3_strategies_differ(self, design_result):
        """三个方案卫星层权重应不同（防御型最低，进攻型最高）."""
        portfolios = design_result["portfolios"]
        sat_weights = []
        for pf in portfolios:
            sat_w = sum(e["weight"] for e in pf["etfs"] if e.get("layer") == "satellite")
            sat_weights.append(sat_w)
        # defensive < balanced < aggressive
        assert sat_weights[0] < sat_weights[2], (
            f"Expected defensive satellite < aggressive satellite: {sat_weights}"
        )
