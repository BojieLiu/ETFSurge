"""
PoolAudit: in-memory audit log for PoolManager refresh events.

Tracks pool changes (added/removed/changed ETFs) across refresh cycles.
Production use can persist to SQLite or log file.

Usage:
    from app.services.pool_audit import pool_audit
    pool_audit.log_refresh(diff)
    history = pool_audit.get_history(limit=10)
"""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PoolAudit:
    """审计日志：记录候选池每次 refresh 的变化。"""

    def __init__(self, max_entries: int = 100):
        self._entries: list[dict[str, Any]] = []
        self._max_entries = max_entries

    def log_refresh(self, diff: Any) -> None:
        """记录一次 refresh 事件。

        Args:
            diff: PoolDiff 对象（有 added/removed/changed/version/timestamp 字段）
        """
        entry = {
            "version": diff.version,
            "timestamp": diff.timestamp or datetime.now().isoformat(),
            "added": [e.get("symbol", "") for e in getattr(diff, "added", [])],
            "removed": [e.get("symbol", "") for e in getattr(diff, "removed", [])],
            "changed": [e.get("symbol", "") for e in getattr(diff, "changed", [])],
        }
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        logger.info(
            "PoolAudit v%s: +%d -%d ~%d",
            diff.version,
            len(entry["added"]),
            len(entry["removed"]),
            len(entry["changed"]),
        )

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取历史记录，按时间倒序。"""
        entries = sorted(self._entries, key=lambda e: e["timestamp"], reverse=True)
        return entries[:limit]

    def get_last_refresh(self) -> dict[str, Any] | None:
        """获取最近一次 refresh 记录。"""
        if not self._entries:
            return None
        return max(self._entries, key=lambda e: e["timestamp"])


# Global singleton
pool_audit = PoolAudit()
