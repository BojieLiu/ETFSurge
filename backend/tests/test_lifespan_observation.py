"""lifespan_observation 单测 (round45 决策依据 — 数据契约稳定).

只测:
  - read_warmup_timing: 文件不存在 / 正常 / 解析错
  - read_pyinstrument_top: header 提取 / tree char 跨行匹
  - read_loop_lag_history: 无 lag 行 / 多行
  - read_perf_diag: 文件不存在 / 正常
  - build_markdown: 4 维全不可用时仍有可读骨架
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 把 scripts/ 加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# 直接 import 模块文件, 避免 scripts/ 不在 package
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "lifespan_observation",
    Path(__file__).resolve().parent.parent / "scripts" / "lifespan_observation.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
read_warmup_timing = mod.read_warmup_timing
read_pyinstrument_top = mod.read_pyinstrument_top
read_loop_lag_history = mod.read_loop_lag_history
read_perf_diag = mod.read_perf_diag
build_markdown = mod.build_markdown


def test_warmup_timing_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    r = read_warmup_timing()
    assert r["available"] is False
    assert "not found" in r["reason"].lower()


def test_warmup_timing_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    (tmp_path / "warmup_timing.json").write_text(
        json.dumps({
            "total_duration_ms": 1234.5,
            "records": [
                {"label": "init_db", "duration_ms": 100.0, "category": "db", "note": "DB init"},
                {"label": "warmup_market", "duration_ms": 1000.0, "category": "warmup", "note": "market"},
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    r = read_warmup_timing()
    assert r["available"] is True
    assert r["data"]["total_duration_ms"] == 1234.5


def test_pyinstrument_top_header_extracts(tmp_path, monkeypatch):
    """pyinstrument 行首是 ASCII art + Recorded: 13:41:22, 应解析 header."""
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    fake = b"""
  _     ._   __/__   _ _  _  _ _/_   Recorded: 13:41:22  Samples:  820
 /_//_/// /_\\ / //_// / //_'/ //     Duration: 41.855    CPU time: 13.381
/   _/                      v5.1.3

41.856 MainThread  <thread>:140178779407232
\xe2\x94\x94\xe2\x94\x80 41.724 <module>  <string>:1
         41.724 Runner.run  asyncio/runners.py:88
         \xe2\x94\x9c\xe2\x94\x80 7.992 _guarded  scripts/sync_instruments.py:118
"""
    (tmp_path / "warmup_pyinstrument.txt").write_bytes(fake)
    r = read_pyinstrument_top()
    assert r["available"] is True
    assert r["header"]["samples"] == 820
    assert r["header"]["duration_s"] == 41.855
    # 应有 3 帧 (Runner.run / _guarded; MainThread / <module> 被 HIDE_RE 过滤)
    visible = [f for f in r["top_frames"] if f["function"] not in ("<thread>", "<string>")]
    assert len(visible) >= 2
    assert visible[0]["function"] == "Runner.run"
    assert visible[0]["file"] == "asyncio/runners.py"
    assert visible[0]["line"] == 88


def test_loop_lag_history_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    (tmp_path / "backend.log").write_text(
        "2026-08-28 INFO startup ok\n2026-08-28 INFO hello\n",
        encoding="utf-8",
    )
    r = read_loop_lag_history()
    assert r["available"] is False


def test_loop_lag_history_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    (tmp_path / "backend.log").write_text(
        "2026-08-28 10:55:41 WARNING  [app.core.loop_watchdog] [loop_watchdog] "
        "event loop lag 5.33s ≥ 5.0s — 87 live tasks, stacks -> x\n"
        "2026-08-28 10:55:58 WARNING  [app.core.loop_watchdog] [loop_watchdog] "
        "event loop lag 10.38s ≥ 5.0s — 17 live tasks, stacks -> y\n",
        encoding="utf-8",
    )
    r = read_loop_lag_history()
    assert r["available"] is True
    assert r["count"] == 2
    assert r["max_lag_s"] == 10.38
    assert r["ge_5s_count"] == 2


def test_perf_diag_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    r = read_perf_diag()
    assert r["available"] is False


def test_build_markdown_all_missing(tmp_path, monkeypatch):
    """4 维全不可用时仍应产出可读 markdown 骨架."""
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    w = read_warmup_timing()
    p = read_pyinstrument_top()
    l = read_loop_lag_history()
    d = read_perf_diag()
    md = build_markdown(w, p, l, d)
    assert "# Lifespan 长尾观测报告" in md
    assert "## 1. Lifespan 启动期 6 阶段耗时" in md
    assert "## 2. 主线程栈帧耗时" in md
    assert "## 3. 事件循环 lag 历史" in md
    assert "## 4. E2E 端点实测耗时" in md
    assert "## 5. 决策依据" in md
    # 不可用分支的提示文本
    assert "不可用" in md
