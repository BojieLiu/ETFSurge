"""Integration test: engine-level pipeline with data-source-level mocking.

Tests the full allocation pipeline from factor computation to strategy
output, mocking only at the data source boundary (HTTP/IO level).
All engine modules (factor aggregation, allocate, rationale) run unmodified
with realistic data shapes.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_integration_engine_pipeline():
    """Engine-level integration: mock only data sources, run real engine.

    Mocks at data source boundary:
      - PoolManager scanner.full_pipeline (realistic ETF entries)
      - FactorRegistry._fetch_market_data (realistic OHLCV)
      - Classifier.batch_classify (industry/concept mapping)

    Engine logic (composite score, _select_and_weight, allocate, build_rationale)
    runs unmodified.

    Verifies:
      - 3 strategies with distinct labels
      - Each has >= 1 non-CASH allocation with positive weight
      - Rationale has no placeholder strings
    """
    from app.services.strategy_design import generate_enhanced_design
    from app.services.pool_manager import PoolManager
    import app.factors.factor_registry as fr_mod

    pm = PoolManager()
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

    # Mock FactorRegistry data with realistic OHLCV + fund_scale
    REALISTIC_DATA = {
        "510300": {"close": [4.13, 4.11, 4.09, 4.07, 4.05, 4.03, 4.02, 4.06],
                   "volume": [12345678, 11000000, 10000000, 9500000, 9000000,
                              8500000, 8800000, 9200000],
                   "high": [4.15, 4.13, 4.11, 4.09, 4.07, 4.05, 4.08, 4.12],
                   "low": [4.10, 4.08, 4.06, 4.04, 4.02, 4.00, 4.01, 4.04],
                   "open": [4.12, 4.10, 4.08, 4.06, 4.04, 4.02, 4.05, 4.10]},
        "159338": {"close": [1.01, 1.00, 1.02, 0.99, 1.00, 0.98, 0.99, 1.01],
                   "volume": [9876543, 9000000, 8500000, 8000000, 8200000,
                              7800000, 8000000, 9500000],
                   "high": [1.02, 1.01, 1.03, 1.00, 1.01, 0.99, 1.00, 1.02],
                   "low": [1.00, 0.99, 1.01, 0.98, 0.99, 0.97, 0.98, 1.00],
                   "open": [1.01, 1.00, 1.02, 0.99, 1.00, 0.98, 0.99, 1.01]},
        "589980": {"close": [1.15, 1.14, 1.16, 1.13, 1.17, 1.12, 1.14, 1.16],
                   "volume": [5432109, 5000000, 4800000, 5200000, 5600000,
                              4600000, 4900000, 5300000],
                   "high": [1.16, 1.15, 1.17, 1.14, 1.18, 1.13, 1.15, 1.17],
                   "low": [1.14, 1.13, 1.15, 1.12, 1.16, 1.11, 1.13, 1.15],
                   "open": [1.15, 1.14, 1.16, 1.13, 1.17, 1.12, 1.14, 1.16]},
        "518880": {"close": [5.88, 5.85, 5.90, 5.84, 5.86, 5.82, 5.83, 5.87],
                   "volume": [3456789, 3000000, 3200000, 2800000, 3100000,
                              2700000, 2900000, 3300000],
                   "high": [5.90, 5.87, 5.92, 5.86, 5.88, 5.84, 5.85, 5.89],
                   "low": [5.85, 5.83, 5.88, 5.82, 5.84, 5.80, 5.81, 5.85],
                   "open": [5.88, 5.85, 5.90, 5.84, 5.86, 5.82, 5.83, 5.87]},
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
                      new=_mock_fetch_market_data):
        result = await generate_enhanced_design(capital=500000)

    assert result is not None
    strategies = result.get("strategies", [])
    assert len(strategies) == 3, f"Expected 3 strategies, got {len(strategies)}"

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

        assert len(cash) == 1, f"Expected 1 cash entry in '{label}', got {len(cash)}"
        for a in non_cash:
            symbols_seen.add(a["symbol"])
            w = a.get("target_weight", 0)
            assert w > 0, f"ETF {a['symbol']} in '{label}' weight={w}"
            rt = a.get("selection_rationale", "")
            assert rt, f"Empty rationale for {a['symbol']}/{label}"
            assert "今日" not in rt, f"Placeholder '今日' in {a['symbol']}/{label}"
            assert "{" not in rt, f"Unfilled template in {a['symbol']}/{label}"

    assert len(labels) == 3, f"Expected 3 distinct labels, got {labels}"
    assert len(label_list) == 3, f"Expected 3 strategies, got {len(label_list)}"
    assert "510300" in symbols_seen, "510300 must appear in at least one strategy"
    assert total_non_cash >= 6, f"Expected >=6 total ETF positions, got {total_non_cash}"
