"""MarketDataHub — 统一数据管道入口。

当前状态: pool_manager 别名的过渡态。
MarketDataHub, market_data_hub = pool_manager (同一个对象)。

迁移目标:
  旧: from ..services.pool_manager import pool_manager
  新: from ..services.market_data_hub import market_data_hub

使用方式:
    from ..services.market_data_hub import market_data_hub
    regime = market_data_hub.get_market_regime()
    pool = market_data_hub.get_pool()
"""

import warnings
from .pool_manager import pool_manager as _pm_singleton

# MarketDataHub 是 pool_manager 的别名
# 两者指向同一个 PoolManager 单例
market_data_hub = _pm_singleton
pool_manager = _pm_singleton

# MarketDataHub 是类型别名（用于类型注解）
MarketDataHub = type(_pm_singleton)

__all__ = ["MarketDataHub", "market_data_hub", "pool_manager"]
