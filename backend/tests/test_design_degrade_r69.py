# -*- coding: utf-8 -*-
"""round29 R69 / R77 收口: 设计「超时 → 降级方案」真正落地，不再「方案生成超时」失败。

现状（§14.4.1 ②）：R59② 的 skip_refresh 降级重试若**也**超时 → 外层
`except asyncio.TimeoutError` → `status=failed, error="方案生成超时"`，
盘后/冷启动首呼 design 拿不到任何方案。

修复：二次超时后用**纯静态池**（零网络）产出 `degradation.mode=degraded` 方案。
附带 R77 收口：`factor_matrix_empty`（因子源不可用）时直接走静态池方案，
不再进 allocate 产出「100% 现金」。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import task_manager as tm
from tests.db_fixtures import task_db, task_mgr  # noqa: F401


def _make_mock_session(design_id: int = 2001):
    record = MagicMock()
    record.id = design_id
    record.report_quality = "pending"
    session = MagicMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)

    async def _refresh(obj):
        obj.id = design_id
    session.refresh = AsyncMock(side_effect=_refresh)
    session.get = AsyncMock(return_value=record)
    return session


# ---------------- 静态降级方案构建器（零网络） ----------------

def test_r69_build_static_degraded_design_is_offline_and_nonempty():
    """降级方案构建器必须零网络、每套方案含非 CASH 标的、标 degraded。"""
    from app.services.strategy_design import build_static_degraded_design

    out = build_static_degraded_design(500000, reason="数据采集超时（测试）")

    assert out.get("error") is None
    strategies = out.get("strategies") or []
    assert len(strategies) == 3
    for s in strategies:
        non_cash = [e for e in (s.get("etfs") or []) if e.get("symbol") != "CASH"]
        assert non_cash, f"方案 {s.get('id')} 无非现金标的（100%现金假方案）"
    deg = out.get("degradation") or {}
    assert deg.get("mode") == "degraded"
    assert "超时" in (deg.get("reason") or "")
    assert out.get("design_metadata", {}).get("fallback") is True


def test_r69_static_degraded_weights_sane():
    """权重合法：每只 ≤30%、总和 ≤1、含现金补足。"""
    from app.services.strategy_design import build_static_degraded_design

    for s in build_static_degraded_design(100000, reason="x")["strategies"]:
        etfs = s.get("etfs") or []
        total = sum(float(e.get("weight") or 0) for e in etfs)
        assert 0.99 <= total <= 1.01, f"权重和异常: {total}"
        for e in etfs:
            if e.get("symbol") != "CASH":
                assert float(e.get("weight") or 0) <= 0.30 + 1e-9


# ---------------- pipeline: 二次超时不再失败 ----------------

@patch("app.tasks.task_manager.async_session")
@patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
@patch("app.services.strategy_design.generate_enhanced_design")
async def test_r69_double_timeout_produces_plan_not_timeout_failure(
    mock_gen, mock_llm, mock_db_session, task_mgr, monkeypatch
):
    """两次数据采集均超时 → 产出降级方案，不得 failed「方案生成超时」。"""
    calls = []

    async def _always_slow(**kwargs):
        calls.append(dict(kwargs))
        await asyncio.sleep(5)
        return {"strategies": [], "market_context": {}}

    mock_gen.side_effect = _always_slow
    mock_llm.return_value = "## 市场分析\n降级方案说明。"
    mock_db_session.side_effect = [_make_mock_session(2001) for _ in range(4)]

    monkeypatch.setattr(tm, "DESIGN_DATA_TIMEOUT", 0.1)
    monkeypatch.setattr(tm, "DESIGN_DEGRADE_RETRY_TIMEOUT", 0.1, raising=False)

    t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
    await tm.design_pipeline(task_mgr, task_id=t["task_id"])

    got = await task_mgr.get_task(t["task_id"])
    assert got["status"] != "failed", f"二次超时后仍失败: {got.get('error_message')}"
    assert "方案生成超时" not in str(got.get("error_message") or ""), \
        "R69 负向：禁止用「方案生成超时」空响应掩盖，应产出降级方案"
    strategies = (got.get("result") or {}).get("strategies") or []
    assert len(strategies) == 3
    for s in strategies:
        assert [e for e in (s.get("etfs") or []) if e.get("symbol") != "CASH"]
    assert len(calls) == 2, f"应尝试 2 次数据采集后转静态降级，实际 {len(calls)}"


@patch("app.tasks.task_manager.async_session")
@patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
@patch("app.services.strategy_design.generate_enhanced_design")
async def test_r69_degraded_marker_persisted_in_market_context(
    mock_gen, mock_llm, mock_db_session, task_mgr, monkeypatch
):
    """降级方案必须带 degradation 标记（前端可提示「数据源降级」，不伪装正常）。"""
    async def _always_slow(**kwargs):
        await asyncio.sleep(5)

    mock_gen.side_effect = _always_slow
    mock_llm.return_value = "报告"
    mock_db_session.side_effect = [_make_mock_session(2002) for _ in range(4)]
    monkeypatch.setattr(tm, "DESIGN_DATA_TIMEOUT", 0.1)
    monkeypatch.setattr(tm, "DESIGN_DEGRADE_RETRY_TIMEOUT", 0.1, raising=False)

    t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
    await tm.design_pipeline(task_mgr, task_id=t["task_id"])

    got = await task_mgr.get_task(t["task_id"])
    mc = (got.get("result") or {}).get("market_context") or {}
    assert (mc.get("degradation") or {}).get("mode") == "degraded"


# ---------------- R77 收口：因子源不可用 → 静态方案而非 100% 现金 ----------------

@pytest.mark.asyncio
async def test_r77_factor_matrix_empty_yields_static_plan_with_holdings(monkeypatch):
    """池非空但因子矩阵内层全空 → 静态池方案（每套含非现金），不得 100% 现金。"""
    from app.services import strategy_design as sd

    class _FakeHub:
        _degraded = False
        _by_code: dict = {}
        _pool = {"core": [{"symbol": "510300"}]}

        def _is_market_hours(self):
            return False

        async def refresh(self):
            return None

        def get_factor_matrix(self):
            return {"510300": {}, "518880": {}}  # 外层非空、内层全空

        def get_pool(self, layer=None):
            return [{"symbol": "510300", "name": "沪深300ETF", "layer": layer or "core"}]

        def get_market_regime(self):
            return "range_bound"

        def get_market_sentiment(self):
            return {}

        def get_index_realtime(self):
            return []

        def get_sector_momentum(self):
            return []

    monkeypatch.setattr(sd, "market_data_hub", _FakeHub(), raising=False)
    monkeypatch.setattr("app.services.market_data_hub.market_data_hub", _FakeHub(), raising=False)

    out = await sd.generate_enhanced_design(capital=200000)

    assert out.get("error") is None
    deg = out.get("degradation") or {}
    assert deg.get("factor_matrix_empty") is True
    # R77 契约：因子全空时绝不产出「100% 现金」失败。引擎在空矩阵下可能仍给出
    # 部分持仓（mode=partial_data/degraded），也可能全现金被后置守卫替换为静态池
    # （mode=static_pool）——两种都满足契约，不得限定单一 mode。
    assert deg.get("mode") in ("static_pool", "partial_data", "degraded"), deg.get("mode")
    strategies = out.get("strategies") or []
    assert len(strategies) == 3
    for s in strategies:
        non_cash = [e for e in (s.get("etfs") or []) if e.get("symbol") != "CASH"]
        assert non_cash, f"R77: 方案 {s.get('id')} 100% 现金（因子源不可用时应给静态方案）"


@pytest.mark.asyncio
async def test_r77_all_cash_engine_output_replaced_by_static_pool(monkeypatch):
    """后置守卫：空矩阵 + 引擎确产出全现金 → 替换为静态等权方案（mode=static_pool）。"""
    from app.services import strategy_design as sd

    class _FakeHub:
        _degraded = False
        _by_code: dict = {}
        _pool = {"core": [{"symbol": "510300"}]}

        def _is_market_hours(self):
            return False

        async def refresh(self):
            return None

        def get_factor_matrix(self):
            return {"510300": {}}  # 内层全空

        def get_pool(self, layer=None):
            return [{"symbol": "510300", "name": "沪深300ETF", "layer": layer or "core"}]

        def get_market_regime(self):
            return "range_bound"

        def get_market_sentiment(self):
            return {}

        def get_index_realtime(self):
            return []

        def get_sector_momentum(self):
            return []

        def get_by_code(self, code):
            return None

    def _all_cash_allocate(**kwargs):
        # 引擎在空矩阵下的典型产物：3 套方案全现金
        return [
            {"id": "defensive", "layer_budget": {"core": 0.4, "satellite": 0.3, "defense": 0.1},
             "allocations": [{"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 1.0}]},
            {"id": "balanced", "layer_budget": {"core": 0.4, "satellite": 0.3, "defense": 0.1},
             "allocations": [{"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 1.0}]},
            {"id": "aggressive", "layer_budget": {"core": 0.4, "satellite": 0.3, "defense": 0.1},
             "allocations": [{"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 1.0}]},
        ]

    monkeypatch.setattr(sd, "market_data_hub", _FakeHub(), raising=False)
    monkeypatch.setattr("app.services.market_data_hub.market_data_hub", _FakeHub(), raising=False)
    monkeypatch.setattr(sd, "engine_allocate", _all_cash_allocate)

    out = await sd.generate_enhanced_design(capital=200000)

    deg = out.get("degradation") or {}
    assert deg.get("mode") == "static_pool", f"全现金应被守卫替换为 static_pool，实得 {deg.get('mode')}"
    for s in out.get("strategies") or []:
        non_cash = [e for e in (s.get("etfs") or []) if e.get("symbol") != "CASH"]
        assert non_cash, f"R77 守卫未生效: 方案 {s.get('id')} 仍 100% 现金"
