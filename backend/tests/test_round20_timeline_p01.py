"""
round20 P0-1 (docs/round20-container-acceptance-diagnosis.md §五 P0-1):
/portfolio/timeline 补 30s TTL 缓存 + limit 分页。

TDD 顺序：本文件为「先写失败单测」阶段——以下断言当前实现必然 FAIL：
  - 无 TTL 缓存（两次调用重复查库）；
  - design/check/task 三表查询无 .limit()（全表扫描）；
修复（portfolio.py get_timeline）：加 _TIMELINE_CACHE（30s TTL、按 (limit, offset) 键控）+
  三表查询加 limit(limit+1)。verify_e2e.py 阈值 5.0→1.0 由 verify_e2e 链路验证。

验收（对照文档 P0-1）：热态 ≤300ms；缓存命中不重复查库；分页生效。
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.routers.portfolio import get_timeline, _TIMELINE_CACHE


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _design(id_, status="completed", error=None, capital=500000.0):
    return _Row(
        id=id_, strategies_json="[]", capital=capital,
        status=status, error_message=error,
        created_at=datetime(2026, 8, 7, 12, 0, id_),
    )


def _check(id_):
    return _Row(
        id=id_, summary="策略检查已完成",
        created_at=datetime(2026, 8, 7, 10, 0, id_),
    )


def _task(id_, status, record_id=None, error=None, created_minute=0, task_type="design"):
    return _Row(
        id=id_, task_type=task_type, status=status, record_id=record_id,
        error_message=error,
        created_at=datetime(2026, 8, 7, 11, created_minute),
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)

    def all(self):
        return self._rows


class _FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _CountingDB:
    """记录 execute 调用次数与 stmt（验证缓存命中 = 不查库；验证 limit 已加）。"""

    def __init__(self, designs, checks, tasks, check_tasks=None):
        self.results = [
            _FakeResult(designs), _FakeResult(checks),
            _FakeResult(check_tasks or []), _FakeResult(tasks),
        ]
        self.i = 0
        self.execute_count = 0
        self.statements = []

    async def execute(self, stmt):
        self.execute_count += 1
        self.statements.append(stmt)
        r = self.results[self.i % len(self.results)]
        self.i += 1
        return r


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前清空 timeline 缓存，避免用例间串扰。"""
    _TIMELINE_CACHE.clear()
    yield
    _TIMELINE_CACHE.clear()


@pytest.mark.asyncio
async def test_second_call_within_ttl_hits_cache():
    """P0-1: 30s TTL 内同 (limit, offset) 二次调用 → 命中缓存，不再查库。"""
    db = _CountingDB(
        designs=[_design(1)], checks=[_check(7)],
        tasks=[_task(201, "completed", record_id=1)],
    )
    body1 = await get_timeline(limit=20, offset=0, db=db)
    assert body1["total"] >= 1
    first_exec = db.execute_count
    body2 = await get_timeline(limit=20, offset=0, db=db)
    assert db.execute_count == first_exec, "30s TTL 内二次调用不应重复查库"
    assert body2["total"] == body1["total"]


@pytest.mark.asyncio
async def test_different_pagination_misses_cache():
    """不同 (limit, offset) 是不同缓存键 → 重新查库。"""
    db = _CountingDB(
        designs=[_design(1), _design(2)], checks=[],
        tasks=[_task(201, "running")],
    )
    await get_timeline(limit=20, offset=0, db=db)
    first_exec = db.execute_count
    await get_timeline(limit=5, offset=10, db=db)
    assert db.execute_count > first_exec, "不同分页参数应重新查库（缓存键含 limit/offset）"


@pytest.mark.asyncio
async def test_queries_carry_limit():
    """P0-1 修复①：design/check/task 三表查询必须带 .limit()（防全表扫描）。"""
    db = _CountingDB(
        designs=[_design(1), _design(2), _design(3)], checks=[_check(7)],
        tasks=[_task(201, "completed", record_id=1)],
    )
    await get_timeline(limit=20, offset=0, db=db)
    limited = [
        str(s) for s in db.statements
        if any(t in str(s) for t in ("portfolio_design", "strategy_check_record", "task_record"))
    ]
    assert limited, "未捕获到任何设计/检查/任务表查询"
    for s in limited:
        assert "LIMIT" in s.upper(), f"查询未带 LIMIT: {s}"
