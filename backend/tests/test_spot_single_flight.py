# -*- coding: utf-8 -*-
"""F9 R27: spot 全量列表 single-flight——缓存 miss 时同 key 并发只 fetch 一次。

无网络，纯 mock：验证并发调用共享一次 fetch 结果。
"""
import threading
import time
from unittest.mock import patch

from app.fetchers import china_market as cm
from app.services.cache_service import sync_memory_cache


def test_single_flight_concurrent_shared():
    """R27: 两个并发调用同 key → fetch_fn 只执行一次，两者拿到相同结果。"""
    sync_memory_cache.set("hk_spot_list", None, 0)  # 确保缓存 miss
    # 直接删缓存 key（MemoryCache.set 用 None 不一定清 key）
    try:
        sync_memory_cache.delete("hk_spot_list")
    except Exception:
        pass

    fetch_count = 0
    fetch_lock = threading.Lock()

    def fake_fetch():
        nonlocal fetch_count
        with fetch_lock:
            fetch_count += 1
        time.sleep(0.2)  # 模拟慢网络，让并发窗口出现
        rows = [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}]
        sync_memory_cache.set("hk_spot_list", rows, 600)
        return rows

    results = []
    errors = []

    def caller():
        try:
            results.append(cm._spot_single_flight("hk_spot_list", fake_fetch))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=caller)
    t2 = threading.Thread(target=caller)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors
    assert fetch_count == 1, f"fetch 执行 {fetch_count} 次（应 1 次）"
    assert len(results) == 2
    assert results[0] == results[1] == [{"symbol": "00700", "name": "腾讯控股", "market": "HK"}]
    # inflight 已清理
    assert "hk_spot_list" not in cm._spot_inflight


def test_single_flight_cache_hit_skips_fetch():
    """R27: 缓存命中 → 不触发 fetch（直接返回缓存）。"""
    sync_memory_cache.set("us_spot_list", [{"symbol": "AAPL", "name": "苹果", "market": "US"}], 600)
    fetch_count = 0

    def fake_fetch():
        nonlocal fetch_count
        fetch_count += 1
        return []

    with patch("app.fetchers.china_market.fetch_us_spot_list",
               wraps=cm.fetch_us_spot_list):
        result = cm.fetch_us_spot_list()
    assert result[0]["symbol"] == "AAPL"
    # 缓存命中路径不经过 single-flight fetch
    assert "us_spot_list" not in cm._spot_inflight
