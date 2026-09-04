# -*- coding: utf-8 -*-
"""R178 (round52 §9.2 方案A): /news/all 三桶去重合并端点。

round52 §9.1: 资讯页 5 tab 桶间互斥，无「全部」聚合视图；hub 已有合并缓存
`_news_cache`（headlines+macro+global 顺序拼接）但无 HTTP 端点（仅 mcp 消费）。
方案A：新增 GET /news/all——三桶合并 + **跨桶 id 去重**（F29 实测桶间有重复史）
+ sort_time 降序 + 上限 60 + partial 头（复用 _with_partial_flag）。

负向断言（能失败的）：
- 跨桶重复 id 必须去重（旧无端点 → 404，合并不去重 → 重复条目 → FAIL）；
- sort_time 降序；
- 合并 < PARTIAL_THRESHOLD → X-News-Partial: true；
- stock/research 不参与（端点不调 fetch_stock_news）。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _item(nid, title, sort_time, level=3, bucket="headlines"):
    return {"id": nid, "title": title, "time": "2026-09-03 12:00:00",
            "sort_time": sort_time, "level": level, "category": "positive",
            "stars": 4, "source": "X", "bucket": bucket}


def _hub_with_buckets(headlines, macro, global_):
    """构建带桶的 fake hub（复用真 NewsMixin.get_news_all 逻辑）。

    _news_cache_ts 设为当前时间——否则 _news_bucket 判过期会触发真刷新（触网）。"""
    import time as _time
    from app.services.hub._news import NewsMixin

    hub = NewsMixin.__new__(NewsMixin)
    hub._news_buckets = {"headlines": headlines, "macro": macro, "global": global_}
    hub._news_cache = None
    hub._news_cache_ts = _time.time()
    return hub


@pytest.mark.asyncio
async def test_news_all_merges_and_dedupes_by_id():
    """负向核心：跨桶重复 id 必须去重 + sort_time 降序。"""
    from app.routers import news as news_router

    h = [_item("a", "头条1", 100), _item("dup", "重复条目", 90)]
    m = [_item("dup", "重复条目", 90, bucket="macro"), _item("b", "宏观1", 80)]
    g = [_item("c", "国际1", 70)]

    hub = _hub_with_buckets(h, m, g)
    out = hub.get_news_all()
    ids = [it["id"] for it in out]
    assert len(ids) == len(set(ids)), f"跨桶重复 id 未去重：{ids}"
    assert "dup" in ids, "重复条目应保留一次而非全弃"
    assert out[0]["sort_time"] >= out[-1]["sort_time"], "必须 sort_time 降序"
    assert len(out) == 4, f"三桶 5 条去重后 4 条，实际 {len(out)}"


@pytest.mark.asyncio
async def test_news_all_respects_cap_60():
    """合并结果上限 60。"""
    from app.routers import news as news_router

    h = [_item(f"h{i}", f"头条{i}", 1000 - i) for i in range(40)]
    m = [_item(f"m{i}", f"宏观{i}", 500 - i) for i in range(40)]
    hub = _hub_with_buckets(h, m, [])
    out = hub.get_news_all()
    assert len(out) == 60, f"上限 60，实际 {len(out)}"


@pytest.mark.asyncio
async def test_news_all_endpoint_partial_header_and_empty():
    """端点层：冷启动空桶 → [] + partial=true；正常 → partial=false。"""
    from app.routers import news as news_router

    # 空桶：partial 必须为 true（诚实标注，不静默上屏空列表）
    hub = _hub_with_buckets([], [], [])
    with patch.object(news_router.market_data_hub, "get_news_all",
                      new=lambda: hub.get_news_all()):
        resp = await news_router.all_news()
        assert resp.status_code == 200
        assert resp.headers["x-news-partial"] == "true"
        assert resp.body  # JSON "[]"

    # 正常三桶（合计 ≥ PARTIAL_THRESHOLD=5）→ partial=false
    hub2 = _hub_with_buckets(
        [_item("a", "头条1", 100), _item("a2", "头条2", 95), _item("a3", "头条3", 92)],
        [_item("b", "宏观1", 90), _item("b2", "宏观2", 85)],
        [_item("c", "国际1", 80)])
    with patch.object(news_router.market_data_hub, "get_news_all",
                      new=lambda: hub2.get_news_all()):
        resp2 = await news_router.all_news()
        assert resp2.headers["x-news-partial"] == "false"


@pytest.mark.asyncio
async def test_news_all_endpoint_no_stock_research_sources():
    """stock/research 按标的查询型端点不参与合并（不发请求）。"""
    from app.routers import news as news_router

    def _boom(*a, **kw):
        raise AssertionError("stock/research 源不得参与 /news/all")

    hub = _hub_with_buckets([_item("a", "头条", 100)], [], [])
    with patch.object(news_router.market_data_hub, "get_news_all",
                      new=lambda: hub.get_news_all()), \
         patch("app.fetchers.news_fetcher.fetch_stock_news", new=_boom), \
         patch("app.fetchers.news_fetcher.fetch_research_reports", new=_boom):
        resp = await news_router.all_news()
        assert resp.status_code == 200
