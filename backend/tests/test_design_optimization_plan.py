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
        result = await generate_enhanced_design(capital=500000)

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
        result = await generate_enhanced_design(capital=500000)

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
        strategies, market_sentiment, [], market_context=market_context
    )
    assert "市场行情快照" in prompt, "prompt missing 市场行情快照 section (P1)"
    assert "行业板块动量" in prompt, "prompt missing 行业板块动量 section (P1)"
    assert "-5.4%" in prompt or "5.4%" in prompt, "prompt should cite actual index change_pct"


# ─── P3: change_pct in trend + build_rationale ──────────────────────

async def test_p3_fetch_single_trend_has_change_pct():
    """_fetch_single_trend must compute today's change_pct from last two closes."""
    from app.services import market_trends

    fake_df = _make_fake_df_with_change()
    with patch("akshare.fund_etf_hist_em", return_value=fake_df), \
         patch("app.utils.decode.decode_df"):
        res = await market_trends._fetch_single_trend("510300")

    assert "change_pct" in res, "_fetch_single_trend missing change_pct (P3)"
    assert abs(res["change_pct"] - (-0.077)) < 1e-3, f"change_pct={res.get('change_pct')}"


def test_p3_build_rationale_today_line():
    """build_rationale must prepend 'today down X%' from trend.change_pct."""
    from app.services.strategy_design import build_rationale

    rationale = build_rationale(
        code="510300",
        layer="core",
        strategy="balanced",
        meta={"name": "HS300ETF"},
        trend={"change_pct": -0.077, "return_1m": -0.05, "return_3m": -0.12, "ma_bias_20": -0.02},
        regime="correction",
        sentiment={"sentiment_index": 40},
    )
    assert "今日跌7.7%" in rationale, f"rationale should start with today's move, got: {rationale}"
