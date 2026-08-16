"""
O3 (docs/archived/round7-rediagnosis.md §7 P3): sync_instruments 补 US 段。

P3 根因: collect_all() 只打包 A 股/A股ETF/HK 三段，US 段未实现 →
instruments 表 US=0 → 个股名称搜索（AAPL/苹果 等）空。

修复: collect_all() 增加 US 段（stock_us_spot_em，market="US", asset_type="US"），
独立行数统计 + 失败段打 ERROR（与既有段一致）。
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.fetchers.sync_instruments import collect_all


async def test_collect_all_includes_us_segment():
    """collect_all 含 US 段——US 行合并进结果。"""
    us_rows = [{"symbol": "AAPL", "name": "苹果", "market": "US", "asset_type": "US"},
               {"symbol": "TSLA", "name": "特斯拉", "market": "US", "asset_type": "US"}]
    a_rows = [{"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock"}]

    async def fake_fetch_a():
        return a_rows

    async def fake_fetch_akshare(fn_name, symbol_col, name_col, market, asset_type):
        if fn_name == "stock_us_spot_em":
            return us_rows
        return []

    with patch("app.fetchers.sync_instruments._fetch_a_stock_list", new=fake_fetch_a), \
         patch("app.fetchers.sync_instruments._fetch_akshare_list", new=fake_fetch_akshare):
        merged = await collect_all()

    markets = {r["market"] for r in merged}
    assert "US" in markets, "US 段应出现在 collect_all 结果"
    us = [r for r in merged if r["market"] == "US"]
    assert len(us) == 2
    assert {r["symbol"] for r in us} == {"AAPL", "TSLA"}
    assert all(r["asset_type"] == "US" for r in us)


async def test_us_segment_failure_isolated():
    """US 段失败 → 只丢 US，A/HK 段不受影响（gather return_exceptions）。"""
    a_rows = [{"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock"}]

    async def fake_fetch_a():
        return a_rows

    async def fake_fetch_akshare(fn_name, symbol_col, name_col, market, asset_type):
        if fn_name == "stock_us_spot_em":
            raise RuntimeError("us source down")
        return []

    with patch("app.fetchers.sync_instruments._fetch_a_stock_list", new=fake_fetch_a), \
         patch("app.fetchers.sync_instruments._fetch_akshare_list", new=fake_fetch_akshare):
        merged = await collect_all()

    assert any(r["market"] == "A" for r in merged), "A 段应保留"
    assert not any(r["market"] == "US" for r in merged), "US 段失败应被隔离"
