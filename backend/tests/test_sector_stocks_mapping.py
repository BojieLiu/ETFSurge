from __future__ import annotations
"""TDD: F1-6 — 板块成分股映射修复。

背景：`_ak_sector_stocks` 用板块代码（BK0447）直接调
`ak.stock_board_industry_cons_em(symbol=代码)`，而 akshare 该接口需要
**板块名称** → 传入代码返回错误数据（半导体板块返回软件股等错位成分）。

覆盖：
  1. _ak_sector_stocks 先做 代码→名称 映射（industry/concept 两张表）再用名称查询
  2. industry 查不到 → 降级 concept 名称查询
  3. hub.get_sector_stocks(BK0447) 返回半导体成分股（名称正确）
"""
import pytest
from unittest.mock import patch, MagicMock


# ── 1. 代码→名称映射 ───────────────────────────────────────────

def test_ak_sector_stocks_uses_name_mapping(monkeypatch):
    """传入代码 BK0447 → 用映射出的名称「半导体」调 industry_cons_em。"""
    from app.fetchers import sector_fetcher

    captured = {"industry_symbol": None}

    class _FakeAk:
        @staticmethod
        def stock_board_industry_name_em():
            import pandas as pd
            return pd.DataFrame([
                {"板块代码": "BK0447", "板块名称": "半导体"},
                {"板块代码": "BK0475", "板块名称": "银行"},
            ])

        @staticmethod
        def stock_board_concept_name_em():
            import pandas as pd
            return pd.DataFrame([])

        @staticmethod
        def stock_board_industry_cons_em(symbol=None):
            captured["industry_symbol"] = symbol
            import pandas as pd
            return pd.DataFrame([
                {"代码": "688981", "名称": "中芯国际"},
                {"代码": "603986", "名称": "兆易创新"},
            ])

        @staticmethod
        def stock_board_concept_cons_em(symbol=None):
            return None

    monkeypatch.setitem(__import__("sys").modules, "akshare", _FakeAk())
    result = sector_fetcher._ak_sector_stocks("BK0447")
    assert captured["industry_symbol"] == "半导体", \
        f"应使用名称查询，实际: {captured['industry_symbol']}"
    assert result and any(r["stock_code"] == "688981" for r in result)


# ── 2. industry 失败 → concept 降级 ────────────────────────────

def test_ak_sector_stocks_falls_back_to_concept(monkeypatch):
    """industry_cons_em 抛错 → 降级 concept_cons_em（仍用名称）。"""
    from app.fetchers import sector_fetcher

    captured = {"concept_symbol": None}

    class _FakeAk:
        @staticmethod
        def stock_board_industry_name_em():
            import pandas as pd
            return pd.DataFrame([{"板块代码": "BK0447", "板块名称": "半导体"}])

        @staticmethod
        def stock_board_concept_name_em():
            import pandas as pd
            return pd.DataFrame([{"板块代码": "BK0447", "板块名称": "半导体"}])

        @staticmethod
        def stock_board_industry_cons_em(symbol=None):
            raise RuntimeError("industry board not found")

        @staticmethod
        def stock_board_concept_cons_em(symbol=None):
            captured["concept_symbol"] = symbol
            import pandas as pd
            return pd.DataFrame([
                {"代码": "688981", "名称": "中芯国际"},
                {"代码": "002371", "名称": "北方华创"},
            ])

    monkeypatch.setitem(__import__("sys").modules, "akshare", _FakeAk())
    result = sector_fetcher._ak_sector_stocks("BK0447")
    assert captured["concept_symbol"] == "半导体"
    assert result and any(r["stock_code"] == "688981" for r in result)


# ── 3. 名称输入兼容（不破坏既有行为） ─────────────────────────

def test_ak_sector_stocks_name_input_works(monkeypatch):
    """直接传名称（非代码）仍可用（老调用方）。"""
    from app.fetchers import sector_fetcher

    captured = {"industry_symbol": None}

    class _FakeAk:
        @staticmethod
        def stock_board_industry_name_em():
            import pandas as pd
            return pd.DataFrame([{"板块代码": "BK0447", "板块名称": "半导体"}])

        @staticmethod
        def stock_board_concept_name_em():
            import pandas as pd
            return pd.DataFrame([])

        @staticmethod
        def stock_board_industry_cons_em(symbol=None):
            captured["industry_symbol"] = symbol
            import pandas as pd
            return pd.DataFrame([{"代码": "688981", "名称": "中芯国际"}])

        @staticmethod
        def stock_board_concept_cons_em(symbol=None):
            return None

    monkeypatch.setitem(__import__("sys").modules, "akshare", _FakeAk())
    result = sector_fetcher._ak_sector_stocks("半导体")
    assert captured["industry_symbol"] == "半导体"
    assert result


# ── 4. hub.get_sector_stocks 链路 ──────────────────────────────

def test_hub_get_sector_stocks_bk_code(monkeypatch):
    """hub.get_sector_stocks(BK0447) → 半导体成分股（经 akshare 名称映射）。"""
    import sys
    from app.services.market_data_hub import market_data_hub
    from app.fetchers import sector_fetcher
    from app.services.cache_service import sync_memory_cache

    # 清掉前序测试可能写入的缓存（sector_stocks 有全局内存缓存）
    sync_memory_cache.clear()

    # levistock 失败 → 走 akshare 路径（patch 模块属性，sys.modules 方式
    # 对已绑定的 `import levistock as lv` 无效）
    fake_lv = type("FakeLv", (), {})()
    fake_lv.sector_stocks_em = lambda code: None
    monkeypatch.setattr(sector_fetcher, "lv", fake_lv)

    class _FakeAk:
        @staticmethod
        def stock_board_industry_name_em():
            import pandas as pd
            return pd.DataFrame([{"板块代码": "BK0447", "板块名称": "半导体"}])

        @staticmethod
        def stock_board_concept_name_em():
            import pandas as pd
            return pd.DataFrame([])

        @staticmethod
        def stock_board_industry_cons_em(symbol=None):
            import pandas as pd
            return pd.DataFrame([
                {"代码": "688981", "名称": "中芯国际"},
                {"代码": "603986", "名称": "兆易创新"},
            ])

        @staticmethod
        def stock_board_concept_cons_em(symbol=None):
            return None

    monkeypatch.setitem(sys.modules, "akshare", _FakeAk())
    result = market_data_hub.get_sector_stocks("BK0447")
    names = [r.get("stock_name") for r in result]
    assert "中芯国际" in names, f"应返回半导体成分股: {names}"


# ===== folded from test_z25_stock_hot_rank.py =====
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
