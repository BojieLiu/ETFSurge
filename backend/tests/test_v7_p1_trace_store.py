"""v7 P1: TraceStore 单测——JSONL 落盘 + tail + 失败不阻断。

RunReport 构造走真实 agent_loop 模型（非 mock dict），保证 dump 结构与实现同步。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.agentic.agent_loop import PlanStep, RunReport, RunStep
from app.agentic.trace_store import TraceStore


def _report(**kw) -> RunReport:
    step = RunStep(index=0, tool="get_realtime_quote",
                   arguments={"symbols": ["510300"]},
                   output={"data": 1, "source": "sina"},
                   source="sina", duration_ms=12.3)
    return RunReport(trace_id=kw.get("trace_id", "t" * 16),
                     steps=kw.get("steps", [step]),
                     partial=kw.get("partial", False),
                     degraded=kw.get("degraded", False),
                     summary_note=kw.get("summary_note", ""),
                     elapsed_ms=15.0,
                     stopped_reason="completed")


class TestTraceStore:
    def test_record_appends_jsonl(self, tmp_path):
        store = TraceStore(path=tmp_path / "traces.jsonl")
        assert store.record(_report()) is True
        lines = (tmp_path / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        import json
        entry = json.loads(lines[0])
        assert entry["trace_id"] == "t" * 16
        assert entry["stopped_reason"] == "completed"
        assert entry["steps"][0]["tool"] == "get_realtime_quote"

    def test_record_includes_missing_data_semantics(self, tmp_path):
        """data_missing 步的 trace 含标记（反幻觉审计依据）。"""
        store = TraceStore(path=tmp_path / "t.jsonl")
        miss = RunStep(index=0, tool="get_factor_snapshot", arguments={},
                       data_missing=True, degraded=True,
                       error="timeout after 0.05s budget")
        store.record(_report(steps=[miss], degraded=True,
                             summary_note="数据缺失: get_factor_snapshot（不编造，如实标注）"))
        import json
        entry = json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8"))
        assert entry["steps"][0]["data_missing"] is True
        assert "数据缺失" in entry["summary_note"]

    def test_tail_reads_recent(self, tmp_path):
        store = TraceStore(path=tmp_path / "t.jsonl")
        for i in range(3):
            store.record(_report(trace_id=f"id{i:016x}"))
        tail = store.tail(2)
        assert len(tail) == 2
        assert tail[-1]["trace_id"] == "id0000000000000002"

    def test_record_failure_does_not_raise(self, tmp_path):
        """trace 是观测设施：写失败返回 False 不抛（不阻断业务主流程）。"""
        store = TraceStore(path=tmp_path / "no-such-dir" / "sub" / "t.jsonl")
        # 制造不可写路径：把 path 指向一个"目录"位置
        store.path = tmp_path  # 目录本身当文件写 -> 失败
        (tmp_path).mkdir(exist_ok=True)
        assert store.record(_report()) is False

    def test_tail_empty_when_missing_file(self, tmp_path):
        store = TraceStore(path=tmp_path / "absent.jsonl")
        assert store.tail() == []
