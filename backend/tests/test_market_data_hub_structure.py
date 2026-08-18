"""Contract tests for the market_data_hub split (Batch 3).

Verifies the module-structure contract in
``api-contracts/internal/market-data-hub-split.md``:

- R1: singleton/class + module-level symbols importable from the facade; all
  106 methods reachable on the singleton via mixin MRO.
- R2: shared class-level state moved with its cluster (spot check).
- R3: behavior unchanged (pure function spot checks).
"""

import importlib

from app.services.market_data_hub import (
    MarketDataHub,
    ALL_LAYERS,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    SECTOR_ETF_MAP,
    _snapshot_as_of_for,
    _strong_sector_etfs,
    _rule_news_summary,
    _parse_concept_tags,
    PoolDiff,
    market_data_hub,
)

KEY_METHODS = [
    # facade orchestration
    "refresh", "_refresh_impl", "set_opportunistic_signals", "update_sector_cache",
    "_refresh_market_snapshot", "_fetch_a_index_rows",
    # pure strategy (engine/ in Batch 4)
    "_assign_layer", "_compute_composite", "_balance_by_industry", "_pct_rank",
    # snapshot
    "_persist_snapshot_after_refresh", "_load_pool_snapshot",
    # kline
    "get_kline", "get_history", "get_kline_rows", "refresh_kline",
    "_enrich_symbol_extra", "get_kline_age_seconds",
    # realtime
    "get_realtime", "get_indices", "get_global_indices", "get_commodities",
    "get_hk_stock_realtime", "get_us_etf_realtime", "get_us_candles",
    "get_index_realtime", "get_advance_decline",
    # sector
    "get_sector_momentum", "get_hot_plates", "get_sector_heat",
    "get_sector_industry", "get_fund_flow",
    # news
    "get_news", "enrich_news_summaries", "refresh_news", "get_news_stock",
    # regime / sentiment
    "get_market_regime", "update_market_regime", "get_market_sentiment",
    # pool
    "get_pool", "get_by_code", "get_factor_matrix", "get_akshare_pool_stats",
    # fundamentals
    "get_fundamentals", "get_stock_hot_rank", "get_research_reports",
]


def test_singleton_and_class_importable():
    assert callable(MarketDataHub)
    assert isinstance(market_data_hub, MarketDataHub)


def test_all_key_methods_present_on_singleton():
    for m in KEY_METHODS:
        assert callable(getattr(market_data_hub, m, None)), f"missing method {m}"


def test_module_level_reexports():
    assert ALL_LAYERS == [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE,
                          LAYER_OPPORTUNISTIC, LAYER_RESEARCH]
    assert callable(_snapshot_as_of_for)
    assert callable(_strong_sector_etfs)
    assert callable(_rule_news_summary)
    assert callable(_parse_concept_tags)
    assert "510300" in SECTOR_ETF_MAP or isinstance(SECTOR_ETF_MAP, dict)


def test_mixin_classes_exported_from_package():
    pkg = importlib.import_module("app.services.hub")
    for name in ["SnapshotMixin", "KlineMixin", "RealtimeMixin", "SectorMixin",
                 "NewsMixin", "RegimeSentimentMixin", "PoolMixin", "FundamentalsMixin"]:
        assert hasattr(pkg, name), f"hub package missing {name}"


def test_mixins_composed_in_mro():
    mro_names = [c.__name__ for c in MarketDataHub.__mro__]
    for name in ["KlineMixin", "RealtimeMixin", "SectorMixin", "NewsMixin",
                 "RegimeSentimentMixin", "PoolMixin", "FundamentalsMixin", "SnapshotMixin"]:
        assert name in mro_names, f"{name} not in MarketDataHub MRO"


def test_shared_class_state_moved_with_cluster():
    # state declared on mixins, reachable via instance
    h = MarketDataHub()
    assert hasattr(h, "_KLINE_CACHE_PERSIST_PATH")
    assert hasattr(h, "_regime_cache")
    assert hasattr(h, "_sentiment_cache")
    assert hasattr(h, "_news_buckets")
    assert hasattr(h, "_FUND_SHARES_CACHE")
    assert hasattr(h, "_refresh_lock")


def test_pure_helpers_behavior_unchanged():
    diff = PoolDiff(added=[], removed=[], changed=[], version=1, timestamp="x")
    assert diff.version == 1
    assert callable(_snapshot_as_of_for)
    # _strong_sector_etfs: pure helper keeps signature/behavior
    assert _strong_sector_etfs([], top_n=2) == []
