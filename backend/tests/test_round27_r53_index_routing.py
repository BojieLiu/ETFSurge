"""round27 R53 (P1): 美股/港股指数分析数据源未路由——接 global indices 实时源 + 新浪 K 线。

问题（round27 §2.9 / §15.1 R53）：`get_asset_realtime` 对 US/HK 指数显式返
`unsupported_market`（round16 P0-22④ 过防护），但 `_GLOBAL_INDEX_DEFS`（^GSPC/^IXIC/
^DJI/^HSI）经 `get_global_indices`/`_foreign` 真实拉取，数据源是通的只是没接；
符号错位（indices_meta 存 SPX vs global 用 ^GSPC）；`fetch_index_history` 只处理 HK/A，
US 指数被误路由。D1 探针已通过：新浪 `stock_us_daily('.INX')` = 5693 行。

修复（本轮）：
- `get_asset_realtime` index 分支路由 US/HK 到 `get_global_indices`，符号映射
  SPX→^GSPC / IXIC→^IXIC / DJI→^DJI / HSI→^HSI；
- `fetch_index_history` 增 US 分支（新浪 stock_us_daily，^GSPC→.INX）。

反假完成：负向断言——mock `_lookup_index_market` 返 US + 注入 global ^GSPC →
realtime 非 None 且无 `unsupported_market`；`fetch_index_history("^GSPC")` ≥250 行且
不误路由到 HK/A 分支。
"""

import pandas as pd
import pytest

from app.services import market_service as ms
from app.fetchers import china_market as cm


@pytest.fixture(autouse=True)
def _clear_rt_cache():
    """隔离：清空 N07 实时行情短缓存，避免跨用例 symbol 冲突导致误命中。"""
    ms._asset_realtime_cache.clear()
    yield



class TestIndexRealtimeRouting:
    """R53: US/HK 指数实时路由到 global indices（撤销过防护）。"""

    @pytest.mark.asyncio
    async def test_us_index_routed_to_global_no_unsupported(self, monkeypatch):
        """_lookup_index_market 返 US + 注入 global ^GSPC → realtime 非 None 且无 unsupported_market。"""
        async def _fake_lookup(symbol):
            return "US"
        monkeypatch.setattr(ms, "_lookup_index_market", _fake_lookup)
        async def _fake_gi():
            return {"美股": [{
                "symbol": "^GSPC", "name": "标普500", "price": 5000.0,
                "change_pct": 1.2, "change_amount": 60.0, "available": True,
            }]}
        monkeypatch.setattr(ms, "get_global_indices", _fake_gi)

        res = await ms.get_asset_realtime("SPX", "index")
        assert res is not None, "US 指数实时必须路由到 global indices（R53）"
        assert "unsupported_market" not in res, "过防护的 unsupported_market 必须移除（R53）"
        assert res["price"] == 5000.0
        assert res["asset_type"] == "index"
        assert res["market"] == "US"

    @pytest.mark.asyncio
    async def test_symbol_map_spx_to_gspc(self, monkeypatch):
        """符号映射 SPX→^GSPC 命中 global 源（经 SPX 查到 ^GSPC 条目）。"""
        async def _fake_lookup(symbol):
            return "US"
        monkeypatch.setattr(ms, "_lookup_index_market", _fake_lookup)
        # 故意只放 ^GSPC（Yahoo 代码），验证 SPX 输入也能映射命中
        async def _fake_gi():
            return {"美股": [{
                "symbol": "^GSPC", "name": "标普500", "price": 4999.0,
                "change_pct": -0.3, "change_amount": -15.0, "available": True,
            }]}
        monkeypatch.setattr(ms, "get_global_indices", _fake_gi)

        res = await ms.get_asset_realtime("SPX", "index")
        assert res is not None
        assert res["price"] == 4999.0
        assert "unsupported_market" not in res

    @pytest.mark.asyncio
    async def test_hk_index_routed_to_global(self, monkeypatch):
        """HK 指数（HSI）同样路由到 global indices，而非 unsupported_market。"""
        async def _fake_lookup(symbol):
            return "HK"
        monkeypatch.setattr(ms, "_lookup_index_market", _fake_lookup)
        async def _fake_gi():
            return {"港股": [{
                "symbol": "^HSI", "name": "恒生指数", "price": 18000.0,
                "change_pct": 0.8, "change_amount": 140.0, "available": True,
            }]}
        monkeypatch.setattr(ms, "get_global_indices", _fake_gi)

        res = await ms.get_asset_realtime("HSI", "index")
        assert res is not None
        assert res["price"] == 18000.0
        assert "unsupported_market" not in res


class TestIndexHistoryRouting:
    """R53: 美股指数 K 线走新浪 stock_us_daily，不误路由到 HK/A。"""

    def test_us_index_history_not_misrouted(self, monkeypatch):
        """fetch_index_history("^GSPC") ≥250 行且未误路由到 HK 腾讯 / A akshare 分支。"""
        import akshare

        rows = [{
            "date": f"2020-01-{i:02d}" if i < 30 else f"2020-02-{i-29:02d}",
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100,
        } for i in range(1, 300)]
        df = pd.DataFrame(rows)
        monkeypatch.setattr(akshare, "stock_us_daily", lambda symbol: df)

        hk_calls = []
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda s: (hk_calls.append(s) or []))
        ak_calls = []
        monkeypatch.setattr(
            akshare, "stock_zh_index_daily",
            lambda symbol: (ak_calls.append(symbol) or pd.DataFrame()),
        )

        out = cm.fetch_index_history("^GSPC")
        assert len(out) >= 250, "US 指数 K 线必须 ≥250 行（R53，探针 5693 行）"
        assert hk_calls == [], "US 指数不得误路由到 HK 腾讯分支（R53）"
        assert ak_calls == [], "US 指数不得误路由到 A akshare 分支（R53）"

    def test_us_index_history_symbol_map_gspc_to_inx(self, monkeypatch):
        """符号映射 ^GSPC→.INX 被新浪 stock_us_daily 实际接收。"""
        import akshare

        captured = {}
        df = pd.DataFrame([{
            "date": "2020-01-01", "open": 1.0, "high": 2.0, "low": 0.5,
            "close": 1.5, "volume": 100,
        }])
        def _fake(symbol):
            captured["symbol"] = symbol
            return df
        monkeypatch.setattr(akshare, "stock_us_daily", _fake)

        cm.fetch_index_history("^GSPC")
        assert captured["symbol"] == ".INX", "美股指数历史必须映射 ^GSPC→.INX（R53）"

    def test_spx_index_history_mapped_to_inx(self, monkeypatch):
        """indices_meta 存的 SPX 也能映射到 .INX（符号错位修复）。"""
        import akshare

        captured = {}
        df = pd.DataFrame([{
            "date": "2020-01-01", "open": 1.0, "high": 2.0, "low": 0.5,
            "close": 1.5, "volume": 100,
        }])
        monkeypatch.setattr(akshare, "stock_us_daily", lambda symbol: (captured.update(symbol=symbol) or df))

        cm.fetch_index_history("SPX")
        assert captured["symbol"] == ".INX", "SPX 也必须映射到 .INX（R53）"
