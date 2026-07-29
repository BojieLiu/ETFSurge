"""S5: MarketDataHub — 统一数据入口别名。

MarketDataHub 是 PoolManager 的别名（继承关系），提供统一的
K 线缓存 / 数据源分发。所有现有 PoolManager 引用无需修改。
"""

from .pool_manager import PoolManager

# MarketDataHub 是 PoolManager 的别名，两者是同一个类
MarketDataHub = PoolManager

__all__ = ["MarketDataHub", "PoolManager"]
