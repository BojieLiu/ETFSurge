"""Agentic trace 存储（v7 P1 §6 轻量自建；P2 升 SQLite 面板）。

- 每 run 一条 trace（RunReport.dump()），JSONL 追加写 logs/agentic_traces.jsonl
- P2 升级路径（§6 REVIEW-R1-7 修订：轻量自建起步）：SQLite 面板 + Langfuse
  export——本类只留 tail() 读入口与 record() 写入口，P2 在此文件扩展
  export_sqlite()/export_langfuse()（勿在别处另起 store）。
- 记录失败不阻断主流程（trace 是观测设施，不是业务依赖）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from .agent_loop import RunReport

logger = get_logger(__name__)

_DEFAULT_PATH = Path("logs/agentic_traces.jsonl")


class TraceStore:
    """RunReport -> JSONL 追加存储（线程安全由调用方保证；async 场景经 run_sync）。"""

    def __init__(self, path: Path | None = None):
        self.path = path or _DEFAULT_PATH

    def record(self, report: "RunReport") -> bool:
        """落一条 trace；失败仅 WARNING 不抛（观测设施不阻断业务）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "trace_id": report.trace_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "stopped_reason": report.stopped_reason,
                "partial": report.partial,
                "degraded": report.degraded,
                "elapsed_ms": round(report.elapsed_ms, 1),
                "summary_note": report.summary_note,
                "steps": [
                    {
                        "index": s.index,
                        "tool": s.tool,
                        "arguments": s.arguments,
                        "source": s.source,
                        "degraded": s.degraded,
                        "data_missing": s.data_missing,
                        "error": s.error,
                        "duration_ms": round(s.duration_ms, 1),
                        "skipped": s.skipped,
                    }
                    for s in report.steps
                ],
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[agentic] trace record failed: %s", exc)
            return False

    def tail(self, n: int = 20) -> list[dict]:
        """读最近 n 条 trace（admin 观测入口预留）。"""
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            return [json.loads(x) for x in lines[-n:] if x.strip()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[agentic] trace tail failed: %s", exc)
            return []


trace_store = TraceStore()
