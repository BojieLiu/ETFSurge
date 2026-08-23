"""round35 A5 (docs/round35-architecture-review.md §13.9 T-A5) —

audit_async_blocking 门禁自身被测试（D1 负向 fixture 思路的第二实例）：
- P-a/P-b：async def 体内直接 open()/sqlite3.* → FAIL（防门禁静默通过回归）；
- 边界：await run_sync(...) 形态不报（豁免路径仍生效）；
- P-c：嵌套 sync def 含阻塞且未被 to_thread/run_sync 包装 → WARN；被包装 → 不报。
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_async_blocking import (  # noqa: E402
    _scan_unwrapped_nested_sync,
    scan_file,
)


def _write(tmp_path: Path, code: str) -> str:
    f = tmp_path / "probe_mod.py"
    f.write_text(code, encoding="utf-8")
    return str(f)


def test_pa_direct_open_in_async_fails(tmp_path):
    """负向①：async 体内直接 open() → 必须命中（门禁静默通过 = D1 盲区回归）。"""
    path = _write(tmp_path, (
        "def helper():\n"
        "    pass\n\n\n"
        "async def refresh_cache():\n"
        "    with open('x.json', 'w') as f:\n"
        "        f.write('{}')\n"
    ))
    violations = scan_file(path)
    assert any("open" in v and "refresh_cache" in v for v in violations), violations


def test_pb_direct_sqlite3_in_async_fails(tmp_path):
    """负向②：async 体内直接 sqlite3.connect → 必须命中。"""
    path = _write(tmp_path, (
        "import sqlite3\n\n\n"
        "async def flush_batch(rows):\n"
        "    conn = sqlite3.connect('x.db')\n"
        "    conn.executemany('INSERT INTO t VALUES (?)', rows)\n"
        "    conn.commit()\n"
    ))
    violations = scan_file(path)
    assert any("sqlite3.connect" in v and "flush_batch" in v for v in violations), violations


def test_wrapped_open_via_run_sync_not_reported(tmp_path):
    """边界：await run_sync(open_and_write) 形态 → 不报（豁免路径生效）。"""
    path = _write(tmp_path, (
        "async def persist(payload):\n"
        "    def _write_file():\n"
        "        with open('x.json', 'w') as f:\n"
        "            f.write(payload)\n"
        "\n"
        "    await run_sync(_write_file)\n"
    ))
    assert scan_file(path) == []


def test_pc_nested_sync_without_wrapper_warns(tmp_path):
    """P-c：嵌套 sync def 含阻塞、函数名未见 to_thread/run_sync 包装 → WARN。"""
    path = _write(tmp_path, (
        "import sqlite3\n\n\n"
        "async def worker():\n"
        "    def _flush(rows):\n"
        "        conn = sqlite3.connect('x.db')\n"
        "        conn.executemany('INSERT INTO t VALUES (?)', rows)\n"
        "\n"
        "    while True:\n"
        "        _flush([])\n"
    ))
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    warns = _scan_unwrapped_nested_sync(tree, path)
    assert warns and "_flush" in warns[0] and "[WARN]" in warns[0]


def test_pc_nested_sync_with_to_thread_no_warn(tmp_path):
    """P-c 合法例：同款嵌套 sync def 被 asyncio.to_thread 包装 → 无 WARN。"""
    path = _write(tmp_path, (
        "import sqlite3\n\n\n"
        "async def worker():\n"
        "    def _query():\n"
        "        conn = sqlite3.connect('x.db')\n"
        "        return conn.execute('SELECT 1').fetchall()\n"
        "\n"
        "    return await asyncio.to_thread(_query)\n"
    ))
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    assert _scan_unwrapped_nested_sync(tree, path) == []


def test_real_app_tree_passes_gate():
    """全量扫描当前 app/ 树：实锤修复后（source_events to_thread /
    _regime_sentiment round36 已修）应零 FAIL。"""
    import audit_async_blocking as aab

    rc = aab.main()
    assert rc == 0
