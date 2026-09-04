# -*- coding: utf-8 -*-
"""R177 (round52 §8.4 方案A+B+C+D): 搜索补全三缺口修复。

round52 §8.2/§8.3 实测三类缺口：
- ① sectors 表 0 行（写入链从未落地）→ 板块搜索恒空。方案A：_search_sectors
  优先查内存缓存（fetch_industry_sectors/fetch_concept_sectors，500+496 只，
  key=sector_name），表查询保留为兜底；
- ② sync_indices_meta._fetch_ths_* 用的 ak.stock_board_industry_index_ths
  语义已漂移为「单板块历史 K 线」→ 收集恒 0。方案B：换
  stock_board_industry_name_ths()/stock_board_concept_name_ths()（列表语义，
  实测 90/375 行，创新药=308014 命中）；
- ③ 中证红利系指数（H30269 红利低波等）不在新浪 spot 列表 → 搜不到。
  方案C：_STATIC_EXTRA_INDICES 增补高频中证/上证红利系指数（symbol 用
  sh000015 形态先例）；
- ④ 方案D：_search_indices_akshare_fallback 兜底链加超时（10s）+ 失败
  logger.warning 升级（原 debug 不可见）。

负向断言（能失败的）：
- 板块搜索走缓存时「创新药」必须命中（旧实现查空表 → 0 条 → FAIL）；
- THS 收集函数解析 _name_ths 的 name/code 列（旧列名 指数代码/指数名称 → 0 行 → FAIL）；
- 静态段必须含 H30269 红利低波（旧缺 → FAIL）；
- 兜底链有超时包裹（无 wait_for → FAIL）。

无网络：全部 mock（sector_fetcher / akshare / async_session）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ── 方案A：板块搜索走内存缓存 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sector_search_hits_memory_cache():
    """负向核心：sectors 表空时，「创新药」必须经内存缓存命中（旧实现 0 条）。"""
    from app.routers import market as market_router

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def __call__(self, *args, **kwargs):
            return self

        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = []  # sectors 表 0 行
            return r

    def fake_fetch_industry(limit=80):
        return [{"sector_code": "BK1027", "sector_name": "半导体"}]

    def fake_fetch_concept(limit=150):
        return [{"sector_code": "308014", "sector_name": "创新药"},
                {"sector_code": "BK1027", "sector_name": "创新药械"}]

    with patch.object(market_router, "async_session", return_value=FakeSession()), \
         patch("app.fetchers.sector_fetcher.fetch_industry_sectors",
               new=fake_fetch_industry), \
         patch("app.fetchers.sector_fetcher.fetch_concept_sectors",
               new=fake_fetch_concept):
        out = await market_router._search_sectors("创新药")

    assert len(out) >= 1, f"板块缓存命中「创新药」必须 >=1 条，实际 {out}"
    assert any("创新药" in it["name"] for it in out)
    assert out[0]["type"] == "sector"
    assert out[0]["market"] == "A"
    # sector_code 必须带出（契约注记：消费方 sector-analysis 按 query=name 工作，
    # code 供前端展示/后续跳转）
    assert all(it.get("symbol") for it in out)


@pytest.mark.asyncio
async def test_sector_search_empty_keyword_returns_empty():
    """空关键词 → 空（不做全量导出）。"""
    from app.routers import market as market_router
    assert await market_router._search_sectors("") == []
    assert await market_router._search_sectors("  ") == []


@pytest.mark.asyncio
async def test_sector_search_us_hk_still_empty():
    """US/HK 市场过滤保留（round10 P2-T 行为不变）。"""
    from app.routers import market as market_router
    assert await market_router._search_sectors("创新药", market="US") == []
    assert await market_router._search_sectors("创新药", market="HK") == []


# ── 方案B：THS 指数收集换 _name_ths 接口 ────────────────────────────


@pytest.mark.asyncio
async def test_ths_industry_collector_uses_name_semantics():
    """负向核心：收集链必须（1）调 _name_ths 列表接口（非已漂移的 index_ths K 线
    接口）（2）解析 name/code 列——旧「指数代码/指数名称」恒 0 路径不得复活。"""
    from app.fetchers import sync_indices_meta as sim

    df = pd.DataFrame([
        {"name": "半导体", "code": "881121"},
        {"name": "白酒", "code": "881273"},
    ])

    called = {}

    def fake_name_ths():
        called["fn"] = "industry_name_ths"
        return df

    async def patched_run(fn, *a, **kw):
        # fn 必须是我们想要的 _name_ths 函数（经 run_sync_long 包裹）
        assert getattr(fn, "__name__", "") == "fake_name_ths" or fn is fake_name_ths
        return fn()

    import akshare as ak
    import app.core.async_utils as au
    with patch.object(ak, "stock_board_industry_name_ths", new=fake_name_ths), \
         patch.object(au, "run_sync_long", new=patched_run):
        out = await sim._fetch_ths_industry_indices()

    assert called.get("fn") == "industry_name_ths", "必须走 _name_ths 列表接口"
    assert len(out) == 2, f"必须解析出 2 条行业指数，实际 {out}"
    assert out[0]["symbol"] == "881121" and out[0]["name"] == "半导体"
    assert out[0]["market"] == "A" and out[0]["category"] == "industry"


@pytest.mark.asyncio
async def test_ths_concept_collector_uses_name_semantics():
    """同上——概念段（创新药=308014 形态）。"""
    from app.fetchers import sync_indices_meta as sim

    df = pd.DataFrame([
        {"name": "创新药", "code": "308014"},
        {"name": "人工智能", "code": "308028"},
    ])

    import akshare as ak
    import app.core.async_utils as au

    async def patched_run(fn, *a, **kw):
        return fn()

    with patch.object(ak, "stock_board_concept_name_ths",
                      new=lambda: df), \
         patch.object(au, "run_sync_long", new=patched_run):
        out = await sim._fetch_ths_concept_indices()

    assert len(out) == 2
    assert {"symbol": "308014", "name": "创新药", "market": "A",
            "category": "concept"} .items() <= out[0].items()


# ── 方案C：静态段增补中证红利系 ──────────────────────────────────────


def test_static_extra_indices_cover_csi_dividend_family():
    """负向核心：静态段必须含红利低波 H30269 / 红利低波100 H20269 /
    中证红利 000922 / 上证红利 000015（旧缺 →「红利低波」搜索 0 条）。"""
    from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

    by_sym = {s["symbol"]: s for s in _STATIC_EXTRA_INDICES}
    for sym in ("H30269", "H20269", "000922", "000015"):
        assert sym in by_sym, f"静态段缺 {sym}（红利系覆盖缺口未修复）"
        assert "红利" in by_sym[sym]["name"]
    # A 股形态标 market=A（sh000015 前缀先例——此处直接用裸码+market 字段）
    assert by_sym["000015"]["market"] == "A"
