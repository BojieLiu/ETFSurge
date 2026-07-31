"""Test Z20: Search sorting contract.

Covers:
1. Exact code match ranks above code prefix
2. Code prefix ranks above exact name
3. Exact name above name prefix above name contains
4. Same tier: ETF before stock; market order A->HK->US; symbol lexicographic
5. _sort_search_results used by search_etf local-table path
"""
import pytest


class TestSearchSorting:
    """Z20: unified search sorting."""

    def _items(self):
        return [
            {"symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "510050", "name": "上证50ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "510880", "name": "红利ETF", "market": "A", "asset_type": "etf", "type": "etf"},
            {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "02800.HK", "name": "盈富基金", "market": "HK", "asset_type": "etf", "type": "etf"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "etf", "type": "etf"},
        ]

    def test_exact_code_ranks_first(self):
        from app.services.market_service import _sort_search_results

        items = self._items()
        result = _sort_search_results(items, "600519")
        assert result[0]["symbol"] == "600519"

    def test_code_prefix_before_name_exact(self):
        from app.services.market_service import _sort_search_results

        # keyword "510300": symbol 510300 exact, but also matches 510 prefix for others
        result = _sort_search_results(self._items(), "510300")
        symbols = [i["symbol"] for i in result]
        # 510300 exact code first, then 510050/510880 (code prefix)
        assert symbols[0] == "510300"
        assert symbols[1] == "510050"
        assert symbols[2] == "510880"

    def test_name_exact_before_name_prefix_before_contains(self):
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "A", "name": "沪深300ETF", "market": "A", "asset_type": "etf"},
            {"symbol": "B", "name": "沪深300ETF联接A", "market": "A", "asset_type": "etf"},
            {"symbol": "C", "name": "沪深300价值ETF", "market": "A", "asset_type": "etf"},
            {"symbol": "D", "name": "中证沪深300指数", "market": "A", "asset_type": "etf"},
        ]
        result = _sort_search_results(items, "沪深300")
        # exact name (沪深300ETF) first, then prefix (沪深300ETF联接A), then contains
        assert result[0]["symbol"] == "A"
        assert result[1]["symbol"] == "B"
        # C and D are contains matches; 沪深300价值ETF vs 中证沪深300指数 both contain,
        # symbol lexicographic decides: C before D
        assert result[2]["symbol"] == "C"
        assert result[3]["symbol"] == "D"

    def test_etf_before_stock_same_tier(self):
        """Z20: 同档（同 tier）内 ETF 优先于个股。"""
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "600519", "name": "贵州茅台股", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "510300", "name": "贵州茅台ETF", "market": "A", "asset_type": "etf", "type": "etf"},
        ]
        result = _sort_search_results(items, "贵州茅台")
        # 两者都是名称前缀匹配（tier 4）→ 同档内 ETF 在前
        assert result[0]["symbol"] == "510300"
        assert result[1]["symbol"] == "600519"

    def test_exact_name_beats_etf_priority(self):
        """Z20: 档位优先于 ETF 规则 — 精确名称(股票)排在名称前缀(ETF)之前。"""
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"},
            {"symbol": "510300", "name": "贵州茅台ETF", "market": "A", "asset_type": "etf", "type": "etf"},
        ]
        result = _sort_search_results(items, "贵州茅台")
        assert result[0]["symbol"] == "600519"  # tier 3 (exact name)
        assert result[1]["symbol"] == "510300"  # tier 4 (name prefix)

    def test_market_order_and_symbol_lexicographic(self):
        from app.services.market_service import _sort_search_results

        items = [
            {"symbol": "SPY", "name": "SPDR 美股", "market": "US", "asset_type": "etf"},
            {"symbol": "02800.HK", "name": "SPDR 港股", "market": "HK", "asset_type": "etf"},
            {"symbol": "510300", "name": "SPDR 概念", "market": "A", "asset_type": "etf"},
        ]
        result = _sort_search_results(items, "SPDR")
        markets = [i["market"] for i in result]
        assert markets == ["A", "HK", "US"]

    def test_ordering_deterministic(self):
        """Same input twice -> same output."""
        from app.services.market_service import _sort_search_results

        items = self._items()
        r1 = _sort_search_results(items, "510")
        r2 = _sort_search_results(items, "510")
        assert [i["symbol"] for i in r1] == [i["symbol"] for i in r2]


class TestSearchEtfSorting:
    """Z20: search_etf local-table path applies the sorting contract."""

    @pytest.mark.asyncio
    async def test_search_etf_sorted(self):
        from app.services import market_service as ms
        from app.models.search import Instrument
        from unittest.mock import patch

        rows = [
            Instrument(symbol="510880", name="红利ETF", market="A", asset_type="etf"),
            Instrument(symbol="510300", name="沪深300ETF", market="A", asset_type="etf"),
            Instrument(symbol="510050", name="上证50ETF", market="A", asset_type="etf"),
        ]

        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return rows

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, stmt):
                return FakeResult()

        with patch.object(ms, "async_session", lambda: FakeSession()):
            result = await ms.search_etf("510")

        symbols = [r["symbol"] for r in result]
        # All three are code-prefix matches -> symbol lexicographic ascending
        assert symbols == ["510050", "510300", "510880"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])