"""
round18 P0-1/P0-2/P0-4 测试（2026-08-12 实施）：
- P0-1: timeline 列裁剪——端点不再读取 strategies_json 大字段（负向：仍读 → FAIL）
- P0-2: metrics 30s TTL 缓存——热态命中缓存不再重复查 DB（负向：每次重查 → FAIL）
- P0-4: factors status 读 DB IC 周期计数——DB 计数 >30 → valid（负向：内存计数
        ≈11 → no_data → FAIL）
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


class TestP01TimelineColumnPruning:
    """round18 P0-1: timeline 显式列查询——不物化/解析 strategies_json 大字段。"""

    @pytest.mark.asyncio
    async def test_timeline_does_not_touch_strategies_json(self):
        """mock Row 无 strategies_json 属性（列裁剪后不读取）→ 端点正常返回；
        负向: 旧实现 `json.loads(d.strategies_json)` → AttributeError → FAIL。"""
        from app.routers.portfolio import get_timeline

        class _Row:
            """仅含显式列（id/created_at/status/capital/error_message/summary 等），
            故意无 strategies_json —— 端点若读取该属性会 AttributeError。"""
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        designs = [
            _Row(id=1, created_at=datetime(2026, 8, 7, 12, 0, 1), status="completed",
                 capital=500000.0, error_message=None),
        ]
        checks = [
            _Row(id=7, created_at=datetime(2026, 8, 7, 10, 0, 7), summary="策略检查已完成"),
        ]
        tasks = [
            _Row(id=201, task_type="design", status="failed", record_id=None,
                 error_message="方案生成超时", created_at=datetime(2026, 8, 7, 11, 0, 1)),
        ]

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        class _FakeDB:
            def __init__(self):
                self.results = [_Result(designs), _Result(checks),
                                _Result([]), _Result(tasks)]
                self.i = 0

            async def execute(self, stmt):
                r = self.results[self.i]
                self.i += 1
                return r

        body = await get_timeline(limit=20, offset=0, db=_FakeDB())
        items = body["items"]
        assert any(i["_type"] == "design" for i in items)
        assert any(i["_type"] == "check" for i in items)
        assert any(i["_type"] == "design" and i["status"] == "failed" for i in items)


class TestP02MetricsCache:
    """round18 P0-2: metrics 30s TTL 缓存——热态命中缓存，DB 只查一次。"""

    @pytest.mark.asyncio
    async def test_metrics_second_call_hits_cache(self, monkeypatch):
        from app.routers import admin as admin_router

        class _FakeHub:
            def get_pool(self):
                return {"A": [1, 2, 3]}
            _consecutive_failures = 0

        execute_calls = {"n": 0}

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, stmt):
                execute_calls["n"] += 1
                from sqlalchemy import text
                s = str(stmt)
                if "count" in s.lower():
                    return MagicMock(scalar=MagicMock(return_value=10))
                return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        def _fake_session_factory():
            return _FakeSession()

        admin_router._METRICS_CACHE.clear()
        import app.services.market_data_hub as mdh
        import app.database as dbmod
        monkeypatch.setattr(mdh, "market_data_hub", _FakeHub())
        monkeypatch.setattr(dbmod, "async_session", _fake_session_factory)

        r1 = await admin_router.get_system_metrics()
        assert r1["pool"]["total_candidates"] == 3
        n_after_first = execute_calls["n"]
        assert n_after_first > 0
        # 二次调用 30s TTL 内命中缓存 → 不再执行 DB 查询（负向: 每次重查 → FAIL）
        r2 = await admin_router.get_system_metrics()
        assert r2["designs"] == r1["designs"]
        assert execute_calls["n"] == n_after_first, \
            f"负向: 二次调用应命中缓存而非重查 DB（当前执行 {execute_calls['n']} 次）"
        admin_router._METRICS_CACHE.clear()


class TestP04FactorsDbSampleCount:
    """round18 P0-4: /factors/active status 读 DB IC 周期计数。"""

    def _make_def(self, code, cat):
        from app.factors.factor_registry import FactorDefinition
        return FactorDefinition(code=code, name="F", category=cat, subcategory="",
                                standardization="zscore", ic_threshold=0.02)

    @pytest.mark.asyncio
    async def test_db_count_over_250_significant_valid(self):
        """F25②: DB 日频交易日 260（≥250）+ t≥2 + |IR|≥0.5 → status=valid
        （负向: 40 天 → no_data 积累中——旧「30 周期即 valid」判据已废弃）。"""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        code = "technical.ma.sma_5"
        factors_router._CACHE.clear()
        mock_db = MagicMock()
        factors_router._db_ic_sample_counts = AsyncMock(return_value={code: 260})
        factors_router._db_ic_series_stats = AsyncMock(return_value={
            code: {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 2.3},
        })
        with patch.object(registry, "_computers", {code: (lambda x: 0.0)}), \
             patch.object(registry, "_factors", {code: self._make_def(code, "technical")}), \
             patch.object(registry, "_last_ic_batch", {code: 0.0321}), \
             patch.object(registry, "_sample_counts", {code: 11}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors(db=mock_db)

        import json
        data = json.loads(body.body) if isinstance(body.body, bytes) else body.body
        flat = {f["code"]: f for cat in data["categories"] for f in cat["factors"]}
        f = flat[code]
        assert f["status"] == "valid", f"260 交易日 + 显著应 valid，实得 {f['status']}: {f['reason']}"
        assert f["sample_count"] == 260
        assert f["t_stat"] == 2.3
        factors_router._CACHE.clear()

    @pytest.mark.asyncio
    async def test_db_count_40_days_still_no_data(self):
        """F25②: 40 个交易日（积累中，未达可观察下限 60）→ no_data，
        即使 |IC| 高（旧「40>30 → valid」判据已废弃——40 天无统计含义）。"""
        from app.routers import factors as factors_router
        from app.factors.factor_registry import registry

        code = "technical.ma.sma_5"
        factors_router._CACHE.clear()
        mock_db = MagicMock()
        factors_router._db_ic_sample_counts = AsyncMock(return_value={code: 40})
        factors_router._db_ic_series_stats = AsyncMock(return_value={
            code: {"ic_mean": 0.032, "ic_std": 0.05, "ir": 0.64, "t_stat": 1.1},
        })
        with patch.object(registry, "_computers", {code: (lambda x: 0.0)}), \
             patch.object(registry, "_factors", {code: self._make_def(code, "technical")}), \
             patch.object(registry, "_last_ic_batch", {code: 0.0321}), \
             patch.object(registry, "_sample_counts", {code: 40}), \
             patch.object(registry, "_last_computed_at", "2026-07-31T15:00:00Z"):
            body = await factors_router.get_active_factors(db=mock_db)

        import json
        data = json.loads(body.body) if isinstance(body.body, bytes) else body.body
        flat = {f["code"]: f for cat in data["categories"] for f in cat["factors"]}
        assert flat[code]["status"] == "no_data", "40 交易日仍应 no_data（积累中）"
        assert "积累" in flat[code]["reason"]
        factors_router._CACHE.clear()
