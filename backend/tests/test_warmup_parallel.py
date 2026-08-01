# -*- coding: utf-8 -*-
"""F2-5: 全球指数预热并行化（A 股 / EM / HK 三段拉取 gather 并行）。

验收：预热 < 1.0s。单测验证三段不再串行（总耗时 ≈ 最慢段，而非三段之和）。
"""
import time

import pytest

from app.services import market_service as ms


@pytest.mark.asyncio
async def test_global_indices_parallel(monkeypatch):
    """A 股 / EM / HK 三个数据段并行拉取：总耗时 < 三段耗时之和。"""
    order = []

    def fake_fetch_index_realtime():
        time.sleep(0.3)
        order.append("a")
        return []

    def fake_fetch_all():
        time.sleep(0.3)
        order.append("em")
        return {}

    def fake_fetch_hk_indices():
        time.sleep(0.3)
        order.append("hk")
        return {}

    import app.fetchers.china_market as cm
    import app.fetchers.global_markets_fetcher as gm

    monkeypatch.setattr(cm, "fetch_index_realtime", fake_fetch_index_realtime)
    monkeypatch.setattr(cm, "fetch_sina_global_index", lambda sym, timeout=4: None)
    monkeypatch.setattr(cm, "fetch_sina_page_global_index", lambda sym, timeout=4: None)
    monkeypatch.setattr(gm, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(gm, "fetch_hk_indices", fake_fetch_hk_indices)
    monkeypatch.setattr(gm, "fetch_realtime", lambda s, timeout=6: None)
    # 清 30s 内存缓存，确保走真实拉取路径
    ms._global_indices_cache = None
    ms._global_indices_cache_ts = 0.0

    start = time.monotonic()
    regions = await ms.get_global_indices()
    elapsed = time.monotonic() - start

    # 串行 = 0.9s；并行 = ~0.3s。取中间阈值 0.7s 判定并行。
    assert elapsed < 0.7, f"三段应并行（<0.7s），实际 {elapsed:.2f}s"
    # 三个数据段都被触达
    assert set(order) == {"a", "em", "hk"}
    # 返回结构完整（占位行）
    assert isinstance(regions, dict)
