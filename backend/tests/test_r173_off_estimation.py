# -*- coding: utf-8 -*-
"""R173 (round52 §7.3 方案A+B): /market/realtime/portfolio 场外估值断链。

round52 §7.1 实测（盘中 11:31-11:35）：场外 15 只 change_pct 全 0、
estimate_source='nav'。根因：盘中分支条件 `now_trading and ti in index_price_map`
的 index_price_map 键集 = 8 个指数代码（000001/399001/...），而场外联接基金
tracked_index 存的是**场内 ETF 代码**（022449→159338、011613→588000）→ 条件恒 False
→ 全部落入 fetch_fund_nav 分支，该分支硬编码 `"change_pct": 0`（:1278）——
nav 分支连 T-1 涨跌都没用上。估值源数据（ti 场内实时行情）就在同一响应的
quotes 里（a_symbols 已含 ti），只是没被查。

方案 A（盘中治本）：盘中优先查 quotes 内 ti 的实时报价（get_realtime_batch
已捎带场内 ETF），change_pct 逐只一致；`ti in index_price_map` 分支保留为
ti=指数代码形态的兼容。

方案 B（盘后兜底）：fetch_fund_nav 分支 change_pct 从硬编码 0 改为
`float(nav_data["daily_change_pct"])`（fetch_fund_nav 契约已含该字段，实测 -1.42），
字段缺失/非法时诚实回 0.0（不再有真实数据可用而显示假 0 的路径）。

负向断言（能失败的）：
- 盘中 + ti 有场内报价 → off 条目 change_pct == ti 报价值（旧代码恒 0 → FAIL）；
- 盘后 nav daily_change_pct=-1.42 → off 条目 change_pct == -1.42（旧代码恒 0 → FAIL）；
- ti=指数代码（000300）→ 原指数映射分支行为不变（兼容守卫）。

无网络：全部 mock（list_etfs / get_realtime_batch / _call / is_trading_time）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_fake_session(off_list):
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def __call__(self, *args, **kwargs):
            return self

        async def execute(self, *args, **kwargs):
            r = MagicMock()
            r.scalars.return_value.all.return_value = off_list
            return r

    return FakeSession()


class _FakeEtf:
    def __init__(self, sym, ti, name=None):
        self.symbol = sym
        self.name = name or f"fund_{sym}"
        self.short_name = self.name[:6]
        self.tracked_index = ti
        self.portfolio_type = "off_exchange"


def _run(off_list, *, trading: bool, batch_quotes, index_quotes, nav_by_sym):
    """统一执行 get_portfolio_realtime(phase='slow') 并返回 quotes。"""
    from app.services import market_service

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return index_quotes
        if fn_name == "fetch_fund_nav":
            sym = args[0] if args else kwargs.get("symbol")
            return nav_by_sym.get(sym)
        raise AssertionError(f"unexpected _call: {fn_name}")

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off_list])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=batch_quotes)), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=trading), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off_list)):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            market_service.get_portfolio_realtime(phase="slow")
        ) if False else None


# pytest-asyncio auto 模式：直接 async def
@pytest.mark.asyncio
async def test_trading_time_uses_tracked_etf_quote_from_batch():
    """方案A核心（负向断言）：盘中 off 条目 change_pct 必须等于 ti 场内报价。

    旧代码：ti=159338（ETF 代码）不在 8 指数键集 → 恒走 nav 分支 → change_pct=0。
    """
    from app.services import market_service

    # 场内标的 159338 的实时报价由 get_realtime_batch 返回（a_symbols 已含 ti）
    batch = [
        {"symbol": "159338", "name": "中证A500ETF", "price": 1.205,
         "change_pct": 0.5, "change_amount": 0.006, "volume": 100},
    ]
    off = [_FakeEtf("022449", "159338")]

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        if fn_name == "fetch_fund_nav":
            return {"nav": 1.1751, "daily_change_pct": -1.42, "nav_date": "2026-09-02"}
        raise AssertionError(fn_name)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=batch)), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=True), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off)):
        quotes = await market_service.get_portfolio_realtime(phase="slow")

    off_q = next(q for q in quotes if q["symbol"] == "022449")
    assert off_q["change_pct"] == pytest.approx(0.5), (
        f"盘中 off 估值必须取 ti 场内实时涨跌，实际 {off_q['change_pct']}"
    )
    assert off_q["price"] == pytest.approx(1.205)
    assert off_q["is_estimated"] is True
    assert off_q["estimate_source"] == "tracked_index"


@pytest.mark.asyncio
async def test_trading_time_index_code_ti_still_uses_index_map():
    """兼容守卫：ti=指数代码（000300）→ 原指数映射分支行为不变。"""
    from app.services import market_service

    off = [_FakeEtf("510300联接", "000300")]
    index_quotes = [{"symbol": "000300", "name": "沪深300", "price": 4000.0,
                     "change_pct": 1.2, "change_amount": 47.0}]

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return index_quotes
        if fn_name == "fetch_fund_nav":
            return None
        raise AssertionError(fn_name)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=True), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off)):
        quotes = await market_service.get_portfolio_realtime(phase="slow")

    off_q = next(q for q in quotes if q["symbol"] == "510300联接")
    assert off_q["change_pct"] == pytest.approx(1.2)
    assert off_q["price"] == pytest.approx(4000.0)
    assert off_q["estimate_source"] == "tracked_index"


@pytest.mark.asyncio
async def test_after_hours_nav_uses_daily_change_pct_not_zero():
    """方案B（负向断言）：盘后 nav 分支 change_pct 用 daily_change_pct（-1.42），
    不得硬编码 0 冒充真实涨跌。"""
    from app.services import market_service

    off = [_FakeEtf("022449", "159338")]

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        if fn_name == "fetch_fund_nav":
            return {"nav": 1.1751, "daily_change_pct": -1.42, "nav_date": "2026-09-02"}
        raise AssertionError(fn_name)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off)):
        quotes = await market_service.get_portfolio_realtime(phase="slow")

    off_q = next(q for q in quotes if q["symbol"] == "022449")
    assert off_q["change_pct"] == pytest.approx(-1.42), (
        f"盘后 nav 分支必须用 T-1 净值涨跌，实际 {off_q['change_pct']}（硬编码 0 = 假值）"
    )
    assert off_q["price"] == pytest.approx(1.1751)
    assert off_q["estimate_source"] == "nav"


@pytest.mark.asyncio
async def test_nav_change_pct_missing_or_bad_is_honest_zero():
    """方案B容错：daily_change_pct 缺失/非法 → 回 0.0（不 crash、不臆造）。"""
    from app.services import market_service

    off = [_FakeEtf("022449", "159338")]

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        if fn_name == "fetch_fund_nav":
            return {"nav": 1.1751, "nav_date": "2026-09-02"}  # 无 daily_change_pct
        raise AssertionError(fn_name)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off)):
        quotes = await market_service.get_portfolio_realtime(phase="slow")

    off_q = next(q for q in quotes if q["symbol"] == "022449")
    assert off_q["change_pct"] == 0.0
    assert off_q["estimate_source"] == "nav"


@pytest.mark.asyncio
async def test_nav_unavailable_keeps_last_close_source():
    """nav 拉取失败 → estimate_source='last_close'（既有行为保留）。"""
    from app.services import market_service

    off = [_FakeEtf("022449", "159338")]

    async def fake_call(fn, *args, **kwargs):
        fn_name = getattr(fn, "__name__", str(fn))
        if fn_name == "fetch_index_realtime":
            return []
        if fn_name == "fetch_fund_nav":
            raise RuntimeError("source down")
        raise AssertionError(fn_name)

    with patch.object(market_service, "cache_get", new=AsyncMock(return_value=None)), \
         patch.object(market_service, "cache_set", new=AsyncMock()), \
         patch("app.services.portfolio_service.list_etfs",
               new=AsyncMock(side_effect=[[], off])), \
         patch.object(market_service, "get_realtime_batch",
                      new=AsyncMock(return_value=[])), \
         patch.object(market_service, "_call", new=fake_call), \
         patch.object(market_service, "is_trading_time", return_value=False), \
         patch.object(market_service, "async_session",
                      return_value=_make_fake_session(off)):
        quotes = await market_service.get_portfolio_realtime(phase="slow")

    off_q = next(q for q in quotes if q["symbol"] == "022449")
    assert off_q["estimate_source"] == "last_close"
    assert off_q["change_pct"] == 0.0
