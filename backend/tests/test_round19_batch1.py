"""
round19 批次 1 测试（P0 小改，2026-08-12 实施）：
- P7-③ watchlist 入库归一化（路由层 watchlist_add：sz301308 → 301308）
- P3-① add_etf / update_etf 落库 avg_cost/shares_held（此前传了被静默丢弃）

对照 §四十三 补强 #2（落库断言）：传值 → 落库/返回一致值；负向：丢弃 → FAIL。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


class TestWatchlistAddPrefixNormalized:
    """round19 P7-③: watchlist 入库统一归一化（手动输入带前缀不原样入库）。"""

    def _fake_session(self):
        """execute 顺序: ①查重 scalar_one_or_none → None（未重复）②instruments 补名 → None。"""
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            ]
        )
        session.add = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__.return_value = session
        cm.__aexit__.return_value = False
        return cm, session

    @pytest.mark.asyncio
    async def test_add_watchlist_with_prefix_stored_pure(self, monkeypatch):
        """POST watchlist 'sz301308'（带前缀）→ 落库 symbol 为 '301308'（负向：原样入库 → FAIL）。"""
        import app.routers.market as mr

        fake_cm, session = self._fake_session()
        monkeypatch.setattr(mr, "async_session", lambda: fake_cm)
        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", AsyncMock(return_value=None))
        monkeypatch.setattr(mr, "CODE_PATTERN", __import__("re").compile(r"^[0-9A-Za-z.\-]+$"))

        data = MagicMock()
        data.symbol = "sz301308"
        data.asset_type = "A"
        data.name = "江波龙"  # 前端搜索已带 name → 跳过实时验证
        data.notes = None

        resp = await mr.watchlist_add(data)

        assert resp["symbol"] == "301308", f"应归一化为 301308，实得 {resp['symbol']}"
        added = session.add.call_args[0][0]
        assert added.symbol == "301308", f"落库 symbol 应为 301308，实得 {added.symbol}"

    @pytest.mark.asyncio
    async def test_add_watchlist_pure_symbol_unchanged(self, monkeypatch):
        """不带前缀的规范 symbol 不受影响（回归：正常路径不误改）。"""
        import app.routers.market as mr

        fake_cm, session = self._fake_session()
        monkeypatch.setattr(mr, "async_session", lambda: fake_cm)
        monkeypatch.setattr(mr.market_data_hub, "get_asset_realtime", AsyncMock(return_value=None))

        data = MagicMock()
        data.symbol = "510300"
        data.asset_type = "A"
        data.name = "沪深300ETF"
        data.notes = None

        resp = await mr.watchlist_add(data)
        assert resp["symbol"] == "510300"


class TestPortfolioEtfPersistCost:
    """round19 P3-①: add_etf / update_etf 落库 avg_cost/shares_held（负向：丢弃 → FAIL）。"""

    @pytest.mark.asyncio
    async def test_add_etf_persists_avg_cost_and_shares(self):
        """add_etf 传 avg_cost/shares_held → 构造对象落库一致值（此前静默丢弃）。"""
        from app.services.portfolio_service import add_etf

        db = AsyncMock()
        db.refresh = AsyncMock()
        data = MagicMock()
        data.symbol = "510300"
        data.name = "沪深300ETF"
        data.short_name = None
        data.asset_type = "HK"  # 非 A 分支，避免 _resolve_tracked_index 网络依赖
        data.target_weight = 0.1
        data.portfolio_type = "on_exchange"
        data.tracked_index = None
        data.avg_cost = 4.62
        data.shares_held = 5000
        data.first_buy_date = None
        data.last_trade_date = None

        etf = await add_etf(db, data)
        assert etf.avg_cost == 4.62, f"avg_cost 应落库，实得 {etf.avg_cost}"
        assert etf.shares_held == 5000, f"shares_held 应落库，实得 {etf.shares_held}"

    @pytest.mark.asyncio
    async def test_update_etf_persists_avg_cost_and_shares(self):
        """update_etf 传 avg_cost/shares_held → 对象更新一致值（此前传了不生效）。"""
        from app.services.portfolio_service import update_etf

        class FakeEtf:
            avg_cost = None
            shares_held = None
            name = "沪深300ETF"
            target_weight = 0.1
            is_active = True
            portfolio_type = "on_exchange"
            short_name = None
            tracked_index = None
            first_buy_date = None
            last_trade_date = None

        etf_obj = FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf_obj))
        db.refresh = AsyncMock()

        data = MagicMock()
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.avg_cost = 4.5
        data.shares_held = 1000
        data.first_buy_date = None
        data.last_trade_date = None
        data.delta_shares = None  # round19 P3-③: adjust 语义未启用（MagicMock 属性默认非 None）
        data.price = None

        result = await update_etf(db, "510300", data)
        assert result is not None
        assert result.avg_cost == 4.5, f"avg_cost 应更新，实得 {result.avg_cost}"
        assert result.shares_held == 1000, f"shares_held 应更新，实得 {result.shares_held}"


class TestPortfolioChangedBroadcast:
    """round19 P2-② (2026-08-12): 组合结构变更端点写库后广播 portfolio_changed
    （跨页面/多标签页自动刷新；负向：无广播 → 其它页面不感知 → FAIL）。"""

    class _FakeEtf:
        portfolio_type = "on_exchange"
        symbol = "510300"

    @pytest.mark.asyncio
    async def test_create_etf_broadcasts(self, monkeypatch):
        from app.routers import portfolio as pr

        calls = []

        async def fake_add(db, data):
            return self._FakeEtf()

        async def fake_broadcast(pt, sym=None):
            calls.append((pt, sym))

        monkeypatch.setattr(pr, "add_etf", fake_add)
        monkeypatch.setattr(pr, "_broadcast_portfolio_changed", fake_broadcast)
        await pr.create_etf(MagicMock(), MagicMock())
        assert calls == [("on_exchange", "510300")], f"POST /etfs 应广播，实得 {calls}"

    @pytest.mark.asyncio
    async def test_update_etf_route_broadcasts(self, monkeypatch):
        from app.routers import portfolio as pr

        calls = []

        async def fake_update(db, symbol, data):
            return self._FakeEtf()

        async def fake_broadcast(pt, sym=None):
            calls.append((pt, sym))

        monkeypatch.setattr(pr, "update_etf", fake_update)
        monkeypatch.setattr(pr, "_broadcast_portfolio_changed", fake_broadcast)
        await pr.update_etf_route("510300", MagicMock(), MagicMock())
        assert calls == [("on_exchange", "510300")], f"PUT /etfs 应广播，实得 {calls}"

    @pytest.mark.asyncio
    async def test_delete_etf_route_broadcasts(self, monkeypatch):
        from app.routers import portfolio as pr

        calls = []

        async def fake_remove(db, symbol):
            return True

        async def fake_broadcast(pt, sym=None):
            calls.append((pt, sym))

        monkeypatch.setattr(pr, "remove_etf", fake_remove)
        monkeypatch.setattr(pr, "_broadcast_portfolio_changed", fake_broadcast)
        await pr.delete_etf("510300", MagicMock())
        assert calls == [(None, "510300")], f"DELETE /etfs 应广播，实得 {calls}"

    @pytest.mark.asyncio
    async def test_apply_design_broadcasts(self, monkeypatch):
        from app.routers import portfolio as pr

        calls = []

        async def fake_apply(db, design):
            return {"ok": True}

        async def fake_broadcast(pt, sym=None):
            calls.append(pt)

        monkeypatch.setattr(pr, "apply_portfolio_design", fake_apply)
        monkeypatch.setattr(pr, "_broadcast_portfolio_changed", fake_broadcast)
        await pr.apply_design({"symbols": ["510300"], "weights": {"510300": 0.5}})
        assert calls == [None], f"POST /apply-design 应广播，实得 {calls}"

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_break_write(self, monkeypatch):
        """广播失败不影响写库响应（负向：广播失败导致端点 500 → FAIL）。"""
        from app.routers import portfolio as pr

        async def fake_add(db, data):
            return self._FakeEtf()

        class _FakeManager:
            async def broadcast(self, channel, msg):
                raise RuntimeError("ws down")

        # 真实 _broadcast_portfolio_changed 内部 try/except 应吞掉 manager 异常
        monkeypatch.setattr("app.routers.ws.manager", _FakeManager())
        monkeypatch.setattr(pr, "add_etf", fake_add)
        result = await pr.create_etf(MagicMock(), MagicMock())
        assert result.symbol == "510300", "广播失败不应影响写库端点响应"
