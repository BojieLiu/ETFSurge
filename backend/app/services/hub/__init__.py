"""Hub collaborators for MarketDataHub — split from market_data_hub.py (Batch 3).

Each module defines a mixin with one responsibility cluster. MarketDataHub (in
``app/services/market_data_hub.py``) composes these mixins via MRO; shared state
lives on the facade instance so methods move verbatim. Module-level functions and
constants live in ``_common``.

Re-exports here keep ``from app.services.hub import <symbol>`` working for future
consumers. Note: ``MarketDataHub`` itself is deliberately NOT re-exported from this
package (importing it would create an import cycle with the facade module).
"""

from app.services.hub._common import (
    MANDATORY_CODES,
    SECTOR_ETF_MAP,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    ALL_LAYERS,
    _LAYER_WEIGHTS,
    _BASE_WEIGHTS,
    MAX_PER_LAYER,
    _snapshot_db_path,
    _snapshot_as_of_for,
    _persist_snapshot_sync,
    _load_latest_snapshot_sync,
    _parse_stock_list,
    _parse_concept_tags,
    _normalize_hot_plate,
    _strong_sector_etfs,
    _rule_news_summary,
    PoolDiff,
)
from app.services.hub._snapshot import SnapshotMixin
from app.services.hub._kline import KlineMixin
from app.services.hub._realtime import RealtimeMixin
from app.services.hub._sector import SectorMixin
from app.services.hub._news import NewsMixin
from app.services.hub._regime_sentiment import RegimeSentimentMixin
from app.services.hub._pool import PoolMixin
from app.services.hub._fundamentals import FundamentalsMixin

__all__ = [
    "MANDATORY_CODES",
    "SECTOR_ETF_MAP",
    "LAYER_CORE",
    "LAYER_SATELLITE",
    "LAYER_DEFENSE",
    "LAYER_OPPORTUNISTIC",
    "LAYER_RESEARCH",
    "ALL_LAYERS",
    "_LAYER_WEIGHTS",
    "_BASE_WEIGHTS",
    "MAX_PER_LAYER",
    "_snapshot_db_path",
    "_snapshot_as_of_for",
    "_persist_snapshot_sync",
    "_load_latest_snapshot_sync",
    "_parse_stock_list",
    "_parse_concept_tags",
    "_normalize_hot_plate",
    "_strong_sector_etfs",
    "_rule_news_summary",
    "PoolDiff",
    "SnapshotMixin",
    "KlineMixin",
    "RealtimeMixin",
    "SectorMixin",
    "NewsMixin",
    "RegimeSentimentMixin",
    "PoolMixin",
    "FundamentalsMixin",
]
