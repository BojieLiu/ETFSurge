"""Realtime market data mixin — split from market_data_hub (Batch 3)."""

import logging

logger = logging.getLogger(__name__)

class RealtimeMixin:
    def get_index_realtime(self) -> list[dict]:
        """获取 A 股大盘实时行情缓存。"""
        return self._index_realtime_cache or []


    async def get_realtime(self, symbols: list[str], asset_type: str = "A") -> list[dict]:
        """批量实时行情（委托 market_service.get_realtime_batch）。"""
        from ...services.market_service import get_realtime_batch
        return await get_realtime_batch(symbols, asset_type)


    async def get_all_realtime(self) -> list[dict]:
        """全量实时行情（委托 market_service.get_all_realtime）。"""
        from ...services.market_service import get_all_realtime
        return await get_all_realtime()


    async def get_asset_realtime(self, symbol: str, asset_type: str) -> dict | None:
        """单标的实时行情（委托 market_service.get_asset_realtime）。"""
        from ...services.market_service import get_asset_realtime
        return await get_asset_realtime(symbol, asset_type)


    async def get_portfolio_realtime(self) -> list[dict]:
        """组合实时行情（委托 market_service.get_portfolio_realtime）。"""
        from ...services.market_service import get_portfolio_realtime
        return await get_portfolio_realtime()


    async def get_indices(self) -> list[dict]:
        """全球指数（委托 market_service.get_indices）。"""
        from ...services.market_service import get_indices
        return await get_indices()


    async def get_global_indices(self) -> dict[str, list[dict]]:
        """全球指数分组（委托 market_service.get_global_indices）。"""
        from ...services.market_service import get_global_indices
        return await get_global_indices()


    async def get_commodities(self) -> list[dict]:
        """商品行情（委托 market_service.get_commodities）。"""
        from ...services.market_service import get_commodities
        return await get_commodities()


    async def get_market_history(self, symbol: str, asset_type: str = "A", period: str = "daily") -> list[dict]:
        """历史 K 线（完整 fallback 链，委托 market_service.get_history）。"""
        from ...services.market_service import get_history as _get_history
        return await _get_history(symbol, asset_type, period)


    async def search_etf(self, keyword: str) -> list[dict]:
        """ETF 搜索（委托 market_service.search_etf）。"""
        from ...services.market_service import search_etf as _search_etf
        return await _search_etf(keyword)


    async def get_sectors_local(self, sector_type: str) -> list[dict]:
        """本地板块列表（委托 market_service.get_sectors_local）。"""
        from ...services.market_service import get_sectors_local as _get
        return await _get(sector_type)


    async def get_indices_meta(self) -> list[dict]:
        """指数元数据（委托 market_service.get_indices_meta）。"""
        from ...services.market_service import get_indices_meta as _get
        return await _get()


    async def search_indices(self, keyword: str) -> list[dict]:
        """指数搜索（委托 market_service.search_indices）。"""
        from ...services.market_service import search_indices as _search
        return await _search(keyword)


    async def get_market_fundamentals(self, symbol: str) -> dict | None:
        """基本面（market_service 版：返回 {symbol, daily} 结构）。"""
        from ...services.market_service import get_fundamentals as _get
        return await _get(symbol)


    def get_market_wind(self) -> list[dict]:
        """市场风控（levistock）。"""
        try:
            from ...fetchers.levistock_fetcher import fetch_market_wind
            return fetch_market_wind() or []
        except Exception as e:
            logger.warning("[hub] get_market_wind failed: %s", e)
            return []


    def get_advance_decline(self) -> float:
        """涨跌家数比（因子用）。"""
        try:
            from ...fetchers.fundamentals_fetcher import fetch_advance_decline_ratio
            return fetch_advance_decline_ratio()
        except Exception as e:
            logger.warning("[hub] get_advance_decline failed: %s", e)
            return 0.0


    def get_hk_stock_realtime(self, symbol: str | None = None) -> list[dict]:
        """港股实时行情。"""
        try:
            from ...fetchers.china_market import fetch_hk_stock_realtime
            return fetch_hk_stock_realtime(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_hk_stock_realtime failed: %s", e)
            return []


    def get_us_etf_realtime(self, symbol: str):
        """美股 ETF 实时行情。"""
        try:
            from ...fetchers.global_markets_fetcher import fetch_us_etf_realtime
            return fetch_us_etf_realtime(symbol)
        except Exception as e:
            logger.warning("[hub] get_us_etf_realtime(%s) failed: %s", symbol, e)
            return None


    def get_us_stock_realtime(self, symbol: str):
        """美股个股实时（TwelveData 降级链）。"""
        try:
            from ...fetchers.global_markets_fetcher import fetch_realtime
            return fetch_realtime(symbol)
        except Exception as e:
            logger.warning("[hub] get_us_stock_realtime(%s) failed: %s", symbol, e)
            return None


    def get_us_history(self, symbol: str, days: int = 60) -> list[dict]:
        """美股历史 K 线（TwelveData）。"""
        try:
            from ...fetchers.global_markets_fetcher import fetch_history
            return fetch_history(symbol, days) or []
        except Exception as e:
            logger.warning("[hub] get_us_history(%s) failed: %s", symbol, e)
            return []


    def get_us_candles(self, symbol: str, resolution: str = "D") -> list[dict]:
        """美股蜡烛图（Finnhub）。"""
        try:
            from ...fetchers.global_markets_fetcher import fetch_candles
            return fetch_candles(symbol, resolution) or []
        except Exception as e:
            logger.warning("[hub] get_us_candles(%s) failed: %s", symbol, e)
            return []
