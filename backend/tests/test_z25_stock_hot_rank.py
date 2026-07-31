"""Test Z25: Stock hot rank volume/sector enrichment.

Covers:
1. volume/turnover filled from batch realtime
2. sector filled from industry map (batch realtime sector takes priority)
3. enrichment failure does not break main flow (returns original rows)
4. sector empty fallback -> ""
"""
import pytest
from unittest.mock import patch


class TestStockHotRankEnrich:
    """Z25: get_stock_hot_rank volume/sector enrichment."""

    def _rank_rows(self):
        return [
            {"rank": 1, "code": "600519", "name": "贵州茅台", "tag": "机构加仓"},
            {"rank": 2, "code": "000858", "name": "五粮液", "tag": "业绩超预期"},
        ]

    def test_volume_turnover_filled_from_batch(self):
        """Z25: volume/turnover joined from batch realtime."""
        from app.services.market_data_hub import market_data_hub

        batch = [
            {"symbol": "600519", "price": 1750.5, "change_pct": 1.25,
             "volume": 12345678, "turnover": 21500000000},
            {"symbol": "000858", "price": 168.0, "change_pct": -0.5,
             "volume": 5000000, "turnover": 8400000000},
        ]
        with patch("app.fetchers.sector_fetcher.fetch_stock_hot_rank",
                   return_value=self._rank_rows()):
            with patch("app.fetchers.china_market.fetch_a_stock_batch", return_value=batch):
                with patch("app.fetchers.sector_fetcher.get_stock_industry_map",
                           return_value={"600519": "白酒", "000858": "白酒"}):
                    result = market_data_hub.get_stock_hot_rank(limit=50)

        assert len(result) == 2
        first = result[0]
        assert first["symbol"] == "600519"
        assert first["volume"] == 12345678
        assert first["turnover"] == 21500000000
        assert first["price"] == 1750.5
        assert first["change_pct"] == 1.25
        assert first["sector"] == "白酒"
        assert first["asset_type"] == "A"
        # rank normalized 1-based
        assert first["rank"] == 1
        assert result[1]["rank"] == 2
        assert result[1]["sector"] == "白酒"

    def test_batch_sector_priority_over_map(self):
        """Z25: batch realtime sector field takes priority over industry map."""
        from app.services.market_data_hub import market_data_hub

        batch = [
            {"symbol": "600519", "price": 1750.5, "change_pct": 1.25,
             "volume": 100, "turnover": 200, "sector": "贵州板块"},
        ]
        with patch("app.fetchers.sector_fetcher.fetch_stock_hot_rank",
                   return_value=[{"rank": 1, "code": "600519", "name": "贵州茅台"}]):
            with patch("app.fetchers.china_market.fetch_a_stock_batch", return_value=batch):
                with patch("app.fetchers.sector_fetcher.get_stock_industry_map",
                           return_value={"600519": "白酒"}):
                    result = market_data_hub.get_stock_hot_rank(limit=50)

        assert result[0]["sector"] == "贵州板块"

    def test_enrich_failure_returns_original_rows(self):
        """Z25: batch realtime failure -> original rows preserved, no crash."""
        from app.services.market_data_hub import market_data_hub

        with patch("app.fetchers.sector_fetcher.fetch_stock_hot_rank",
                   return_value=self._rank_rows()):
            with patch("app.fetchers.china_market.fetch_a_stock_batch",
                       side_effect=Exception("network down")):
                with patch("app.fetchers.sector_fetcher.get_stock_industry_map",
                           return_value={}):
                    result = market_data_hub.get_stock_hot_rank(limit=50)

        # Main flow not broken; rows returned with default volume/sector
        assert len(result) == 2
        assert result[0]["volume"] == 0
        assert result[0]["sector"] == ""

    def test_sector_missing_falls_back_empty(self):
        """Z25: no industry map entry -> sector=''."""
        from app.services.market_data_hub import market_data_hub

        with patch("app.fetchers.sector_fetcher.fetch_stock_hot_rank",
                   return_value=[{"rank": 1, "code": "600519", "name": "贵州茅台"}]):
            with patch("app.fetchers.china_market.fetch_a_stock_batch", return_value=[]):
                with patch("app.fetchers.sector_fetcher.get_stock_industry_map",
                           return_value={}):
                    result = market_data_hub.get_stock_hot_rank(limit=50)

        assert result[0]["sector"] == ""
        assert result[0]["volume"] == 0

    def test_industry_map_function_built(self):
        """Z25: get_stock_industry_map builds {symbol: industry} from stock_basic."""
        from app.fetchers.sector_fetcher import get_stock_industry_map

        with patch("app.fetchers.global_markets_fetcher.fetch_stock_basic",
                   return_value=[
                       {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"},
                       {"symbol": "000858", "name": "五粮液", "industry": "白酒"},
                   ]):
            mapping = get_stock_industry_map(["600519", "000858"])

        assert mapping == {"600519": "白酒", "000858": "白酒"}

    def test_industry_map_empty_on_failure(self):
        """Z25: stock_basic failure -> empty map."""
        from app.fetchers.sector_fetcher import get_stock_industry_map
        from app.services.cache_service import sync_memory_cache
        sync_memory_cache.clear()  # 清除上个用例缓存

        with patch("app.fetchers.global_markets_fetcher.fetch_stock_basic",
                   side_effect=Exception("tushare down")):
            mapping = get_stock_industry_map(["600519"])
        assert mapping == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])