"""Integration test: engine-level pipeline with data-source-level mocking.

Tests the full allocation pipeline from factor computation to strategy
output, mocking only at the data source boundary (HTTP/IO level).
All engine modules (factor aggregation, allocate, rationale) run unmodified
with realistic data shapes.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_integration_engine_pipeline():
    """Engine-level integration: mock only data sources, run real engine.

    Mocks at data source boundary:
      - MarketDataHub scanner.full_pipeline (realistic ETF entries)
      - FactorRegistry._fetch_market_data (realistic OHLCV)
      - Classifier.batch_classify (industry/concept mapping)

    Engine logic (composite score, _select_and_weight, allocate, build_rationale)
    runs unmodified.

    Verifies:
      - 3 strategies with distinct labels
      - Each has >= 1 non-CASH allocation with positive weight
      - Rationale has no placeholder strings
    """
    # generate_enhanced_design uses the module-level market_data_hub singleton,
    # so we must mock the singleton directly, not create a local instance.
    from app.services.strategy_design import generate_enhanced_design
    from app.services.market_data_hub import market_data_hub as live_pm
    import app.factors.factor_registry as fr_mod

    pm = live_pm
    pm.scanner = MagicMock()
    pm.scanner.full_pipeline.return_value = {
        "core": [
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300指数",
             "amount": 5.1e7, "fund_scale": 2300000000.0},
            {"symbol": "159338", "name": "中证A500ETF", "tracked_index": "中证A500指数",
             "amount": 1.0e7, "fund_scale": 1200000000.0},
        ],
        "satellite": [
            {"symbol": "589980", "name": "科创100ETF汇添富", "tracked_index": "上证科创板100指数",
             "amount": 6.2e6, "fund_scale": 500000000.0},
        ],
        "defense": [
            {"symbol": "518880", "name": "黄金ETF", "tracked_index": "黄金9999",
             "amount": 2.0e7, "fund_scale": 1500000000.0},
        ],
    }
    pm.classifier = MagicMock()
    pm.classifier.batch_classify.return_value = {
        "510300": {"industry": "宽基指数", "concepts": ["沪深300"], "confidence": 0.95},
        "159338": {"industry": "宽基指数", "concepts": ["A500"], "confidence": 0.92},
        "589980": {"industry": "主题指数", "concepts": ["科创100"], "confidence": 0.88},
        "518880": {"industry": "商品", "concepts": ["黄金"], "confidence": 0.95},
    }
    pm.get_market_sentiment = MagicMock(return_value={"sentiment_index": 55})
    pm.get_news = MagicMock(return_value=[
        {"title": "政策利好", "level": "利好", "stars": 4},
        {"title": "市场平稳", "level": "中性", "stars": 3},
    ])
    pm.get_regime = MagicMock(return_value="range_bound")
    pm.get_index_realtime = MagicMock(return_value=[])
    pm.get_sector_momentum = MagicMock(return_value=[])

    # Force a fresh refresh with mocked data (skip cooldown)
    pm._last_refresh_ts = 0.0
    # Also mock the news/f10 enrichment to prevent real HTTP calls
    pm._news_cache = []
    pm._sentiment_cache = {"sentiment_index": 55, "sentiment_label": "中性"}
    # Clear any stale pool from previous tests
    pm._pool = {"core": [], "satellite": [], "defense": []}
    pm._by_code = {}
    pm._factor_cache = {}
    # Mock the market snapshot function which calls real HTTP (global indices, sector momentum)
    pm._refresh_market_snapshot = AsyncMock()

    # Mock FactorRegistry data with realistic OHLCV + fund_scale
    # Need 30+ data points to support RSI_14 (15), MACD (26), SMA_20 (20), Bollinger (20)
    def _gen_prices(base, count=35, drift=0.001, jitter=0.005):
        """Generate realistic price list with slight drift and noise."""
        vals = [base]
        for i in range(1, count):
            v = vals[-1] * (1 + drift + jitter * (i % 5 - 2) / 10)
            vals.append(round(v, 2))
        return vals

    REALISTIC_DATA = {}
    for sym, base_close in [("510300", 4.12), ("159338", 1.01), ("589980", 1.15), ("518880", 5.87)]:
        closes = _gen_prices(base_close)
        REALISTIC_DATA[sym] = {
            "close": closes,
            "open": [c * (1 - 0.002) for c in closes],
            "high": [c * (1 + 0.005) for c in closes],
            "low": [c * (1 - 0.005) for c in closes],
            "volume": [int(v) for v in _gen_prices(10000000, 35, 0, 0.3)],
        }

    async def _mock_fetch_market_data(self, symbols, symbol_extra=None):
        result = {}
        for sym in symbols:
            d = dict(REALISTIC_DATA.get(sym, REALISTIC_DATA["510300"]))
            extra = (symbol_extra or {}).get(sym, {})
            fs = float(extra.get("fund_scale", 0) or 100e9)
            d["total_mv"] = fs
            d["float_mv"] = fs * 0.8
            result[sym] = d
        return result

    with patch.object(fr_mod.FactorRegistry, "_fetch_market_data",
                      new=_mock_fetch_market_data), \
         patch("app.fetchers.etf_scanner.enrich_tracked_indices") as _mock_enrich, \
         patch("app.services.market_trends.compute_sector_momentum",
               return_value=[]), \
         patch("app.fetchers.fundamentals_fetcher.fetch_market_sentiment",
               return_value={"sentiment_index": 55}):
        _mock_enrich.return_value = None
        result = await generate_enhanced_design(capital=500000)

        # All assertions inside the patch context to prevent fire-and-forget leaks
        assert result is not None
        strategies = result.get("strategies", [])
        assert len(strategies) == 3

        labels = set()
        total_non_cash = 0
        symbols_seen = set()
        label_list = []

        for s in strategies:
            label = s.get("label", s.get("name", "?"))
            label_list.append(label)
            labels.add(label)
            allocs = s.get("allocations", s.get("etfs", []))
            non_cash = [a for a in allocs if a.get("symbol") and a["symbol"] != "CASH"]
            cash = [a for a in allocs if a.get("symbol") == "CASH"]
            total_non_cash += len(non_cash)
            assert len(cash) == 1
            for a in non_cash:
                symbols_seen.add(a["symbol"])
                w = a.get("weight", a.get("target_weight", 0))
                assert w > 0
                rt = a.get("selection_rationale", "")
                assert rt
                assert "今日" not in rt
                assert "{" not in rt

        assert len(labels) == 3
        assert len(label_list) == 3
        assert "510300" in symbols_seen
        assert total_non_cash >= 6
