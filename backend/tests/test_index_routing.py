"""round25 R37: indices/global 冷启动返 0 条修复——磁盘 last-ok 懒加载兜底。

问题（round25 §0.3 R37 实证）：容器内 warmup 已拉取全球指数并落盘 indices_cache.json，
但端点 `GET /market/indices/global` 返 0 条。根因：`_global_indices_last_ok` 是模块级
内存态，模块 import 时 `_load_ok_cache()` 若磁盘缓存尚不存在则错过；此后 warmup 落盘
但端点再次冷拉失败（源冷却）时，内存 last_ok 仍空 → 无 last-good 可兜 → 返 {}（0 条）。

修复（round25 R37）：
- 异常路径：内存 last_ok 空 → 懒加载磁盘缓存（补上 warmup 落盘的数据）；
- 非交易时段全源空路径：同上懒加载（盘后端点即可读 T-1 数据，而非 0 条）。
"""

import json
from unittest.mock import patch

import pytest

from app.services import market_service as ms


class TestGlobalIndicesDiskFallback:
    """R37: 冷启动磁盘 last-ok 懒加载兜底。"""

    def test_load_ok_cache_populates_memory(self, tmp_path):
        """磁盘缓存可载入内存（_load_ok_cache 正确反序列化）。"""
        blob = {
            "ts": 1755200000.0,
            "data": {"美股": [{"symbol": "SPX", "name": "标普500", "price": 5000.0,
                              "available": True, "region": "美股"}]},
        }
        path = tmp_path / "indices_cache.json"
        path.write_text(json.dumps(blob), encoding="utf-8")
        monkey_patcher = patch.object(ms, "_get_cache_db_path", return_value=str(path))
        monkey_patcher.start()
        try:
            ok = ms._load_ok_cache()
            assert ok is True
            assert "美股" in ms._global_indices_last_ok
            assert ms._global_indices_last_ok["美股"][0]["symbol"] == "SPX"
        finally:
            monkey_patcher.stop()
            ms._global_indices_last_ok.clear()
            ms._global_indices_last_ok_ts = 0

    @pytest.mark.asyncio
    async def test_no_data_path_lazily_loads_disk_cache(self, tmp_path, monkeypatch):
        """非交易时段全源空 + 内存 last_ok 空 + 磁盘有缓存 → 懒加载返回 T-1 数据（非 0 条）。"""
        blob = {
            "ts": ms._GLOBAL_INDICES_OK_TTL - 100,  # 在 24h TTL 内
            "data": {"港股": [{"symbol": "HSI", "name": "恒生指数", "price": 18000.0,
                               "available": True, "region": "港股"}]},
        }
        path = tmp_path / "indices_cache.json"
        path.write_text(json.dumps(blob), encoding="utf-8")

        # 清空内存态
        ms._global_indices_last_ok.clear()
        ms._global_indices_last_ok_ts = 0
        ms._global_indices_cache = {}
        ms._global_indices_cache_ts = 0

        # 磁盘路径指向临时文件 + 模拟所有源返回空（has_data=False）
        monkeypatch.setattr(ms, "_get_cache_db_path", lambda: str(path))
        async def _defs():
            return [("HSI", "恒生指数", "港股")]
        monkeypatch.setattr(ms, "_global_index_defs", _defs)
        monkeypatch.setattr(ms, "_to_json_native", lambda x: x)
        monkeypatch.setattr(ms, "_enrich_market_status", lambda r: None)

        # _call 是模块级包装（fetch_index_realtime 等经 _call 调用）——让所有 fetch 返回空
        async def _call_empty(fn, *args, **kwargs):
            return [] if "realtime" in fn.__name__ else {}
        monkeypatch.setattr(ms, "_call", _call_empty)

        # run_sync 调用 sina/finnhub 源——同样返回空
        async def _run_sync_empty(fn, *args, timeout=4):
            return None
        monkeypatch.setattr(ms, "run_sync", _run_sync_empty)

        out = await ms.get_global_indices()
        assert "港股" in out, "冷启动非交易时段必须返回 T-1 港股数据（R37，非 0 条）"
        assert out["港股"][0]["symbol"] == "HSI"
        # 标注降级（available=False，诚实呈现 T-1）
        assert out["港股"][0]["available"] is False

        # 恢复内存态避免污染其它测试
        ms._global_indices_last_ok.clear()
        ms._global_indices_last_ok_ts = 0

    @pytest.mark.asyncio
    async def test_exception_path_lazily_loads_disk_cache(self, tmp_path, monkeypatch):
        """异常路径：内存空 + 磁盘有缓存 → 懒加载返回（而非 {}）。"""
        blob = {
            "ts": 1755200000.0,
            "data": {"美股": [{"symbol": "DJI", "name": "道琼斯", "price": 34000.0,
                               "available": True, "region": "美股"}]},
        }
        path = tmp_path / "indices_cache.json"
        path.write_text(json.dumps(blob), encoding="utf-8")

        ms._global_indices_last_ok.clear()
        ms._global_indices_last_ok_ts = 0
        ms._global_indices_cache = {}
        ms._global_indices_cache_ts = 0
        monkeypatch.setattr(ms, "_get_cache_db_path", lambda: str(path))

        # 强制 get_global_indices 抛异常
        async def _boom(*a, **k):
            raise RuntimeError("source down")

        monkeypatch.setattr(ms, "_global_index_defs", _boom)

        out = await ms.get_global_indices()
        assert out.get("美股"), "异常路径必须懒加载磁盘缓存（R37，非空 {}）"
        assert out["美股"][0]["symbol"] == "DJI"

        ms._global_indices_last_ok.clear()
        ms._global_indices_last_ok_ts = 0

    def test_exception_no_cache_returns_empty(self, tmp_path, monkeypatch):
        """异常 + 磁盘无缓存 → {}（诚实降级，不编造）。"""
        ms._global_indices_last_ok.clear()
        ms._global_indices_last_ok_ts = 0
        monkeypatch.setattr(ms, "_get_cache_db_path",
                            lambda: str(tmp_path / "nonexistent.json"))
        assert ms._load_ok_cache() is False
        assert ms._global_indices_last_ok == {}


# ── folded from test_round27_r53_index_routing.py ──
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