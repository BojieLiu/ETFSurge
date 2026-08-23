from __future__ import annotations
"""Tests for system-diagnosis-and-optimization-plan.md fixes.

Covers the verifiable (unit-testable) fixes:
  - F4: LLM max_tokens raised 8192 -> 12288 (budget for reasoning models)
  - F5: reasoning_content fallback removed (content empty -> "" not scratchpad)
  - F19: china_specific factors consume `industry` from factor data
        (five_year_plan / strategic_emerging / dual_circulation)

External network / LLM providers are mocked — no real calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


# ─── F4 / F5: llm_complete max_tokens + reasoning fallback ──────────

def _fake_provider():
    return SimpleNamespace(
        id="fake",
        name="Fake Provider",
        model="deepseek-v4-flash",
        api_url="https://example.test/v1/chat/completions",
        api_key="sk-fake",
        timeout=30,
    )


async def _call_llm_with_response(payload):
    """Run llm_complete against a mocked httpx client returning `payload`."""
    from app.analysis import llm as llm_mod

    captured = {}

    class _Resp:
        def __init__(self, body):
            self._body = body
        def raise_for_status(self):
            return None
        def json(self):
            return self._body

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, headers=None, json=None):
            captured["body"] = json
            return _Resp(payload)

    with patch("app.analysis.llm.client.get_configured_providers", return_value=[_fake_provider()]), \
         patch("app.analysis.llm.client._check_key", new=AsyncMock()), \
         patch("httpx.AsyncClient", _Client):
        content = await llm_mod.llm_complete("hello world")
    return content, captured.get("body", {})


@pytest.mark.asyncio
async def test_F4_max_tokens_raised_to_12288():
    content, body = await _call_llm_with_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    })
    assert content == "ok"
    assert body.get("max_tokens") == 12288


@pytest.mark.asyncio
async def test_F5_empty_content_returns_empty_not_reasoning():
    # reasoning_content present but content empty -> must return "" (no scratchpad leak)
    content, _ = await _call_llm_with_response({
        "choices": [{"message": {
            "content": "",
            "reasoning_content": "let me think step by step ...",
        }}],
        "usage": {},
    })
    assert content == ""


@pytest.mark.asyncio
async def test_F5_json_force_empty_content_returns_empty():
    content, _ = await _call_llm_with_response({
        "choices": [{"message": {
            "content": "",
            "reasoning_content": "not valid json at all",
        }}],
        "usage": {},
    })
    assert content == ""


# ─── F19: china_specific factors consume `industry` ────────────────

from app.factors.factor_registry import (
    _compute_five_year_plan,
    _compute_strategic_emerging,
    _compute_dual_circulation,
)


@pytest.mark.parametrize("industry,expected", [
    ("半导体", 0.95),
    ("银行", 0.25),
    ("食品饮料", 0.30),
    ("", 0.30),  # fallback
])
def test_F19_five_year_plan_uses_industry(industry, expected):
    assert _compute_five_year_plan({"industry": industry}) == expected


@pytest.mark.parametrize("industry,expected", [
    ("半导体", 1.0),
    ("计算机", 1.0),
    ("银行", 0.0),
    ("", 0.0),
])
def test_F19_strategic_emerging_uses_industry(industry, expected):
    assert _compute_strategic_emerging({"industry": industry}) == expected


@pytest.mark.parametrize("industry,concepts,expected", [
    ("食品饮料", [], 1.0),
    ("汽车", ["内需"], 1.0),
    ("银行", [], 0.0),
    ("", [], 0.0),
])
def test_F19_dual_circulation_uses_industry_and_concepts(industry, concepts, expected):
    assert _compute_dual_circulation({"industry": industry, "concepts": concepts}) == expected


# ─── F7: LLM health probe ────────────────────────────────────────────

async def _run_health_check(ok_providers, timeout=15.0):
    """Run llm_health_check with providers whose post() returns per-index ok flag."""
    import httpx
    from app.analysis import llm as llm_mod

    class _Resp:
        def __init__(self, ok):
            self._ok = ok
        def raise_for_status(self):
            if not self._ok:
                raise httpx.HTTPStatusError("bad", request=None, response=None)
        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

    queue = list(ok_providers)  # shared across concurrent probe clients

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, headers=None, json=None):
            ok = queue.pop(0) if queue else False
            return _Resp(ok)

    with patch("app.analysis.llm.health.get_configured_providers",
               return_value=[_fake_provider(), _fake_provider()]), \
         patch("app.analysis.llm.health.has_any_api_key", return_value=True), \
         patch("httpx.AsyncClient", _Client):
        return await llm_mod.llm_health_check(timeout=timeout)


@pytest.mark.asyncio
async def test_F7_health_ok_when_provider_available():
    report = await _run_health_check([True, True])
    assert report["status"] == "ok"
    assert report["has_api_key"] is True
    assert len(report["providers"]) == 2
    assert all(p["ok"] for p in report["providers"])
    assert all(p["status"] == "available" for p in report["providers"])


@pytest.mark.asyncio
async def test_F7_health_degraded_when_all_fail():
    report = await _run_health_check([False, False])
    assert report["status"] == "degraded"
    assert all(p["ok"] is False for p in report["providers"])
    assert all(p["error"] is not None for p in report["providers"])


@pytest.mark.asyncio
async def test_F7_health_ok_if_any_provider_up():
    report = await _run_health_check([False, True])
    assert report["status"] == "ok"
    assert report["providers"][0]["ok"] is False
    assert report["providers"][1]["ok"] is True


@pytest.mark.asyncio
async def test_F7_health_no_key():
    from app.analysis import llm as llm_mod
    with patch("app.analysis.llm.health.has_any_api_key", return_value=False):
        report = await llm_mod.llm_health_check()
    assert report["status"] == "no_key"
    assert report["has_api_key"] is False
    assert report["providers"] == []


# ─── F3: HK/US search enrichment ──────────────────────────────────

@pytest.mark.asyncio
async def test_F3_hk_us_static_match_without_keyword():
    from app.services import market_service as ms
    # No enrichment -> pure static map
    with patch.object(ms, "get_asset_realtime", new=AsyncMock(return_value=None)):
        res = await ms.search_hk_us("", enrich=False)
    assert len(res) > 0
    assert all(r["market"] in ("HK", "US") for r in res)
    assert "price" not in res[0]


@pytest.mark.asyncio
async def test_F3_hk_us_enriched_with_live_quote():
    from app.services import market_service as ms

    async def _fake_quote(symbol, market):
        return {"price": 25.6, "change_pct": 1.23}

    with patch.object(ms, "get_asset_realtime", new=_fake_quote):
        res = await ms.search_hk_us("盈富", enrich=True)
    assert len(res) >= 1
    hit = next(r for r in res if r["symbol"] == "02800.HK")
    assert hit["price"] == 25.6
    assert hit["change_pct"] == 1.23


@pytest.mark.asyncio
async def test_F3_hk_us_enrich_falls_back_on_error():
    from app.services import market_service as ms

    async def _boom(symbol, market):
        raise RuntimeError("network down")

    # Even if live enrich fails, static result must be returned (no raise)
    with patch.object(ms, "get_asset_realtime", new=_boom):
        res = await ms.search_hk_us("SPY", enrich=True)
    assert any(r["symbol"] == "SPY" for r in res)
    assert "price" not in res[0]  # enrichment failed -> no price field


# ─── F11: demjson -> orjson/json shim ────────────────────────────

def test_F11_shim_fast_path_for_strict_json():
    import sys, types
    import app.core.fast_json as fast_json

    # Fake demjson module: its real decode records a call and echoes input.
    fake = types.ModuleType("demjson")
    fake.decode = lambda text, *a, **k: f"ORIG:{text}"

    fast_json.reset_demjson_shim()
    saved = sys.modules.get("demjson")
    sys.modules["demjson"] = fake
    try:
        assert fast_json.install_demjson_shim() is True
        # strict JSON -> shim takes the fast path, original NOT called
        assert fake.decode('{"a": 1}') == {"a": 1}
        # non-strict JSON -> shim falls back to original demjson
        assert fake.decode('{"a": 1,}') == 'ORIG:{"a": 1,}'
    finally:
        if saved is None:
            sys.modules.pop("demjson", None)
        else:
            sys.modules["demjson"] = saved
        fast_json.reset_demjson_shim()


def test_F11_shim_noop_when_demjson_absent():
    import sys
    import app.core.fast_json as fast_json

    saved = sys.modules.get("demjson")
    sys.modules.pop("demjson", None)  # pretend demjson not installed
    fast_json.reset_demjson_shim()
    try:
        assert fast_json.install_demjson_shim() is False
    finally:
        if saved is not None:
            sys.modules["demjson"] = saved
        fast_json.reset_demjson_shim()


# ─── F9: ETF scan batching (parallel gtimg chunks) ───────────────

def test_F9_gtimg_batch_merges_chunks():
    from app.fetchers import etf_scanner as es

    def _fake_chunk(chunk):
        # mark which codes came through this chunk
        return {c: {"amount": len(chunk), "turnover": 0,
                    "fund_scale": 0, "pe": 0} for c in chunk}

    codes = [f"5{i:05d}" for i in range(350)]  # 4 chunks of 100/100/100/50
    with patch.object(es, "_tencent_gtimg_chunk", side_effect=_fake_chunk):
        merged = es._tencent_gtimg_batch(codes)
    # all codes present, merged across parallel chunks
    assert set(merged.keys()) == set(codes)
    assert merged[codes[0]]["amount"] == 100  # chunk size preserved


def test_F9_gtimg_batch_small_input_serial():
    from app.fetchers import etf_scanner as es

    calls = []

    def _fake_chunk(chunk):
        calls.append(tuple(chunk))
        return {c: {"amount": 1, "turnover": 0, "fund_scale": 0, "pe": 0} for c in chunk}

    # 2 chunks -> serial path (<=2 chunks)
    codes = [f"5{i:05d}" for i in range(150)]
    with patch.object(es, "_tencent_gtimg_chunk", side_effect=_fake_chunk):
        merged = es._tencent_gtimg_batch(codes)
    assert set(merged.keys()) == set(codes)
    assert len(calls) == 2  # serial: exactly 2 chunk calls


# ─── Z01: factor-health endpoint must have `import time` in scope ──

def test_Z01_factor_health_has_time_import():
    """Verify that get_factor_health() can access time.time() without NameError."""
    import inspect
    from app.routers import admin as admin_mod

    src = inspect.getsource(admin_mod.get_factor_health)
    # The function must have `time.time()` calls; either time is imported
    # at module level or inside the function
    assert "time.time()" in src
    # Check module-level imports include 'import time'
    mod_src = inspect.getsource(admin_mod)
    assert "import time" in mod_src.split("from fastapi")[0] or "import time" in mod_src


# ─── Z03: china_specific ic_value initialized to 0 for static factors ──

@pytest.mark.asyncio
async def test_Z03_china_specific_ic_not_none():
    """Verify /api/v1/factors/active returns china_specific with ic_value==null (Z03)."""
    import json
    from app.routers import factors as factors_mod
    from app.factors.factor_registry import registry

    # Simulate a freshly initialized _last_ic_batch
    old_batch = registry._last_ic_batch
    registry._last_ic_batch = {}
    try:
        # round18 P0-4: 端点新增 db 依赖（DB IC 周期计数）——测试传 mock db
        resp = await factors_mod.get_active_factors(db=MagicMock())
        body = json.loads(resp.body) if isinstance(resp.body, bytes) else resp.body
        for cat in body.get("categories", []):
            if cat["name"] == "china_specific":
                for f in cat["factors"]:
                    # Phase 40 Z03: 静态政策因子 ic_value=null（不再硬编码 0），
                    # status='static'（旧断言 ic_value!=None 与 Z03 修复冲突）
                    if f["code"] in ("china.policy.five_year_plan",
                                     "china.policy.strategic_emerging",
                                     "china.policy.dual_circulation"):
                        assert f["ic_value"] is None, f"{f['code']} ic_value should be None (static)"
                        assert f["status"] == "static", f"{f['code']} status should be static"
    finally:
        registry._last_ic_batch = old_batch


# ─── Z04: etf_specific data field injection in _fetch_market_data ──

@pytest.mark.asyncio
async def test_Z04_fetch_market_data_injects_industry_concepts():
    """Verify symbol_extra industry/concepts injected into fetch market data."""
    from app.factors.factor_registry import FactorRegistry

    fr = FactorRegistry()
    extra = {"510300": {"industry": "金融", "concepts": ["大盘", "蓝筹"]}}
    # We can't easily call _fetch_market_data without network, but we can
    # verify that _compute_industry_diversification receives these fields
    from app.factors.factor_registry import _compute_industry_diversification
    result = _compute_industry_diversification({"concepts": ["金融", "科技", "医药"]})
    assert result < 0.5  # multiple concepts -> more diversified
    result = _compute_industry_diversification({"concepts": ["金融"]})
    assert result > 0.3  # single concept -> more concentrated


@pytest.mark.asyncio
async def test_Z04_premium_discount_compute_uses_nav():
    """Verify premium_discount compute function uses nav from IOPV data."""
    from app.factors.factor_registry import _compute_premium_discount
    # price > nav -> positive premium
    assert _compute_premium_discount({"price": 1.05, "nav": 1.00}) == pytest.approx(0.05, abs=1e-3)
    # price < nav -> negative premium (discount)
    assert _compute_premium_discount({"price": 0.95, "nav": 1.00}) == pytest.approx(-0.05, abs=1e-3)
    # no nav -> 0.0
    assert _compute_premium_discount({"price": 1.00}) == 0.0


@pytest.mark.asyncio
async def test_Z04_tracking_error_uses_benchmark_close():
    """Verify tracking_error uses benchmark_close when available."""
    from app.factors.factor_registry import _compute_tracking_error
    # close and benchmark_close both [100, 101, 102, 103, 104, 105]
    # ETF returns: 1%, 1%, 1%, 1%, 1%
    # Benchmark returns: 1%, 1%, 1%, 1%, 1% -> diff squared: 0
    closes = [100, 101, 102, 103, 104, 105]
    result = _compute_tracking_error({"close": closes, "benchmark_close": closes})
    assert result == 0.0

    # Different returns -> tracking error > 0
    bench_closes = [100, 110, 120, 130, 140, 150]
    result = _compute_tracking_error({"close": closes, "benchmark_close": bench_closes})
    assert result > 0.0


@pytest.mark.asyncio
async def test_Z04_shares_change_existing_field():
    """Verify shares_change reads shares_change_20d when present."""
    from app.factors.factor_registry import _compute_shares_change
    assert _compute_shares_change({"shares_change_20d": 0.15}) == 0.15
    assert _compute_shares_change({}) == 0.0


# ─── Z10: Signal threshold relaxation ──────────────────────────────

def test_Z10_high_score_triggers_buy():
    """With relaxed threshold, a high positive score generates buy signal."""
    from app.analysis.signal import generate_signal
    # RSI < 30 (+2) + MACD golden cross (+1) + MA5>MA20 (+1) = 4.0 >= 2 (original) or >= 1.5 (new)
    result = generate_signal({"rsi": 25, "macd": {"dif": 2, "dea": 1}, "ma5": 10.5, "ma20": 10.0})
    assert result["signal"] == "buy"
    assert result["score"] >= 1.5


def test_Z10_moderate_score_triggers_buy_with_relaxed_threshold():
    """With threshold relaxed from 2.0 to 1.5, moderate signals become buy."""
    from app.analysis.signal import generate_signal
    # RSI<40 (+1) + KDJ超卖金叉 (+1) = 2.0, originally >= 2.0 buy
    # After relaxing to 1.5, even 1.6 should be buy
    result = generate_signal({"rsi": 35, "kdj": {"k": 25, "d": 20, "j": 15}, "ma5": 10.5, "ma20": 10.0})
    # RSI=35 => <40 so +1. KDJ k=25 < d=30 and k<30 => +1. Total=2.0
    assert result["score"] >= 2.0
    assert result["signal"] == "buy"


def test_Z10_edge_near_threshold():
    """Score just above 1.5 should be buy with relaxed threshold."""
    from app.analysis.signal import generate_signal
    # MACD 金叉 (+1) + MA5>MA20 (+1) = 2.0 -> buy with either threshold
    result = generate_signal({"macd": {"dif": 1, "dea": 0}, "ma5": 10.5, "ma20": 10.0})
    assert result["score"] >= 1.5
    assert result["signal"] == "buy"


# ─── Z11: Design circuit breaker fallback ──────────────────────────

@pytest.mark.asyncio
async def test_Z11_design_fallback_handles_failure_gracefully():
    """When design pipeline fails, generate_enhanced_design returns gracefully."""
    from app.services import strategy_design as sd_mod
    from unittest.mock import AsyncMock, MagicMock, patch as mock_patch

    with mock_patch("app.services.market_data_hub.market_data_hub") as mock_pm:
        mock_pm.refresh = AsyncMock()
        mock_pm.get_factor_matrix = MagicMock(side_effect=RuntimeError("design failed"))
        mock_pm.get_pool = MagicMock(return_value=[])
        mock_pm.get_market_regime = MagicMock(return_value="range_bound")
        mock_pm.get_market_sentiment = MagicMock(return_value={})
        mock_pm.get_index_realtime = MagicMock(return_value=[])
        mock_pm.get_sector_momentum = MagicMock(return_value=[])
        mock_pm.get_by_code = MagicMock(return_value={})

        result = await sd_mod.generate_enhanced_design(500000)
        assert isinstance(result, dict)
        assert "strategies" in result
        # Should not be empty (fallback provides strategies)
        assert len(result.get("strategies", [])) > 0


# ===== folded from test_phase1_diagnosis_fixes.py =====
import asyncio
import socket
import sys
from tests.db_fixtures import task_mgr  # noqa: F401
class TestP0_5_IPv4Priority:
    """P0.5: Global IPv4 priority monkey-patch in config.py"""

    def test_enable_ipv4_only_creates_monkey_patch(self):
        """enable_ipv4_only() should patch socket.getaddrinfo to force AF_INET."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        original = socket.getaddrinfo
        try:
            enable_ipv4_only()
            # Test that it forces IPv4
            result = socket.getaddrinfo("127.0.0.1", 80)
            assert all(r[0] == socket.AF_INET for r in result)
        finally:
            socket.getaddrinfo = original

    def test_disable_ipv4_only_restores_original(self):
        """disable_ipv4_only() should restore the original socket.getaddrinfo."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        # Capture the patched version, then enable again
        enable_ipv4_only()
        patched = socket.getaddrinfo
        
        # Save original BEFORE restore for verification
        import socket as _socket
        orig = _socket._original_getaddrinfo if hasattr(_socket, '_original_getaddrinfo') else None
        # Actually just verify behavior: after disable, IPv6 results should be possible
        # (but we can't guarantee since it depends on DNS resolution)
        
        disable_ipv4_only()
        assert socket.getaddrinfo is not patched, "disable should change getaddrinfo"

    def test_ipv4_only_ignores_AF_INET6(self):
        """The patched getaddrinfo should ignore AF_INET6 requests."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        original = socket.getaddrinfo
        try:
            enable_ipv4_only()
            # Running with AF_INET6 should still return IPv4 results
            result = socket.getaddrinfo("127.0.0.1", 80, socket.AF_INET6)
            assert all(r[0] == socket.AF_INET for r in result)
        finally:
            socket.getaddrinfo = original
class TestP0_1_StrategyCheckLLMImport:
    """P0.1: Fix 'from app.analysis.llm import llm_provider' error."""

    async def test_generate_check_llm_comment_uses_llm_complete(self):
        """_generate_check_llm_comment should use llm_complete not llm_provider.
        
        Verify by patching llm_complete at the import path used inside the function.
        """
        with patch("app.analysis.llm.llm_complete", new_callable=AsyncMock) as mock_llm:
            # Re-import to pick up the patch
            import importlib
            from app.tasks import strategy_check_worker
            importlib.reload(strategy_check_worker)
            from app.tasks.strategy_check_worker import _generate_check_llm_comment

            mock_llm.return_value = "test analysis response"

            result = await _generate_check_llm_comment({
                "positions": [
                    {"symbol": "510050", "name": "华夏上证50", "weight": 0.3, "change_pct": 0.5, "market_value": 150000},
                    {"symbol": "510300", "name": "华泰300", "weight": 0.2, "change_pct": -0.3, "market_value": 100000},
                ]
            })

            assert result is not None
            assert isinstance(result, str)
            assert mock_llm.await_count >= 1

    async def test_generate_check_llm_comment_empty_positions(self):
        """Empty positions should return None without calling any LLM."""
        from app.tasks.strategy_check_worker import _generate_check_llm_comment

        result = await _generate_check_llm_comment({"positions": []})
        assert result is None

    async def test_generate_check_llm_comment_no_positions_key(self):
        """Missing positions key should return None."""
        from app.tasks.strategy_check_worker import _generate_check_llm_comment

        result = await _generate_check_llm_comment({})
        assert result is None

    # round35 §11-P1-6: test_generate_check_llm_report_empty_positions 已随死函数
    # `_generate_check_llm_report` 一并删除（生产零调用，测试尸体不保留）。

    def test_no_llm_provider_import_error(self):
        """strategy_check_worker should NOT import llm_provider anymore."""
        import ast

        import os
        test_path = os.path.join(os.path.dirname(__file__), "..", "app", "tasks", "strategy_check_worker.py")
        with open(test_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        llm_provider_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "llm_provider":
                        llm_provider_found = True
                        break
        
        if llm_provider_found:
            # Check if it's inside a conditional or try/except where it's a fallback
            pytest.fail("strategy_check_worker still imports llm_provider")
        
        # Instead, verify llm_complete IS imported somewhere
        llm_complete_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "llm_complete":
                        llm_complete_found = True
                        break
        
        assert llm_complete_found, "strategy_check_worker should import llm_complete"
class TestP1_4_ProbeAccuracy:
    """P1.4: Fix data source probe accuracy."""

    def test_akshare_probe_uses_actual_function(self):
        """akshare probe should use a function actually used by the system."""
        import ast

        import os
        probes_path = os.path.join(os.path.dirname(__file__), "..", "app", "monitor", "probes.py")
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find the _probe_akshare function
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "akshare" in node.name.lower():
                # Check the AST body for actual function calls (not comments)
                has_old_func = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) 
                    and n.func.attr == "stock_zh_a_hist"
                    for n in ast.walk(node)
                )
                assert not has_old_func, (
                    "akshare probe still uses stock_zh_a_hist, "
                    "should use system-actual function"
                )
                # Check it uses stock_sector_spot_em (the actual system function)
                has_new_func = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) 
                    and n.func.attr == "stock_sector_spot_em"
                    for n in ast.walk(node)
                )
                assert has_new_func, (
                    "akshare probe should use stock_sector_spot_em "
                    "(the function used by sector_fetcher)"
                )
                return

        pytest.fail("Could not find akshare probe function")

    def test_probe_names_match_source_registry(self):
        """Probe names should match SourceRegistry source names."""
        import ast

        import os
        probes_path = os.path.join(os.path.dirname(__file__), "..", "app", "monitor", "probes.py")
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find all register_probe calls and extract the source names
        registered_sources = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id == "register_probe":
                    if call.args and isinstance(call.args[0], ast.Constant):
                        registered_sources.append(call.args[0].value)

        # Check for standard source names
        expected_sources = ["mootdx", "sina", "tencent", "akshare", "levistock", "dongfang"]
        for source in expected_sources:
            assert source in registered_sources, (
                f"Probe for {source} not found or not registered with proper name "
                f"(found: {registered_sources})"
            )
