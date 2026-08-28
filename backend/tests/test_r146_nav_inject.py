"""R146: nav 注入（_inject_nav）测试 — premium_discount 通过 market_data 分支非 0。

原 nav IOPV 链只在 _fetch_market_data（DEPRECATED fallback），生产链路
（compute(market_data=cached_kline)）走 market_data 分支跳过 → premium_discount 恒 0.0。
本轮提取 _inject_nav 公共方法在两处复用。本测试验证：mock _fetch_iopv_chain 返回
nav → _inject_nav 注入成功 → _compute_premium_discount 非 0。
"""
from __future__ import annotations

import pytest

import app.factors.factor_registry as fr
from app.factors.factor_registry import _inject_nav, _compute_premium_discount


@pytest.fixture
def mock_iopv_chain(monkeypatch):
    """mock _fetch_iopv_chain 返回给定 nav/price。"""
    def _patch(nav: float, price: float, symbols: list[str]) -> None:
        async def fake_chain(_s_list, _symbols):
            return {
                sym: {"nav": nav, "price": price}
                for sym in _symbols
            }, "test"
        monkeypatch.setattr(fr, "_fetch_iopv_chain", fake_chain)
    return _patch


class TestInjectNav:
    @pytest.mark.asyncio
    async def test_nav_injected_when_iopv_returns_nav(self, mock_iopv_chain):
        """IOPV chain 命中 → nav/price 注入 → premium_discount 非 0。"""
        mock_iopv_chain(nav=4.1242, price=4.1250, symbols=["510300"])
        market_data = {"510300": {"close": 4.1250}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"]["nav"] == 4.1242
        assert market_data["510300"]["price"] == 4.1250
        pd = _compute_premium_discount(market_data["510300"])
        assert pd != 0.0, "premium_discount 应非 0（nav 已注入）"
        # (4.1250 - 4.1242)/4.1242 ≈ 0.000194
        assert abs(pd - 0.000194) < 0.0001

    @pytest.mark.asyncio
    async def test_nav_not_overwritten_when_no_iopv(self, mock_iopv_chain, monkeypatch):
        """IOPV chain 全空 → 沿用已有 nav（若已注入），不覆盖。"""
        mock_iopv_chain(nav=0, price=0, symbols=["510300"])  # nav=0 触发跳过
        market_data = {"510300": {"nav": 4.0, "price": 4.02, "close": 4.02}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"]["nav"] == 4.0, "已有 nav 不被覆盖"
        pd = _compute_premium_discount(market_data["510300"])
        assert pd != 0.0

    @pytest.mark.asyncio
    async def test_tjj_fallback_when_iopv_empty(self, mock_iopv_chain, monkeypatch):
        """IOPV chain 全空 → TTJ 兜底（patch market_data_hub.get_fund_nav）→ nav 注入。"""
        mock_iopv_chain(nav=0, price=0, symbols=["510300"])
        # run_sync 是模块级函数（app.core.async_utils），被 _inject_nav 局部导入。
        # patch 其模块属性使 _hub.get_fund_nav 短路返回 dict。
        import app.core.async_utils as au

        class FakeHub:
            async def get_fund_nav(self, sym, timeout=6):
                return {"nav": 4.2}

        async def fake_run_sync(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        monkeypatch.setattr(au, "run_sync", fake_run_sync)
        import app.services.market_data_hub as mdh

        monkeypatch.setattr(mdh, "market_data_hub", FakeHub())
        market_data = {"510300": {"close": 4.2}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"].get("nav") == 4.2, "TTJ 兜底应注入 nav"
        # TTJ 兜底仅注入 nav（无 price）——premium_discount 需 price+nav 双有才非 0；
        # 此处只验证 nav 兜底成功（诚实降级：价格缺失时不造 0）。
        assert "price" not in market_data["510300"]
