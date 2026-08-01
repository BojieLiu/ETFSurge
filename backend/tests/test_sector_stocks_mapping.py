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
