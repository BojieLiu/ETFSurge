"""round35 A1 (docs/round35-architecture-review.md §13.9 T-A1) —
portfolio.db WAL 日志模式 + busy_timeout 接线验证。

含防恒绿的负向对照组：rollback journal（旧行为）下「读者持读锁 + 写者独占开始」
立即 BUSY；同一场景在 WAL 下读写并行无阻塞——证明断言能区分两种模式，
而非任何配置下都绿。
"""
import sqlite3

import pytest

from app.database import _set_sqlite_pragma


@pytest.fixture
def wal_db(tmp_path):
    """经 database.py pragma 钩子初始化的临时库（等价生产接线：首连即设 WAL，
    journal_mode 持久化进 DB 文件）。"""
    db = tmp_path / "wal_test.db"
    conn = sqlite3.connect(db)
    _set_sqlite_pragma(conn, None)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def rollback_db(tmp_path):
    """旧行为对照库：不经钩子，默认 rollback journal。"""
    db = tmp_path / "rollback_test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return db


def test_journal_mode_is_wal_and_persists(wal_db):
    """正向①：经钩子连接后 journal_mode == wal，且对新打开的裸连接依然成立
    （WAL 持久化到 DB 文件——hub/_common.py 裸连接无需重设模式）。"""
    conn = sqlite3.connect(wal_db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    # 重开连接（模拟 hub 裸 sqlite3.connect）→ 模式仍在
    fresh = sqlite3.connect(wal_db)
    try:
        assert fresh.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        fresh.close()


def test_busy_timeout_set_per_connection(wal_db):
    """正向②：busy_timeout 是 per-connection 属性，每次 connect 由钩子设为 30s。"""
    conn = sqlite3.connect(wal_db)
    _set_sqlite_pragma(conn, None)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        conn.close()


def test_wal_reader_writer_parallel_no_busy(wal_db):
    """正向③（并发冒烟）：WAL 下读者持读事务期间写者可写入提交，交替多轮无 BUSY。"""
    for round_no in range(20):
        reader = sqlite3.connect(wal_db, timeout=1)
        writer = sqlite3.connect(wal_db, timeout=1)
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM t").fetchall()  # 持共享读快照
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO t VALUES (?)", (round_no,))
            writer.execute("COMMIT")  # WAL：写不打扰进行中的读
            reader.execute("SELECT * FROM t").fetchall()
            reader.execute("COMMIT")
        finally:
            reader.close()
            writer.close()


def test_rollback_mode_reproduces_busy(rollback_db):
    """负向对照：同场景在 rollback journal（旧行为）下写者被拒——
    若本用例不抛错，说明测试无法区分两种模式（恒绿假防护）。"""
    reader = sqlite3.connect(rollback_db, timeout=0.2)
    writer = sqlite3.connect(rollback_db, timeout=0.2)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM t").fetchall()  # 持共享锁
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            # 共享锁活跃时升级 EXCLUSIVE → BUSY（rollback 模式读写互斥）
            writer.execute("COMMIT")
    finally:
        reader.close()
        writer.close()


def test_real_database_engine_has_pragma_hook():
    """接线存在性：生产 engine 已挂 pragma 钩子（防钩子被误删后本文件仍绿）。"""
    from sqlalchemy import event

    from app.database import _set_sqlite_pragma, engine

    assert event.contains(
        engine.sync_engine, "connect", _set_sqlite_pragma
    ), "database.engine 未挂 _set_sqlite_pragma connect 钩子"
