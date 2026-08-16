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