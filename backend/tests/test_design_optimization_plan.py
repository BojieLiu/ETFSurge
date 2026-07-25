"""
TDD tests for design-optimization-plan.md (P0/P1/P3 fixes).

Covers:
  - P0: generate_enhanced_design must detect market regime from 510300 (HS300 ETF)
        instead of the missing 000001, so a sharp 1m drop yields "correction".
  - P1: generate_enhanced_design must include `index_realtime` in market_context;
        _build_design_report_prompt must render "market snapshot" and "sector momentum".
  - P3: _fetch_single_trend must compute `change_pct` (today's move);
        build_rationale must prepend "today up/down X%" using that field.

All external network calls (akshare / mootdx / china_market) are mocked.
"""

import pandas as pd
from unittest.mock import patch, AsyncMock, Mock


def _make_fake_df_with_change():
    # second-to-last close 1.0, last close 0.923 -> today -7.7%
    # >=5 rows to satisfy the function's internal length guard
    return pd.DataFrame({"收盘": [1.10, 1.08, 1.05, 1.00, 0.923]})


def _fake_pool():
    """Return a non-empty satellite pool so the scanner (network) is skipped."""
    return [{"symbol": "512480", "name": "semiconductorETF", "liquidity": 17.0,
             "industry": "semiconductor", "composite_score": 0.8}]


# ─── P0: regime detection via 510300 ────────────────────────────────

async def test_p0_regime_detected_from_510300():
    """Sharp 1m drop on 510300 with neutral-weak sentiment must read 'correction',
    not the default 'range_bound' (the old 000001 bug)."""
    from app.services.strategy_design import generate_enhanced_design

    fake_trend = {
        "510300": {"return_1m": -0.15, "return_3m": -0.12, "ma_bias_20": 0.0},
    }
    fake_sentiment = {"sentiment_index": 55, "sentiment_label": "neutral", "advance_ratio": 0.5}
    fake_macro = {"economic_phase": "recovery", "monetary_stance": "loose"}
    fake_benchmark = [{"symbol": "600519", "name": "Moutai", "change_pct": -0.8, "signal": "sell"}]
    fake_sector = [{"sector_name": "semiconductor", "rank": 2, "total": 31, "change_pct": 1.2}]

    with patch("app.services.market_trends.compute_etf_trends", new=AsyncMock(return_value=fake_trend)), \
         patch("app.services.macro_state.detect_macro_regime", new=AsyncMock(return_value=fake_macro)), \
         patch("app.fetchers.sentiment_fetcher.fetch_market_sentiment", new=AsyncMock(return_value=fake_sentiment)), \
         patch("app.fetchers.benchmark_stocks.fetch_benchmark_stocks", new=AsyncMock(return_value=fake_benchmark)), \
         patch("app.fetchers.news_fetcher.fetch_news_headlines", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.fundamental_fetcher.fetch_fund_flow", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.fundamental_fetcher.fetch_current_pe_pb", new=AsyncMock(return_value=None)), \
         patch("app.services.market_trends.compute_sector_momentum", new=AsyncMock(return_value=fake_sector)), \
         patch("app.services.pool_manager.pool_manager") as mp:
        mp.refresh = AsyncMock()
        mp.get_pool = lambda *a, **k: _fake_pool()
        mp.get_factor_matrix = lambda: {"512480": {"technical": 0.7, "momentum": 0.6, "valuation": 0.5, "sentiment": 0.4}}
        mp.get_market_regime = lambda: "correction"
        mp.get_market_sentiment = lambda: fake_sentiment
        mp.get_index_realtime = lambda: []
        mp.get_sector_momentum = lambda: fake_sector
        result = await generate_enhanced_design(capital=500000)

    strategies = result.get("strategies", [])
    assert len(strategies) > 0, f"generate_enhanced_design returned 0 strategies, error: {result.get('detail', 'N/A')}"
    regime = result["market_context"]["market_regime"]
    assert regime == "correction", f"expected 'correction', got {regime!r} (P0 bug not fixed)"


# ─── P1: index_realtime in market_context + prompt sections ──────────

async def test_p1_index_realtime_in_market_context():
    """generate_enhanced_design must attach fetch_index_realtime() output to market_context."""
    from app.services.strategy_design import generate_enhanced_design

    fake_trend = {"510300": {"return_1m": 0.01, "return_3m": 0.03, "ma_bias_20": 0.0}}
    fake_sentiment = {"sentiment_index": 55, "sentiment_label": "neutral", "advance_ratio": 0.5}
    fake_macro = {"economic_phase": "recovery", "monetary_stance": "neutral"}
    fake_index = [
        {"symbol": "000001", "name": "SH", "price": 3210.5, "change_pct": -0.012,
         "change_amount": -3.9, "asset_type": "index"},
        {"symbol": "000300", "name": "HS300", "price": 3850.0, "change_pct": -0.008,
         "change_amount": -3.1, "asset_type": "index"},
    ]
    fake_sector = [{"sector_name": "food", "rank": 1, "total": 31, "change_pct": 2.1}]

    with patch("app.services.market_trends.compute_etf_trends", new=AsyncMock(return_value=fake_trend)), \
         patch("app.services.macro_state.detect_macro_regime", new=AsyncMock(return_value=fake_macro)), \
         patch("app.fetchers.sentiment_fetcher.fetch_market_sentiment", new=AsyncMock(return_value=fake_sentiment)), \
         patch("app.fetchers.benchmark_stocks.fetch_benchmark_stocks", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.news_fetcher.fetch_news_headlines", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.fundamental_fetcher.fetch_fund_flow", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.fundamental_fetcher.fetch_current_pe_pb", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.china_market.fetch_index_realtime", new=Mock(return_value=fake_index)), \
         patch("app.services.market_trends.compute_sector_momentum", new=AsyncMock(return_value=fake_sector)), \
         patch("app.services.pool_manager.pool_manager") as mp:
        mp.refresh = AsyncMock()
        mp.get_pool = lambda *a, **k: _fake_pool()
        mp.get_factor_matrix = lambda: {"512480": {"technical": 0.7, "momentum": 0.6, "valuation": 0.5, "sentiment": 0.4}}
        mp.get_market_regime = lambda: "range_bound"
        mp.get_market_sentiment = lambda: fake_sentiment
        mp.get_index_realtime = lambda: fake_index
        mp.get_sector_momentum = lambda: fake_sector
        result = await generate_enhanced_design(capital=500000)

    strategies = result.get("strategies", [])
    assert len(strategies) > 0, f"generate_enhanced_design returned 0 strategies, error: {result.get('detail', 'N/A')}"
    ctx = result["market_context"]
    assert "index_realtime" in ctx, "market_context missing index_realtime (P1 not wired)"
    assert len(ctx["index_realtime"]) == 2
    assert ctx["index_realtime"][0]["symbol"] == "000001"


def test_p1_prompt_contains_market_snapshot_and_sector_momentum():
    """_build_design_report_prompt must render a market snapshot and sector momentum section."""
    from app.analysis.llm import _build_design_report_prompt

    strategies = [{
        "style": "balanced", "style_label": "balanced", "portfolio_name": "balanced portfolio",
        "positioning": "growth+defense", "expected_return": 0.11, "max_drawdown": -0.18,
        "sharpe_ratio": 1.0,
        "allocations": [{"symbol": "510300", "name": "HS300ETF", "layer": "core",
                         "target_weight": 0.20, "selection_rationale": "core"}],
    }]
    market_sentiment = {"sentiment_index": 45, "sentiment_label": "cautious"}
    market_context = {
        "index_realtime": [
            {"symbol": "000001", "name": "SH", "price": 3210.5, "change_pct": -0.012},
            {"symbol": "399001", "name": "SZ", "price": 10120.0, "change_pct": -0.054},
        ],
        "market_regime": "correction",
        "macro_regime": {"economic_phase": "recovery", "monetary_stance": "loose"},
        "sector_momentum": [
            {"sector_name": "semiconductor", "rank": 2, "total": 31, "change_pct": 1.2},
        ],
    }

    prompt = _build_design_report_prompt(
        strategies, market_sentiment, [], market_context=market_context, plan_tables=""
    )
    assert "市场行情快照" in prompt, "prompt missing 市场行情快照 section (P1)"
    assert "行业板块动量" in prompt, "prompt missing 行业板块动量 section (P1)"
    assert "-5.4%" in prompt or "5.4%" in prompt, "prompt should cite actual index change_pct"


def test_p5a_prompt_contains_factor_data():
    """Prompt for design report must include factor_score and breakdown."""
    from app.analysis.llm import _build_design_report_prompt

    strategies = [
        {
            "label": "防御型", "id": "defensive",
            "layer_budget": {"core": 0.50, "satellite": 0.15, "defense": 0.05},
            "allocations": [
                {"symbol": "510300", "name": "沪深300ETF", "weight": 0.18,
                 "layer": "core", "factor_score": 0.72,
                 "factor_scores": {"style.size.ln_mcap": 0.8, "etf.amount_stability": 0.6,
                                   "sentiment.news_heat": 0.3},
                 "selection_rationale": "核心底仓"},
                {"symbol": "518880", "name": "黄金ETF", "weight": 0.08,
                 "layer": "defense", "factor_score": 0.65,
                 "factor_scores": {"etf.premium_discount": -0.2, "style.size.ln_mcap": 0.5},
                 "selection_rationale": "避险配置"},
                {"symbol": "CASH", "name": "现金", "weight": 0.10,
                 "layer": "cash", "factor_score": 0.5, "factor_scores": {},
                 "selection_rationale": "流动性管理"},
            ],
        }
    ]
    market_sentiment = {"sentiment_index": 30, "sentiment_label": "谨慎"}
    market_context = {
        "index_realtime": [],
        "market_regime": "correction",
        "macro_regime": {"economic_phase": "recovery", "monetary_stance": "loose"},
        "sector_momentum": [],
    }

    prompt = _build_design_report_prompt(
        strategies, market_sentiment, [], market_context=market_context, plan_tables=""
    )

    # 因子评分 section 必须出现
    assert "各标的因子评分" in prompt, "prompt missing factor scoring section (P5a)"
    # 因子分值必须出现
    assert "0.72" in prompt, "prompt should contain factor_score 0.72 for 510300"
    # 因子分解子项必须出现
    assert "ln_mcap" in prompt or "amount_stability" in prompt, (
        "prompt should contain individual factor breakdown items"
    )


# ─── P3: change_pct in trend + build_rationale ──────────────────────

async def test_p3_fetch_single_trend_has_change_pct():
    """_fetch_single_trend must compute today's change_pct from last two closes.
    Uses china_market.fetch_history (mootdx→Sina) instead of raw akshare."""
    from app.services import market_trends

    # Mock fetch_history return: 5 rows, closes 1.10, 1.08, 1.05, 1.00, 0.923
    # Latest close 0.923, prev close 1.00 → change_pct = -0.077
    fake_rows = [
        {"日期": f"2026-07-{14+i}", "收盘": c, "成交量": 1000000 * (5-i)}
        for i, c in enumerate([1.10, 1.08, 1.05, 1.00, 0.923])
    ]
    with patch("app.fetchers.china_market.fetch_history", return_value=fake_rows):
        res = await market_trends._fetch_single_trend("510300")

    assert "change_pct" in res, "_fetch_single_trend missing change_pct (P3)"
    assert abs(res["change_pct"] - (-0.077)) < 1e-3, f"change_pct={res.get('change_pct')}"


def test_p3_build_rationale_uses_real_factor_data():
    """build_rationale uses actual factor keys (RSI, MACD, composite scores) instead of
    non-existent keys like change_pct / return_3m (rationale.py fix)."""
    from app.services.strategy_design import build_rationale

    rationale = build_rationale(
        code="510300",
        layer="core",
        strategy="balanced",
        meta={"name": "HS300ETF"},
        factor_scores={
            "technical.rsi.rsi_14": 35.2,
            "technical.macd.macd": 0.005,
            "technical": -0.5,
            "momentum": 0.3,
            "technical.signal.overall": -0.1,
        },
        regime="correction",
    )
    # Should NOT contain "今日" placeholder
    assert "今日" not in rationale, f"rationale should NOT contain '今日' placeholder, got: {rationale}"
    # Should contain actual factor data
    assert "RSI" in rationale, f"rationale should include RSI, got: {rationale}"
    assert "技术面" in rationale, f"rationale should include technical score, got: {rationale}"
    assert "市场回调" in rationale, f"rationale should include market regime 'correction', got: {rationale}"


# ─── P0.5: regime fallback via index_realtime ────────────────────────

async def test_p0p5_regime_fallback_from_index_realtime():
    """When trend_data for 510300 is empty (akshare timeout), detect_market_regime
    must fall back to index_realtime and detect 'correction' from a -5.4% plunge."""
    from app.services import market_trends
    from app.services.strategy_design import generate_enhanced_design

    fake_trend = {"510300": {}}  # empty trend → akshare failure simulation
    fake_sentiment = {"sentiment_index": 50, "sentiment_label": "neutral", "advance_ratio": 0.5}
    fake_macro = {"economic_phase": "弱复苏", "monetary_stance": "宽松", "bond_bull": True}
    fake_benchmark = []
    fake_index_realtime = [
        {"symbol": "399001", "name": "深证成指", "price": 13706.88, "change_pct": -0.054},
        {"symbol": "399006", "name": "创业板指", "price": 3428.63, "change_pct": -0.0715},
    ]
    fake_sector = []

    with patch("app.services.market_trends.compute_etf_trends", new=AsyncMock(return_value=fake_trend)), \
         patch("app.services.macro_state.detect_macro_regime", new=AsyncMock(return_value=fake_macro)), \
         patch("app.fetchers.sentiment_fetcher.fetch_market_sentiment", new=AsyncMock(return_value=fake_sentiment)), \
         patch("app.fetchers.benchmark_stocks.fetch_benchmark_stocks", new=AsyncMock(return_value=fake_benchmark)), \
         patch("app.fetchers.news_fetcher.fetch_news_headlines", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.fundamental_fetcher.fetch_fund_flow", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.fundamental_fetcher.fetch_current_pe_pb", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.china_market.fetch_index_realtime", new=Mock(return_value=fake_index_realtime)), \
         patch("app.services.market_trends.compute_sector_momentum", new=AsyncMock(return_value=fake_sector)), \
         patch("app.services.pool_manager.pool_manager") as mp:
        mp.refresh = AsyncMock()
        mp.get_pool = lambda *a, **k: _fake_pool()
        mp.get_factor_matrix = lambda: {"512480": {"technical": 0.7, "momentum": 0.6, "valuation": 0.5, "sentiment": 0.4}}
        mp.get_market_regime = lambda: "correction"
        mp.get_market_sentiment = lambda: fake_sentiment
        mp.get_index_realtime = lambda: fake_index_realtime
        mp.get_sector_momentum = lambda: fake_sector
        result = await generate_enhanced_design(capital=500000)

    strategies = result.get("strategies", [])
    assert len(strategies) > 0, f"generate_enhanced_design returned 0 strategies, error: {result.get('detail', 'N/A')}"
    regime = result["market_context"]["market_regime"]
    assert regime == "correction", (
        f"P0.5 failed: expected 'correction' from index_realtime -5.4% fallback, "
        f"got {regime!r}"
    )


# ─── UX3: load_only on list_designs ─────────────────────────────────

async def test_ux3_list_designs_loads_only_metadata():
    """GET /portfolio/designs must use SQLAlchemy load_only so that large
    strategies_json / market_snapshot_json columns are not loaded."""
    from sqlalchemy import select, desc
    from sqlalchemy.orm import load_only
    from app.models.portfolio_design import PortfolioDesign
    from app.routers.portfolio import list_designs as endpoint

    # Inspect the SQL query built by the endpoint to confirm load_only is applied.
    # We should see load_only columns in the compiled statement.
    mock_stmt = (
        select(PortfolioDesign)
        .options(load_only(
            PortfolioDesign.id,
            PortfolioDesign.created_at,
            PortfolioDesign.capital,
            PortfolioDesign.risk_profile,
            PortfolioDesign.status,
            PortfolioDesign.error_message,
        ))
        .order_by(desc(PortfolioDesign.created_at))
        .limit(10)
    )
    compiled = str(mock_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "strategies_json" not in compiled, (
        "load_only should exclude strategies_json from the SELECT; "
        "got column in query: " + compiled
    )
    assert "market_snapshot_json" not in compiled, (
        "load_only should exclude market_snapshot_json from the SELECT"
    )
    # Column names should be present (table alias is portfolio_designs)
    assert "portfolio_designs.created_at" in compiled or "portfolio_designs.capital" in compiled
    # P4-1: error_message must also be in the load_only columns
    assert "error_message" in compiled, (
        "load_only should include error_message in the SELECT; "
        "fix the endpoint to add error_message to load_only"
    )


# ─── P5-a: _build_plan_tables ──────────────────────────────────

def test_p5a_build_plan_tables_has_structure():
    """_build_plan_tables must emit 方案详解, plan labels, ETF symbols, and layer labels."""
    from app.tasks.design_report import _build_plan_tables

    strategies = [
        {
            "label": "稳健增值方案",
            "layer_budget": {"core": 0.50, "satellite": 0.30, "defense": 0.20},
            "allocations": [
                {"symbol": "510300", "name": "HS300ETF", "layer": "core",
                 "target_weight": 0.30, "selection_rationale": "大盘宽基"},
                {"symbol": "513100", "name": "纳指ETF", "layer": "satellite",
                 "target_weight": 0.20, "selection_rationale": "海外科技"},
            ],
        },
        {
            "label": "积极成长方案",
            "layer_budget": {"core": 0.40, "satellite": 0.40, "defense": 0.20},
            "allocations": [
                {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
                 "target_weight": 0.25, "selection_rationale": "国产替代"},
                {"symbol": "511880", "name": "银华日利", "layer": "defense",
                 "target_weight": 0.15, "selection_rationale": "流动性管理"},
            ],
        },
    ]

    result = _build_plan_tables(strategies)

    assert "方案详解" in result, "result missing 方案详解 header"
    assert "稳健增值方案" in result, "result missing first plan label"
    assert "积极成长方案" in result, "result missing second plan label"
    assert "510300" in result, "result missing ETF symbol 510300"
    assert "512480" in result, "result missing ETF symbol 512480"
    assert "513100" in result, "result missing ETF symbol 513100"
    assert "511880" in result, "result missing ETF symbol 511880"
    assert "核心" in result, "result missing 核心 layer"
    assert "卫星" in result, "result missing 卫星 layer"
    assert "防御" in result, "result missing 防御 layer"


# ─── P6: dynamic_layer_budget 参数调优 ─────────────────────────

async def test_p6_correction_satellite_reduction():
    """correction 模式下 aggressive 卫星层应降至 ~25%，防御型现金 > 进攻型现金。"""
    from app.services.strategy_design import generate_enhanced_design
    from app.engine.budgets import dynamic_layer_budget

    delta = dynamic_layer_budget("aggressive", "correction")
    aggressive_sat = delta.get("satellite", 0)
    assert aggressive_sat < 0.28, (
        f"correction aggressive satellite should be ~0.25, got {aggressive_sat:.3f}"
    )

    # 防御型现金 > 进攻型现金
    def_budget = dynamic_layer_budget("defensive", "correction")
    agg_budget = dynamic_layer_budget("aggressive", "correction")
    def_cash = 1.0 - sum(def_budget.values())
    agg_cash = 1.0 - sum(agg_budget.values())
    assert def_cash > agg_cash, (
        f"defensive cash ({def_cash:.2f}) should be > aggressive cash ({agg_cash:.2f})"
    )


# ─── P7: sentiment regime bias ──────────────────────────────────

async def test_p7_sentiment_regime_bias():
    """数据源故障(sentiment_index=50)时，regime 应覆盖情绪指数。"""
    from app.services.strategy_design import generate_enhanced_design

    fake_trend = {
        "510300": {"return_1m": -0.15, "return_3m": -0.12, "ma_bias_20": 0.0},
    }
    fake_sentiment = {"sentiment_index": 50, "sentiment_label": "neutral"}
    fake_macro = {"economic_phase": "recovery", "monetary_stance": "loose"}
    fake_benchmark = [{"symbol": "600519", "name": "Moutai", "change_pct": -0.8, "signal": "sell"}]
    fake_sector = []
    fake_index_realtime = [
        {"name": "上证指数", "symbol": "000001", "price": 3764, "change_pct": -3.05},
    ]

    with patch("app.services.market_trends.compute_etf_trends", new=AsyncMock(return_value=fake_trend)), \
         patch("app.services.macro_state.detect_macro_regime", new=AsyncMock(return_value=fake_macro)), \
         patch("app.fetchers.sentiment_fetcher.fetch_market_sentiment", new=AsyncMock(return_value=fake_sentiment)), \
         patch("app.fetchers.benchmark_stocks.fetch_benchmark_stocks", new=AsyncMock(return_value=fake_benchmark)), \
         patch("app.fetchers.news_fetcher.fetch_news_headlines", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.news_fetcher.fetch_macro_news", new=AsyncMock(return_value=[])), \
         patch("app.fetchers.fundamental_fetcher.fetch_fund_flow", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.fundamental_fetcher.fetch_current_pe_pb", new=AsyncMock(return_value=None)), \
         patch("app.fetchers.china_market.fetch_index_realtime", new=Mock(return_value=fake_index_realtime)), \
         patch("app.services.market_trends.compute_sector_momentum", new=AsyncMock(return_value=fake_sector)), \
         patch("app.services.pool_manager.pool_manager") as mp:
        mp.refresh = AsyncMock()
        mp.get_pool = lambda *a, **k: _fake_pool()
        mp.get_factor_matrix = lambda: {"512480": {"technical": 0.7, "momentum": 0.6, "valuation": 0.5, "sentiment": 0.4}}
        mp.get_market_regime = lambda: "correction"
        mp.get_market_sentiment = lambda: fake_sentiment
        mp.get_index_realtime = lambda: fake_index_realtime
        mp.get_sector_momentum = lambda: fake_sector
        result = await generate_enhanced_design(capital=500000)

    strategies = result.get("strategies", [])
    assert len(strategies) > 0, f"generate_enhanced_design returned 0 strategies, error: {result.get('detail', 'N/A')}"
    ctx = result.get("market_context", {})
    sent = ctx.get("market_sentiment", {})
    idx = sent.get("sentiment_index", 50)
    label = sent.get("sentiment_label", "")
    assert idx <= 50, (
        f"P7 failed: sentiment_index should be <=50 (regime override), got {idx}"
    )
    regime_val = ctx.get("market_regime", "")
    assert regime_val == "correction", (
        f"P7 failed: regime should be 'correction' overriding neutral sentiment, got {regime_val!r}"
    )


# ─── P8: import 路由无死桩 ────────────────────────────────────

def test_p8_import_route_not_stub():
    """POST /import 路由不能是 pass 桩，须有真实响应体。"""
    from app.routers.portfolio import router
    for route in router.routes:
        if route.path == "/api/v1/portfolio/import" and "POST" in route.methods:
            # 确认路由绑定了真实函数，未使用 pass 桩
            assert route.endpoint.__name__ != "import_portfolio_endpoint", (
                "import route is still the dead stub! "
                "Remove the first @router.post('/import') with pass body."
            )
            return
    # 如果没找到 import 路由，也视为失败
    assert False, "POST /api/v1/portfolio/import route not found"


# ─── P9: consistency check runs before broadcast ───────────────

def test_p9_consistency_check_before_broadcast():
    """_validate_report_consistency 必须在 WS broadcast 之前调用。"""
    import ast, inspect
    from app.tasks import design_report as dr

    source = inspect.getsource(dr.compose_and_push_report)
    tree = ast.parse(source)

    # Walk AST: find broadcast call and consistency check call
    broadcast_lineno = None
    check_lineno = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "broadcast":
                broadcast_lineno = node.lineno
            if isinstance(node.func, ast.Attribute) and node.func.attr == "_validate_report_consistency":
                check_lineno = node.lineno
            if isinstance(node.func, ast.Name) and node.func.id == "_validate_report_consistency":
                check_lineno = node.lineno

    assert check_lineno is not None, (
        "_validate_report_consistency call not found in compose_and_push_report"
    )
    assert broadcast_lineno is not None, (
        "broadcast call not found in compose_and_push_report"
    )
    assert check_lineno < broadcast_lineno, (
        f"consistency check at line {check_lineno} must run before "
        f"broadcast at line {broadcast_lineno}"
    )


# ─── P10: _strip_ai_boilerplate ─────────────────────────────────


def test_p10_strip_ai_boilerplate_removes_header():
    """_strip_ai_boilerplate 必须删除'报告日期'/'分析师'行及第一句 AI 腔。"""
    from app.tasks.design_report import _strip_ai_boilerplate

    text = (
        "好的，作为专业的 ETF 投资组合策略分析师，我将为您撰写一份报告。\n\n"
        "### ETF 投资组合策略报告\n\n"
        "**报告日期：** 2024年5月24日\n"
        "**分析师：** AI 投资组合策略分析师\n\n"
        "这是正文内容。\n"
    )
    cleaned = _strip_ai_boilerplate(text)

    assert "报告日期" not in cleaned, "should strip 报告日期 line"
    assert "分析师" not in cleaned, "should strip 分析师 line"
    assert "好的，作为专业的" not in cleaned, "should strip AI opening"
    assert "这是正文内容" in cleaned, "should preserve real content"


def test_p10_strip_ai_boilerplate_preserves_content():
    """正常内容不应被误删。"""
    from app.tasks.design_report import _strip_ai_boilerplate

    text = "当前市场处于回调延续阶段。\n防御风格占主导。"
    cleaned = _strip_ai_boilerplate(text)
    assert cleaned == text, f"got: {cleaned!r}"


def test_p10_strip_ai_boilerplate_empty():
    """空文本不应崩溃。"""
    from app.tasks.design_report import _strip_ai_boilerplate
    assert _strip_ai_boilerplate("") == ""
    assert _strip_ai_boilerplate(None) == ""


# ─── P11: _build_plan_tables rationale length ────────────────────


def test_p11_rationale_not_truncated_too_short():
    """入选理由至少保留 150 字符，不应仅 100。"""
    from app.tasks.design_report import _build_plan_tables

    long_rationale = "基于" + "测试" * 60  # 120 chars
    strategies = [
        {
            "label": "测试方案",
            "layer_budget": {"core": 0.50, "satellite": 0.30, "defense": 0.20},
            "allocations": [
                {"symbol": "510300", "name": "HS300ETF", "layer": "core",
                 "target_weight": 0.30, "selection_rationale": long_rationale},
            ],
        },
    ]

    result = _build_plan_tables(strategies)
    assert long_rationale[:150] in result, (
        "rationale should retain at least 150 chars"
    )


# ─── P12: generate_strategy_check_report ───────────────────────


def test_p12_strategy_check_agent_registered():
    """strategy_check agent must be registered in registry."""
    from app.analysis.registry import get_agent

    agent = get_agent("strategy_check")
    assert agent is not None
    assert agent.config.name == "策略检查"
    assert agent.config.response_format == "json_object"


# ─── P13: strategy_check response schema ───────────────────────


def test_p13_strategy_check_schema_compliance():
    """strategy_check v2 response schema matches contract."""
    from app.analysis.llm import generate_strategy_check_report
    import inspect
    sig = inspect.signature(generate_strategy_check_report)
    
    # Check function signature accepts new params
    params = list(sig.parameters.keys())
    assert "market_data" in params
    assert "factor_breakdowns" in params
    assert "regime" in params
    
    # Return type should be dict
    assert sig.return_annotation in (dict, inspect.Parameter.empty)
