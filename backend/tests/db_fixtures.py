"""
共享测试 DB fixtures（Z27 task-persistence-redesign §8.1）

M4: fixture 不能放在单个测试文件内部 — 多个测试文件（test_task_db_persistence /
    test_design_pipeline_integration / test_design_tasks / test_report_quality ...）
    需要同一测试库，pytest fixture 跨文件不可见。
M5: 建齐三张表（tasks + portfolio_designs + strategy_check_records）— A2/A3 的
    「record_id 关联」用例需要 design/check 表。
D10: TaskManager(session_factory=...) 注入独立 SQLite 测试库，不碰全局单例 / 开发库。
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base


@pytest.fixture(scope="session")
async def task_db(tmp_path_factory):
    """session 级独立 SQLite 测试库：tasks + portfolio_designs + strategy_check_records。"""
    tmp = tmp_path_factory.mktemp("task_db")
    db_url = f"sqlite+aiosqlite:///{tmp / 'test_tasks.db'}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    from app.models.task import TaskRecord
    from app.models.portfolio_design import PortfolioDesign
    from app.models.strategy_check import StrategyCheckRecord

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            TaskRecord.__table__,
            PortfolioDesign.__table__,
            StrategyCheckRecord.__table__,
        ])

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def task_mgr(task_db):
    """每次用例独立的 DB-backed TaskManager（注入测试库），用例间清空 tasks 表（§8.1）。"""
    from sqlalchemy import delete
    from app.tasks.task_manager import TaskManager
    from app.models.task import TaskRecord

    async with task_db() as db:
        await db.execute(delete(TaskRecord))
        await db.commit()

    return TaskManager(session_factory=task_db)
