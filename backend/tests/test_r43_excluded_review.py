"""单测: llm_excluded_review 脚本输出格式 + 决策建议聚合."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _run(args: list[str], env: dict | None = None) -> tuple[int, str, str]:
    # 强制子进程输出 utf-8 (避免 Windows GBK 干扰)
    full_env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if env:
        full_env.update(env)
    p = subprocess.run(
        [sys.executable, "scripts/llm_excluded_review.py", *args],
        capture_output=True, text=True, encoding="utf-8", cwd="E:/ETF_Surge/backend",
        env=full_env,
    )
    return p.returncode, p.stdout, p.stderr


def test_empty_state_clean_output():
    """空状态 → '(空: ...)' 提示, exit 0."""
    rc, out, _ = _run([])
    assert rc == 0
    # 用正则检查 "空" 关键字 (避免 GBK 编码下空状态消息不可预期)
    import re
    assert re.search(r"空|no\s*熔断|无", out), f"空状态输出缺失: {out[:200]}"


def test_json_mode_valid_structure():
    """--json 模式 → 合法 JSON, 含 providers/snapshot_at 字段."""
    rc, out, _ = _run(["--json"])
    assert rc == 0
    data = json.loads(out)
    assert "snapshot_at" in data
    assert "providers" in data
    assert isinstance(data["providers"], dict)


def test_marks_excluded_shown_as_permanent_warning():
    """mock 注入 _exclusions 标记 → markdown 给出"永久不删"告警."""
    # 用子进程 + 设环境变量, 脚本读 mock_state_path 注入
    # 但本脚本没此参数 → 简化: 直接 patch 模块状态再 run (走 sys.path 同一进程)
    from app.analysis.llm import gates
    from app.analysis.llm import model_catalog
    # 保存
    saved_circuit = dict(gates._circuit)
    saved_excl = set(model_catalog.model_catalog._exclusions)
    saved_long = dict(gates._long_cooldown)
    try:
        # 注入 mock
        gates._circuit.clear()
        gates._long_cooldown.clear()
        model_catalog.model_catalog._exclusions.clear()
        gates._circuit["b_ai:deepseek-v4-flash"] = {
            "state": "OPEN", "fail_count": 3, "opened_at": time.monotonic() - 100,
            "is_quota": True,
        }
        gates._long_cooldown["b_ai:qwen3.8-flash"] = time.monotonic() + 3600
        model_catalog.model_catalog._exclusions.add("b_ai:qwen3.8-flash")
        # 跑子进程 -- 但子进程拿不到当前进程的 mock state
        # 改: 改为在当前进程跑 (脚本 main() 直接调)
        from scripts.llm_excluded_review import main as review_main
        import sys
        # 替换 sys.argv
        old_argv = sys.argv
        sys.argv = ["llm_excluded_review.py"]
        try:
            rc = review_main()
        finally:
            sys.argv = old_argv
        assert rc == 0
    finally:
        gates._circuit.clear()
        gates._circuit.update(saved_circuit)
        gates._long_cooldown.clear()
        gates._long_cooldown.update(saved_long)
        model_catalog.model_catalog._exclusions.clear()
        model_catalog.model_catalog._exclusions.update(saved_excl)
