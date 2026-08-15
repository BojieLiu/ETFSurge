from __future__ import annotations
"""
Tests for GET /portfolio/designs endpoint (P4-2).

Verifies:
  - Response is a list
  - Every item has required fields: id, created_at, capital, risk_profile, status, error_message
  - error_message is either a string or null
  - status is "completed" or "failed"
  - DB layer is mocked so no real data is needed
"""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime


@pytest.fixture
def mock_db_session():
    """Create a fully mocked AsyncSession that returns test records."""
    import sqlalchemy.ext.asyncio
    from app.routers import portfolio as _port
    # P0-8: 清空列表 TTL 缓存，避免跨测试串缓存致断言失效
    _port._DESIGNS_LIST_CACHE.clear()

    # Create mock records that look like PortfolioDesign ORM instances
    class MockDesign:
        """Simulates a PortfolioDesign ORM row with attributes."""
        def __init__(self, id, created_at, capital, risk_profile, status, error_message):
            self.id = id
            self.created_at = created_at
            self.capital = capital
            self.risk_profile = risk_profile
            self.status = status
            self.error_message = error_message
            self.strategies_json = None  # Needed by list_designs for etf_count
            self.report_quality = "none"  # Z19: list endpoint exposes report_quality
            self.report_generated_at = None  # Z19: list endpoint exposes report_generated_at

    mock_records = [
        MockDesign(
            id=1,
            created_at=datetime(2024, 1, 15, 10, 30, 0),
            capital=500000.0,
            risk_profile="balanced",
            status="completed",
            error_message=None,
        ),
        MockDesign(
            id=2,
            created_at=datetime(2024, 1, 14, 14, 0, 0),
            capital=1000000.0,
            risk_profile="aggressive",
            status="failed",
            error_message="Insufficient candidates for aggressive profile",
        ),
        MockDesign(
            id=3,
            created_at=datetime(2024, 1, 13, 9, 15, 0),
            capital=300000.0,
            risk_profile="conservative",
            status="completed",
            error_message=None,
        ),
    ]

    # Mock the execute method — execute() returns a Result, and result.scalars().all()
    # is a synchronous call, not async.
    class MockScalars:
        def all(self):
            return mock_records

    class MockResult:
        def scalars(self):
            return MockScalars()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()

    # Build the mock session
    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    return session, mock_records


@pytest.mark.asyncio
async def test_list_designs_returns_list(mock_db_session):
    """Response from list_designs must be a list."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    assert isinstance(result, list), f"Expected list, got {type(result)}"


@pytest.mark.asyncio
async def test_list_designs_required_fields(mock_db_session):
    """Every item in the response must contain all required fields."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    required_fields = {"id", "created_at", "capital", "risk_profile", "status", "error_message"}
    for item in result:
        missing = required_fields - set(item.keys())
        assert not missing, f"Item {item.get('id')} missing fields: {missing}"


@pytest.mark.asyncio
async def test_list_designs_error_message_type(mock_db_session):
    """error_message must be either a string or null (None)."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    for item in result:
        em = item.get("error_message")
        assert em is None or isinstance(em, str), (
            f"error_message should be str or None, got {type(em)}: {em!r}"
        )


@pytest.mark.asyncio
async def test_list_designs_status_values(mock_db_session):
    """status must be 'completed' or 'failed'."""
    session, _ = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    valid_statuses = {"completed", "failed"}
    for item in result:
        assert item.get("status") in valid_statuses, (
            f"Item {item.get('id')} has invalid status: {item.get('status')!r}"
        )


@pytest.mark.asyncio
async def test_list_designs_all_records_returned(mock_db_session):
    """All mock records should appear in the response."""
    session, mock_records = mock_db_session
    from app.routers.portfolio import list_designs

    result = await list_designs(limit=10, offset=0, db=session)
    assert len(result) == len(mock_records), (
        f"Expected {len(mock_records)} records, got {len(result)}"
    )


@pytest.mark.asyncio
async def test_list_designs_error_message_preserved():
    """A failed design with an error_message must preserve the message string."""
    import sqlalchemy.ext.asyncio
    from unittest.mock import AsyncMock

    class MockDesign:
        def __init__(self, id, created_at, capital, risk_profile, status, error_message):
            self.id = id
            self.created_at = created_at
            self.capital = capital
            self.risk_profile = risk_profile
            self.status = status
            self.error_message = error_message
            self.strategies_json = None
            self.report_quality = "none"  # Z19: list endpoint exposes report_quality
            self.report_generated_at = None  # Z19: list endpoint exposes report_generated_at

    failed_record = MockDesign(
        id=99,
        created_at=datetime(2024, 2, 1, 8, 0, 0),
        capital=200000.0,
        risk_profile="aggressive",
        status="failed",
        error_message="Provider timeout; no response from LLM",
    )

    class MockScalars:
        def all(self):
            return [failed_record]

    class MockResult:
        def scalars(self):
            return MockScalars()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()

    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    from app.routers.portfolio import list_designs, _DESIGNS_LIST_CACHE
    _DESIGNS_LIST_CACHE.clear()  # P0-8: 防跨测试串缓存

    result = await list_designs(limit=10, offset=0, db=session)
    assert len(result) == 1
    assert result[0]["error_message"] == "Provider timeout; no response from LLM"
    assert result[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_list_designs_ttl_cache_hit():
    """P0-8 (round16 2.3): designs_list 内存 TTL 缓存——同 (limit,offset) 二次调用
    命中缓存不再触发 DB 查询（负向：二次仍查 DB → FAIL）。"""
    import sqlalchemy.ext.asyncio
    from unittest.mock import AsyncMock

    class MockDesign:
        id = 1
        created_at = datetime(2024, 1, 15, 10, 30, 0)
        capital = 500000.0
        risk_profile = "balanced"
        status = "completed"
        error_message = None
        report_quality = "full"
        report_generated_at = None
        strategies_json = '[{"etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}]}]'

    class MockScalars:
        def all(self):
            return [MockDesign()]

    class MockResult:
        def scalars(self):
            return MockScalars()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()
    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    from app.routers.portfolio import list_designs, _DESIGNS_LIST_CACHE
    _DESIGNS_LIST_CACHE.clear()

    r1 = await list_designs(limit=10, offset=0, db=session)
    assert len(r1) == 1
    assert mock_execute.await_count == 1, "首次调用应执行 DB 查询"
    # 二次调用：30s TTL 内命中缓存，不再触发 DB 查询
    r2 = await list_designs(limit=10, offset=0, db=session)
    assert len(r2) == 1
    assert r2[0]["etf_count"] == 1
    assert mock_execute.await_count == 1, f"负向：二次调用应命中缓存而非再查 DB（当前 {mock_execute.await_count}）"

    _DESIGNS_LIST_CACHE.clear()



@pytest.mark.asyncio
async def test_get_design_allocations_include_market_fields():
    """P0-4 (round16 3.9 B3): get_design plans[].allocations[] 转换层白名单
    必须透传 daily_change_pct/price/factor_score——旧实现丢弃 → 设计详情「今日涨跌」
    列恒显示"数据源不可用"（负向：字段缺失 → FAIL）。"""
    import sqlalchemy.ext.asyncio
    from unittest.mock import AsyncMock

    class MockRecord:
        id = 506
        created_at = datetime(2026, 8, 11, 12, 0, 0)
        capital = 500000.0
        risk_profile = "balanced"
        design_text = "## 一、方案概览"
        status = "completed"
        error_message = None
        report_quality = "full"
        report_generated_at = None
        strategies_json = ('[{"label": "平衡型", "portfolio_name": "平衡", "positioning": "均衡", '
                           '"expected_return": 0.12, "max_drawdown": 0.15, "sharpe_ratio": 1.2, '
                           '"etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core", '
                           '"weight": 0.3, "selection_rationale": "宽基", '
                           '"daily_change_pct": -0.65, "price": 4.728, "factor_score": 0.75}]}]')
        market_snapshot_json = '{"market_regime": "range_bound"}'

    class MockResult:
        def scalar_one_or_none(self):
            return MockRecord()

    mock_execute = AsyncMock()
    mock_execute.return_value = MockResult()
    session = AsyncMock(spec=sqlalchemy.ext.asyncio.AsyncSession)
    session.execute = mock_execute

    from app.routers.portfolio import get_design

    result = await get_design(design_id=506, db=session)
    plans = result["plans"]
    assert len(plans) == 1
    alloc = plans[0]["allocations"][0]
    assert alloc["daily_change_pct"] == -0.65, f"daily_change_pct 被转换层丢弃: {alloc}"
    assert alloc["price"] == 4.728
    assert alloc["factor_score"] == 0.75


# ── P2-9 B2/B6 (round16 3.9, 自 test_p29_contract_bias.py 拆入) ────────────────
# 契约偏差收口：B2（design-async 响应含 design_id）入 portfolio 域；
# B6（WatchlistPanel change_pct=null 不标红，前端源码级断言）随 B2 并入本文件
# ——B6 为前端源码断言，勿因「后端文件」误删（来源 round16 §3.9/P2-9）。


@pytest.mark.asyncio
async def test_design_async_response_has_design_id():
    """B2: design-async 202 响应含 design_id 字段（null 允许，前端读字段不 undefined）。"""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient
    from app.main import app

    class _FakeTaskMgr:
        async def create_task(self, task_type="design", params=None):
            return {"task_id": 999, "created_at": "2026-08-11T12:00:00Z"}

    with patch("app.tasks.task_manager.task_manager", _FakeTaskMgr()), \
         patch("app.tasks.task_manager.design_worker", new=AsyncMock()):
        client = TestClient(app)
        resp = client.post("/api/v1/portfolio/design-async", json={"capital": 500000})
    assert resp.status_code == 202
    body = resp.json()
    assert "design_id" in body, f"design-async 响应应含 design_id: {body}"
    assert body["task_id"] == 999


def test_watchlist_panel_null_change_pct_not_red():
    """B6: WatchlistPanel 涨跌着色判空——change_pct=null 不渲染红涨（源码级断言）。"""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                        "components", "market", "WatchlistPanel.vue")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                            "components", "market", "WatchlistPanel.vue")
    src = open(path, encoding="utf-8").read()
    # B6: change_pct=null 必须判空（不得误判红涨）。round24 R20 改为可选链
    # `item.realtime?.change_pct != null`（realtime 可能为 null：美股/HK 无实时源），
    # 语义等价且更健壮——断言实际生效的判空守卫。
    assert "item.realtime?.change_pct != null" in src, \
        "change_pct=null 时应判空（不得误判红涨）"


# ===== folded from test_round19_batch1.py =====
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
