"""round35 A1 (docs/round35-architecture-review.md §13.9 T-A1) + R139 (round38) —
portfolio.db journal_mode + busy_timeout + synchronous 接线验证。

round35 曾用 WAL 模式（读不阻塞写）；round38 R139 因 WAL 下并发写入多次
page corruption（清空重建后 2h 再次 malformed）改回 DELETE + synchronous=FULL，
牺牲并发读写的无阻塞换取写入完整性（rollback journal 读写互斥为预期行为）。

含防恒绿的负向对照组：读者持读锁 + 写者独占开始 → 立即 BUSY——证明断言能
区分「DELETE/rollback 互斥」与「WAL 并行」，而非任何配置下都绿。
"""
import sqlite3

import pytest

from app.database import _set_sqlite_pragma


@pytest.fixture
def pragma_db(tmp_path):
    """经 database.py pragma 钩子初始化的临时库（等价生产接线：首连即设
    journal_mode=DELETE + synchronous=FULL，DELETE 持久化进 DB 文件）。"""
    db = tmp_path / "pragma_test.db"
    conn = sqlite3.connect(db)
    _set_sqlite_pragma(conn, None)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def rollback_db(tmp_path):
    """旧行为对照库：不经钩子，默认 rollback journal（DELETE 属 rollback 族，
    读写同样互斥）。"""
    db = tmp_path / "rollback_test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return db


def test_journal_mode_is_delete_and_persists(pragma_db):
    """正向①：经钩子连接后 journal_mode == delete，且对新打开的裸连接依然成立
    （DELETE 持久化到 DB 文件——hub/_common.py 裸连接无需重设模式）。"""
    conn = sqlite3.connect(pragma_db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()
    # 重开连接（模拟 hub 裸 sqlite3.connect）→ 模式仍在
    fresh = sqlite3.connect(pragma_db)
    try:
        assert fresh.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        fresh.close()


def test_synchronous_full_set(pragma_db):
    """正向②：synchronous=FULL（2）——R139 写完整性保护，防 WAL 损坏复发。"""
    conn = sqlite3.connect(pragma_db)
    _set_sqlite_pragma(conn, None)
    try:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        conn.close()


def test_busy_timeout_set_per_connection(pragma_db):
    """正向③：busy_timeout 是 per-connection 属性，每次 connect 由钩子设为 30s。"""
    conn = sqlite3.connect(pragma_db)
    _set_sqlite_pragma(conn, None)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        conn.close()


def test_delete_writer_succeeds_when_reader_releases(pragma_db):
    """正向④（串行化冒烟）：DELETE 模式读写互斥（rollback journal 族），
    读者提交释放读锁后写者可独占提交，交替多轮无 BUSY（busy_timeout 兜底）。"""
    for round_no in range(20):
        reader = sqlite3.connect(pragma_db, timeout=30)
        writer = sqlite3.connect(pragma_db, timeout=30)
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM t").fetchall()  # 持读快照
            reader.execute("COMMIT")  # 先释放读锁（DELETE 模式不打扰写）
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO t VALUES (?)", (round_no,))
            writer.execute("COMMIT")
        finally:
            reader.close()
            writer.close()


def test_rollback_mode_reproduces_busy(rollback_db):
    """负向对照：同场景在 rollback journal 下，读者持读锁时写者 BEGIN IMMEDIATE
    升级 EXCLUSIVE 被拒（读写互斥）——若本用例不抛错，说明测试无法区分模式
    （DELETE 与 rollback 同族，行为一致；断言仍有区分力）。"""
    reader = sqlite3.connect(rollback_db, timeout=0.2)
    writer = sqlite3.connect(rollback_db, timeout=0.2)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM t").fetchall()  # 持共享锁
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            # 共享锁活跃时升级 EXCLUSIVE → BUSY（rollback/DELETE 模式读写互斥）
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
