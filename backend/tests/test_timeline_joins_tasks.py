"""
O12 (docs/archived/round8-rediagnosis.md §7 §7 O12 + docs/archived/interaction-redesign.md D2):
/portfolio/timeline join tasks 表——失败 design 任务在历史列表可见。

验收:
① 触发 Stage2 失败后 /timeline 返回 status='failed' + error_message；
② 已写库成功项不因 join 重复；
③ 运行中任务也可见（status='running'）。
"""

from datetime import datetime, timezone

import pytest

from app.routers.portfolio import get_timeline


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


def _task(id_, status, record_id=None, error=None, created_minute=0):
    return _Row(
        id=id_, task_type="design", status=status, record_id=record_id,
        error_message=error,
        created_at=datetime(2026, 8, 7, 11, created_minute),
    )


class _FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDB:
    """顺序返回 designs / checks / tasks 三组结果。"""

    def __init__(self, designs, checks, tasks):
        self.results = [_FakeResult(designs), _FakeResult(checks), _FakeResult(tasks)]
        self.i = 0

    async def execute(self, stmt):
        r = self.results[self.i]
        self.i += 1
        return r


class TestTimelineJoinsTasks:
    @pytest.mark.asyncio
    async def test_failed_task_visible_with_error(self):
        """失败 design 任务（无 design 记录）在 timeline 中可见，带 status+error_message。"""
        db = _FakeDB(
            designs=[_design(1)],          # 成功记录
            checks=[_check(7)],
            tasks=[_task(201, "failed", error="方案生成超时，数据源响应过慢")],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        items = body["items"]
        failed = [i for i in items if i["status"] == "failed"]
        assert failed, "失败 design 任务应在 timeline 可见"
        assert failed[0]["error_message"] == "方案生成超时，数据源响应过慢"
        assert failed[0]["_type"] == "design"

    @pytest.mark.asyncio
    async def test_running_task_visible(self):
        """运行中 design 任务可见（status='running'）。"""
        db = _FakeDB(
            designs=[],
            checks=[],
            tasks=[_task(202, "running")],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        assert any(i["status"] == "running" for i in body["items"])

    @pytest.mark.asyncio
    async def test_completed_task_with_design_not_duplicated(self):
        """成功且已有 design 记录的任务不因 join 重复。"""
        db = _FakeDB(
            designs=[_design(1)],
            checks=[],
            tasks=[_task(203, "completed", record_id=1)],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        items = body["items"]
        design_items = [i for i in items if i["_type"] == "design" and i["status"] == "completed"]
        # 只有 1 条 completed design（不重复）
        assert len(design_items) == 1
        assert design_items[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_success_without_design_record_still_shown(self):
        """completed 但无 design 记录的任务保留（task 可见，带 task_id）。"""
        db = _FakeDB(
            designs=[],
            checks=[],
            tasks=[_task(204, "completed", error=None)],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        assert any(i.get("task_id") == 204 for i in body["items"])
