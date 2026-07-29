"""
Local snapshot fallback — last-known-good data for when all data sources fail.

S3 from system-diagnosis-and-optimization-plan.md: 本地快照兜底

Stores/retrieves data as JSON files in a configurable snapshot directory.
Thread-safe with per-file locks.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "snapshots"


class SnapshotService:
    """Local snapshot storage for data-source fallback.

    Each snapshot is a JSON file named ``{key}.json`` in the snapshot directory.
    Thread-safe with a per-key lock dict for concurrent access.
    """

    def __init__(self, snapshot_dir: str | Path | None = None) -> None:
        self._dir = Path(snapshot_dir) if snapshot_dir else _DEFAULT_SNAPSHOT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        logger.info("[snapshot] initialized at %s", self._dir)

    def _get_lock(self, key: str) -> threading.Lock:
        """Get or create a per-key lock."""
        if key not in self._locks:
            with self._global_lock:
                if key not in self._locks:
                    self._locks[key] = threading.Lock()
        return self._locks[key]

    def _sanitize_key(self, key: str) -> str:
        """Sanitize key to a safe filename."""
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return safe if safe else "default"

    def _path_for(self, key: str) -> Path:
        return self._dir / f"{self._sanitize_key(key)}.json"

    def save_snapshot(self, key: str, data: Any) -> None:
        """Save a snapshot to disk.

        Args:
            key: Snapshot identifier.
            data: Any JSON-serializable value.
        """
        lock = self._get_lock(key)
        with lock:
            path = self._path_for(key)
            try:
                payload = {
                    "key": key,
                    "timestamp": time.time(),
                    "timestamp_iso": datetime.utcnow().isoformat(),
                    "data": data,
                }
                tmp = path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, default=str)
                tmp.replace(path)
                logger.debug("[snapshot] saved %s (%d bytes)", key, os.path.getsize(path))
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("[snapshot] failed to save %s: %s", key, exc)

    def load_snapshot(self, key: str, max_age_hours: int = 24) -> Any | None:
        """Load a snapshot if it exists and is not too old.

        Args:
            key: Snapshot identifier.
            max_age_hours: Maximum age in hours (default 24).

        Returns:
            Stored data, or None if missing/expired/corrupted.
        """
        lock = self._get_lock(key)
        with lock:
            path = self._path_for(key)
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload: dict = json.load(f)
                age_hours = (time.time() - payload.get("timestamp", 0)) / 3600
                if age_hours > max_age_hours:
                    logger.debug("[snapshot] %s expired (%.1f hours > %d hours)",
                                 key, age_hours, max_age_hours)
                    return None
                logger.debug("[snapshot] loaded %s (age=%.1f hours)", key, age_hours)
                return payload.get("data")
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("[snapshot] failed to load %s: %s", key, exc)
                # Corrupted file — remove it
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None

    def clear_snapshot(self, key: str) -> None:
        """Delete a snapshot file."""
        lock = self._get_lock(key)
        with lock:
            path = self._path_for(key)
            try:
                if path.exists():
                    path.unlink()
                    logger.debug("[snapshot] cleared %s", key)
            except OSError as exc:
                logger.warning("[snapshot] failed to clear %s: %s", key, exc)

    def clear_all(self) -> None:
        """Delete all snapshot files."""
        for path in self._dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
        logger.debug("[snapshot] cleared all snapshots")


# Module-level singleton for use across the app
snapshot_service = SnapshotService()
