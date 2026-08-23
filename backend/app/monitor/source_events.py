"""Source event monitoring — in-memory ring buffer + SQLite persistence.

Reuses the pattern from monitor/token_usage.py for consistency:
- Memory ring buffer (5000 records) for fast queries
- Async batch flush to SQLite (data/source.db)
- 7-day rolling cleanup
"""

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings


@dataclass
class SourceEvent:
    """A single data-source access event (success or failure)."""
    source_name: str       # 'mootdx' / 'sina' / 'twelvedata' / ...
    route: str             # 'A_stock_realtime' / 'US_ETF' / 'probe' / ...
    operation: str         # 'realtime' / 'history' / 'probe' / 'batch'
    target: str            # '000001' / 'SPY' / '510050' / ...
    success: bool          # True=ok, False=failure
    duration_ms: float     # how long the call took
    error_message: str     # empty on success
    timestamp: float       # unix epoch


class SourceEventStore:
    """Process-level source event store with async SQLite persistence.

    - Memory ring buffer: keeps last max_records events
    - Async batch flush worker: writes to data/source.db every 100 events or 5s
    - Daily old-data cleanup: DELETE events older than 7 days
    """

    def __init__(self, max_records: int = 5000):
        self._records: list[SourceEvent] = []
        self._lock = asyncio.Lock()
        self._max = max_records
        self._db_path = self._get_db_path()
        self._flush_queue: asyncio.Queue = asyncio.Queue()
        self._flush_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._init_db()
        self._db_ready = True

    # ── Public API ────────────────────────────────────────────

    async def record(self, event: SourceEvent) -> None:
        """Record a source event (thread-safe, non-blocking)."""
        self._ensure_tasks()
        async with self._lock:
            self._records.append(event)
            if len(self._records) > self._max:
                self._records = self._records[-self._max // 2:]
        self._flush_queue.put_nowait(event)

    async def recent_failures(self, limit: int = 20) -> list[dict]:
        """Return most recent failure events."""
        async with self._lock:
            fails = [r for r in self._records if not r.success]
            fails = fails[-limit:]
            return [self._to_dict(e) for e in fails]

    async def timeline(
        self, hours: float = 1, granularity_secs: int = 60
    ) -> list[dict]:
        """Return time-bucketed event counts."""
        now = time.time()
        cutoff = now - hours * 3600
        async with self._lock:
            relevant = [r for r in self._records if r.timestamp >= cutoff]

        buckets: dict[float, dict] = {}
        for e in relevant:
            bucket_start = (e.timestamp // granularity_secs) * granularity_secs
            if bucket_start not in buckets:
                buckets[bucket_start] = {
                    "bucket": datetime.fromtimestamp(
                        bucket_start, tz=timezone.utc
                    ).isoformat(),
                    "success": 0,
                    "failure": 0,
                    "total": 0,
                }
            buckets[bucket_start]["total"] += 1
            if e.success:
                buckets[bucket_start]["success"] += 1
            else:
                buckets[bucket_start]["failure"] += 1
        return [buckets[k] for k in sorted(buckets.keys())]

    async def health_summary(self) -> list[dict]:
        """Aggregate per-source health stats from memory records."""
        async with self._lock:
            if not self._records:
                return []
            sources: dict[str, dict] = {}
            for e in reversed(self._records[-500:]):
                sn = e.source_name
                if sn not in sources:
                    sources[sn] = {
                        "name": sn,
                        "total_calls": 0,
                        "failures": 0,
                        "last_ok": 0.0,
                        "last_error": "",
                    }
                s = sources[sn]
                s["total_calls"] += 1
                if e.success:
                    s["last_ok"] = max(s["last_ok"], e.timestamp)
                else:
                    s["failures"] += 1
                    s["last_error"] = e.error_message or ""
            return list(sources.values())

    async def shutdown(self) -> None:
        """Flush pending events and cancel background tasks."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):
                pass
        # Final flush of remaining queue
        remaining: list[SourceEvent] = []
        while not self._flush_queue.empty():
            try:
                remaining.append(self._flush_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            self._flush_batch(remaining)

    # ── Internal ─────────────────────────────────────────────

    def _get_db_path(self) -> Path:
        data_dir = Path(settings.database_url.replace("sqlite+aiosqlite:///", "")).parent
        return data_dir / "source.db"

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name     TEXT    NOT NULL,
                    route           TEXT    NOT NULL DEFAULT '',
                    operation       TEXT    NOT NULL DEFAULT 'realtime',
                    target          TEXT    NOT NULL DEFAULT '',
                    success         INTEGER NOT NULL,
                    duration_ms     REAL    NOT NULL DEFAULT 0,
                    error_message   TEXT    NOT NULL DEFAULT '',
                    timestamp       REAL    NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_se_source ON source_events(source_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_se_ts ON source_events(timestamp)"
            )
            conn.commit()

    def _ensure_tasks(self) -> None:
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_worker())
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_worker())

    async def _flush_worker(self) -> None:
        batch: list[SourceEvent] = []
        try:
            while True:
                try:
                    entry = await asyncio.wait_for(
                        self._flush_queue.get(), timeout=5.0
                    )
                    batch.append(entry)
                except asyncio.TimeoutError:
                    pass

                if len(batch) >= 100 or (batch and self._flush_queue.empty()):
                    self._flush_batch(batch)
                    batch.clear()
        except asyncio.CancelledError:
            if batch:
                self._flush_batch(batch)
            raise

    def _flush_batch(self, batch: list[SourceEvent]) -> None:
        if not batch:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executemany(
                    """INSERT INTO source_events
                       (source_name, route, operation, target, success,
                        duration_ms, error_message, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(e.source_name, e.route, e.operation, e.target,
                      int(e.success), e.duration_ms, e.error_message, e.timestamp)
                     for e in batch]
                )
                conn.commit()
        except Exception:
            pass  # Silent: don't let persistence failures cascade

    async def _cleanup_worker(self) -> None:
        """Daily cleanup: DELETE events older than 7 days."""
        def _delete_old() -> None:
            # round35 A5 (§13.9 T-A5): 同步 sqlite 移入线程池——原直接跑在 async
            # 体内阻塞事件循环（audit_async_blocking P-b pattern 实锤点）。
            try:
                cutoff = time.time() - 7 * 86400
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        "DELETE FROM source_events WHERE timestamp < ?",
                        (cutoff,)
                    )
                    conn.commit()
            except Exception:
                pass
        try:
            while True:
                await asyncio.sleep(86400)  # once per day
                await asyncio.to_thread(_delete_old)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _to_dict(event: SourceEvent) -> dict:
        return {
            "id": id(event),  # runtime reference, not DB id
            "source_name": event.source_name,
            "route": event.route,
            "operation": event.operation,
            "target": event.target,
            "success": event.success,
            "error_message": event.error_message,
            "duration_ms": event.duration_ms,
            "timestamp": event.timestamp,
        }


# Global singleton (same pattern as token_store)
source_event_store = SourceEventStore()
