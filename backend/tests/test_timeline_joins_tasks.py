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

from app.routers.portfolio import get_timeline, _TIMELINE_CACHE


@pytest.fixture(autouse=True)
def _clear_timeline_cache():
    """round20 P0-1: get_timeline 新增 30s TTL 缓存——每用例清空，防跨用例脏数据。"""
    _TIMELINE_CACHE.clear()
    yield
    _TIMELINE_CACHE.clear()


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

    # round18 P0-1: timeline 显式列查询改用 result.all()（返回 Row）——
    # 兼容测试双接口
    def all(self):
        return self._rows


class _FakeDB:
    """顺序返回 designs / checks / check-tasks / tasks 四组结果。

    round9 P2-11: get_timeline 新增 check 类型 task 查询（判孤立 check 记录）→
    第 3 个查询为 check 任务组（默认空）。
    """

    def __init__(self, designs, checks, tasks, check_tasks=None):
        self.results = [
            _FakeResult(designs), _FakeResult(checks),
            _FakeResult(check_tasks or []), _FakeResult(tasks),
        ]
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

    @pytest.mark.asyncio
    async def test_running_check_task_visible(self):
        """P0-9 (round16 3.10 R1): check 类型 running 任务在 timeline 可见——
        旧实现 task_items 只查 design，策略检查运行中不可见。"""
        db = _FakeDB(
            designs=[],
            checks=[],
            tasks=[_task(388, "running", task_type="check")],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        running_checks = [i for i in body["items"] if i["_type"] == "check" and i["status"] == "running"]
        assert running_checks, "check 类型 running 任务应在 timeline 可见"
        assert running_checks[0]["task_id"] == 388

    @pytest.mark.asyncio
    async def test_completed_check_task_not_duplicated(self):
        """P0-9: 已完成且已落 strategy_check_records 的 check 任务不重复（check_items 已覆盖）。"""
        db = _FakeDB(
            designs=[],
            checks=[_check(3)],
            tasks=[_task(389, "completed", record_id=3, task_type="check")],
        )
        body = await get_timeline(limit=20, offset=0, db=db)
        check_items = [i for i in body["items"] if i["_type"] == "check"]
        # 只有 1 条 check（check_items 覆盖，task 行被去重），且不是来自 task 的独立 ghost
        assert len(check_items) == 1
        assert check_items[0]["id"] == 3



class _StmtCapturingDB:
    """捕获 get_timeline 执行的所有 stmt 字符串（用于断言 SQL 形态）。"""

    def __init__(self, results):
        self.results = list(results)
        self.i = 0
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        r = self.results[self.i]
        self.i += 1
        return r


class TestCheckTaskQueryOrdering:
    """round23 遗留修复（2026-08-14）：/timeline 的 check-task 关联查询
    （check_task_stmt）缺 order_by——SQLite 按 rowid 返回最旧 21 条 check 任务，
    其 record_id 集合不含最新 check 记录 → 最新策略检查全被标 orphan=true →
    前端历史列表过滤掉 → 「策略检查成功但不显示」。验收：该查询必须按
    created_at 降序（与 checks/tasks 查询对齐，都取最近）。"""

    @pytest.mark.asyncio
    async def test_check_task_stmt_ordered_by_created_at_desc(self):
        """check-task 关联查询必须带 ORDER BY created_at DESC（取最近任务，防误标 orphan）。"""
        # 复用模块级 _design/_check/_task 构造器；results 顺序:
        # designs / checks / check-tasks / tasks
        db = _StmtCapturingDB([
            _FakeResult([_design(1)]),
            _FakeResult([_check(5)]),
            _FakeResult([_task(240, "completed", record_id=240, task_type="check")]),
            _FakeResult([_task(470, "completed", record_id=5, task_type="check")]),
        ])
        await get_timeline(limit=20, offset=0, db=db)
        # 第 3 条 stmt = check_task_stmt
        assert len(db.statements) >= 3, f"应执行 >=3 条查询，实得 {len(db.statements)}"
        check_stmt = db.statements[2].upper()
        assert "ORDER BY" in check_stmt, \
            f"check-task 查询必须按时间降序（防取最旧记录误标 orphan），实得: {db.statements[2][:200]}"
        assert "CREATED_AT" in check_stmt, \
            f"check-task 查询须按 created_at 排序，实得: {db.statements[2][:200]}"

    @pytest.mark.asyncio
    async def test_orphan_false_when_record_linked_to_recent_task(self):
        """行为回归：最新 check 记录有 task 关联时 orphan 必须 False（否则前端过滤掉）。"""
        db = _StmtCapturingDB([
            _FakeResult([_design(1)]),
            _FakeResult([_check(5)]),                       # 最新 check 记录
            _FakeResult([_task(470, "completed", record_id=5, task_type="check")]),  # 关联任务
            _FakeResult([]),
        ])
        items = await get_timeline(limit=20, offset=0, db=db)
        items = items.get("items", items) if isinstance(items, dict) else items
        check_items = [it for it in items if it.get("_type") == "check"]
        assert check_items, "timeline 应包含 check 记录"
        assert check_items[0].get("orphan") is False, \
            f"有关联 task 的 check 记录不得标 orphan（前端会过滤），实得: {check_items[0]}"
