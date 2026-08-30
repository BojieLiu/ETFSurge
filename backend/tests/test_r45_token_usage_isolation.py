"""round45 R160 诊断: 测试环境 token_usage.db 隔离——防 pytest 污染生产统计.

背景: round44 C 方案 (verify_llm_exclusion) 5min delta 检测到 deepseek-v4-flash-free
+9 calls, 排查发现 1051 条 test_ 前缀 function_name 记录写入真实 data/token_usage.db
（pytest 全量期间, conftest 未隔离 token_store DB 路径）。

修复: conftest.py 加 session 级 autouse fixture _isolate_token_usage_db——
测试期把 token_store._db_path 切到 tmp, 防污染。

本测试验证:
1. fixture 生效: 测试进程内 token_store._db_path 不指向 data/token_usage.db
2. 写入隔离: token_store.record 写 tmp DB, 真实 DB 无新记录
3. _init_db 在新路径正常建表
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_token_usage_db_isolated_to_tmp():
    """fixture 生效: token_store._db_path 已切到 tmp (非 data/token_usage.db)."""
    from app.monitor.token_usage import token_store
    db_path = Path(token_store._db_path)
    assert "data" not in db_path.parts or "token_usage.db" != db_path.name or (
        db_path.parent.name.startswith("token_usage")
    ), f"token_usage DB 应在 tmp: {db_path}"
    # 更直接: 路径中含 tmp/pytest- 痕迹 (tmp_path_factory 产物)
    assert "pytest" in str(db_path) or "tmp" in str(db_path).lower(), (
        f"DB 路径应含 pytest tmp 痕迹: {db_path}"
    )


def test_token_store_record_goes_to_isolated_db(tmp_path):
    """写入隔离: record 后 tmp DB 有记录, 真实 data/token_usage.db 不变."""
    import asyncio
    from app.monitor.token_usage import token_store, UsageRecord

    # 记录当前真实 DB 的总行数
    real_db = Path("data/token_usage.db")
    real_count_before = 0
    if real_db.exists():
        with sqlite3.connect(real_db) as conn:
            real_count_before = conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]

    async def _record():
        await token_store.record(UsageRecord(
            function_name="test_round45_isolation_probe",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            model="isolated-model",
            timestamp=0.0,
            success=True,
            duration_ms=1.0,
            provider="test_provider",
        ))

    asyncio.run(_record())

    # 隔离 DB (token_store._db_path) 应含这条记录
    isolated_db = Path(token_store._db_path)
    assert isolated_db.exists(), f"隔离 DB 应已创建: {isolated_db}"
    with sqlite3.connect(isolated_db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM usage_records WHERE function_name='test_round45_isolation_probe'"
        ).fetchone()[0]
    assert n >= 1, f"隔离 DB 应含探针记录: {isolated_db}"

    # 真实 DB 行数不变
    if real_db.exists():
        with sqlite3.connect(real_db) as conn:
            real_count_after = conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]
        assert real_count_after == real_count_before, (
            f"真实 DB 被污染! before={real_count_before} after={real_count_after}"
        )


def test_isolated_db_has_table_schema():
    """_init_db 在 tmp 路径正常建表 (flush_worker 写入不炸 no such table)."""
    from app.monitor.token_usage import token_store
    isolated_db = Path(token_store._db_path)
    assert isolated_db.exists()
    with sqlite3.connect(isolated_db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_records)").fetchall()]
    assert "function_name" in cols and "provider" in cols and "model" in cols, (
        f"usage_records 表 schema 应完整: {cols}"
    )
