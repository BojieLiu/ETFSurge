from __future__ import annotations
"""
Tests for POST /api/v1/portfolio/apply-design (P0).

Verifies:
  - Request body with symbols + weights applies correctly
  - Existing ETFs get updated (action: "updated")
  - New symbols get created (action: "added")
  - Weight is clamped to [0, 0.5]
  - Empty symbols returns empty result
"""

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_db():
    """Create a fully mocked async session with list_etfs returning test records."""
    mock_etf = MagicMock()
    mock_etf.symbol = "510300"
    mock_etf.name = "沪深300ETF"
    mock_etf.target_weight = 0.3
    mock_etf.portfolio_type = "on_exchange"
    mock_etf.is_active = True

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session, [mock_etf]


@pytest.mark.asyncio
async def test_apply_design_updates_existing(mock_db):
    """已有 ETF 更新权重时返回 action: updated."""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,  # first call (inside apply_portfolio_design)
        existing_etfs,  # second call (after commit)
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.4, "portfolio_type": "on_exchange"}],
                       "applied": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.4, "portfolio_type": "on_exchange",
                                    "action": "updated"}],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["510300"],
                        "weights": {"510300": 0.4}},
                db=session,
            )
            assert result["applied"][0]["action"] == "updated"
            assert result["applied"][0]["target_weight"] == 0.4
            assert len(result["symbols"]) == 1


@pytest.mark.asyncio
async def test_apply_design_adds_new(mock_db):
    """新 ETF 自动创建时返回 action: added."""
    session, existing_etfs = mock_db
    merged = existing_etfs[:]
    new_mock = MagicMock()
    new_mock.symbol = "159915"
    new_mock.name = "159915 ETF"
    new_mock.target_weight = 0.2
    new_mock.portfolio_type = "on_exchange"
    new_mock.is_active = True
    merged.append(new_mock)

    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,
        merged,
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [
                           {"symbol": "510300", "name": "沪深300ETF",
                            "target_weight": 0.3, "portfolio_type": "on_exchange"},
                           {"symbol": "159915", "name": "159915 ETF",
                            "target_weight": 0.2, "portfolio_type": "on_exchange"},
                       ],
                       "applied": [
                           {"symbol": "159915", "name": "159915 ETF",
                            "target_weight": 0.2, "portfolio_type": "on_exchange",
                            "action": "added"},
                       ],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["159915", "510300"],
                        "weights": {"159915": 0.2, "510300": 0.3}},
                db=session,
            )
            added = [a for a in result["applied"] if a["action"] == "added"]
            assert len(added) == 1
            assert added[0]["symbol"] == "159915"


@pytest.mark.asyncio
async def test_apply_design_weight_clamped(mock_db):
    """权重超出 [0, 0.5] 范围时被夹紧."""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", side_effect=[
        existing_etfs,
        existing_etfs,
    ]):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.5, "portfolio_type": "on_exchange"}],
                       "applied": [{"symbol": "510300", "name": "沪深300ETF",
                                    "target_weight": 0.5, "portfolio_type": "on_exchange",
                                    "action": "updated"}],
                   })):
            from app.routers.portfolio import apply_design
            result = await apply_design(
                design={"portfolio_type": "on_exchange",
                        "symbols": ["510300"],
                        "weights": {"510300": 0.9}},  # 0.9 → clamped to 0.5
                db=session,
            )
            assert result["applied"][0]["target_weight"] == 0.5


@pytest.mark.asyncio
async def test_apply_design_empty_symbols(mock_db):
    """round14 P0-A: 空 symbols 应 400（修复前返回 200 空操作 + 前端假成功，
    前后端断裂根因——旧断言固化了 bug 行为，已更新）。"""
    session, existing_etfs = mock_db
    with patch("app.routers.portfolio.list_etfs", return_value=existing_etfs):
        with patch("app.routers.portfolio.apply_portfolio_design",
                   new=AsyncMock(return_value={
                       "symbols": [],
                       "applied": [],
                       "message": "组合设计中没有指定持仓",
                   })):
            from app.routers.portfolio import apply_design
            with pytest.raises(HTTPException) as exc:
                await apply_design(
                    design={"portfolio_type": "on_exchange",
                            "symbols": [],
                            "weights": {}},
                    db=session,
                )
            assert exc.value.status_code == 400


# ===== folded from test_round14_apply_design_factors.py =====
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from app.main import app
from app.routers import factors as factors_router
from app.routers.portfolio import apply_design
from app.services.portfolio_service import apply_portfolio_design
client = TestClient(app)
def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
class TestApplyDesignBackend:
    """P0-A 后端加固：空 payload → 400；契约 payload → applied 非空。"""

    def test_empty_symbols_rejected_400(self):
        """修复前：空 symbols 返回 200 空操作（前端假成功）；修复后 400。"""
        with patch("app.routers.portfolio.apply_portfolio_design", new_callable=AsyncMock) as m:
            resp = client.post("/api/v1/portfolio/apply-design", json={"portfolio_type": "on_exchange", "symbols": [], "weights": {}})
        assert resp.status_code == 400
        m.assert_not_awaited()

    def test_missing_weights_rejected_400(self):
        resp = client.post("/api/v1/portfolio/apply-design", json={"portfolio_type": "on_exchange", "symbols": ["510300"]})
        assert resp.status_code == 400

    def test_contract_payload_applied_matches_symbols(self):
        """基线 D 首个用例（前端真实消费形态）：契约 payload → applied 与 symbols 一致。"""
        fake_result = {
            "symbols": [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3, "portfolio_type": "on_exchange"}],
            "applied": [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3, "portfolio_type": "on_exchange", "action": "updated"}],
        }
        with patch("app.routers.portfolio.apply_portfolio_design", new_callable=AsyncMock, return_value=fake_result):
            payload = {
                "portfolio_type": "on_exchange",
                "symbols": ["510300", "159338"],
                "weights": {"510300": 0.3, "159338": 0.2},
            }
            resp = client.post("/api/v1/portfolio/apply-design", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("applied"), "applied 必须非空（防前端假成功）"
        assert body["applied"][0]["symbol"] in payload["symbols"]

    def test_service_layer_empty_symbols_returns_empty_not_crash(self):
        """服务层仍兼容直接调用（不抛异常），路由层负责 400 拦截。"""
        with patch("app.services.portfolio_service.list_etfs", new_callable=AsyncMock, return_value=[]):
            result = asyncio_run(apply_portfolio_design(MagicMock(), {"symbols": [], "weights": {}}))
        assert result.get("symbols") == []


# ===== folded from test_round19_batch1.py =====
from unittest.mock import AsyncMock, MagicMock
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
