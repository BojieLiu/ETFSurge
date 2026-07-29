"""Tests for app/services/snapshot_service.py — local snapshot fallback."""

import json
import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.services.snapshot_service import SnapshotService


@pytest.fixture
def snap_dir(tmp_path):
    """Use a temp directory for snapshot storage."""
    return tmp_path / "snapshots"


@pytest.fixture
def service(snap_dir):
    """Create a SnapshotService with temp directory."""
    return SnapshotService(snapshot_dir=snap_dir)


class TestSnapshotService:
    def test_save_and_load(self, service, snap_dir):
        """Save data and load it back."""
        service.save_snapshot("test_key", {"a": 1, "b": [2, 3, 4]})
        result = service.load_snapshot("test_key")
        assert result == {"a": 1, "b": [2, 3, 4]}

    def test_load_missing(self, service):
        """Loading a non-existent key returns None."""
        result = service.load_snapshot("nonexistent")
        assert result is None

    def test_load_expired(self, service):
        """Loading an expired snapshot returns None."""
        service.save_snapshot("expired_key", "old data")
        result = service.load_snapshot("expired_key", max_age_hours=0)
        # max_age_hours=0 means anything older than 0 hours is expired
        # Since we saved it (takes a few ms), it should be slightly expired
        assert result is None

    def test_clear_snapshot(self, service, snap_dir):
        """Clearing removes the file."""
        service.save_snapshot("clear_me", "data")
        assert (snap_dir / "clear_me.json").exists()
        service.clear_snapshot("clear_me")
        assert not (snap_dir / "clear_me.json").exists()

    def test_clear_all(self, service, snap_dir):
        """Clearing all removes all JSON files."""
        service.save_snapshot("k1", 1)
        service.save_snapshot("k2", 2)
        service.save_snapshot("k3", 3)
        assert len(list(snap_dir.glob("*.json"))) == 3
        service.clear_all()
        assert len(list(snap_dir.glob("*.json"))) == 0

    def test_thread_safety(self, service):
        """Concurrent save/load operations are safe."""
        errors = []

        def worker(key: str):
            try:
                for _ in range(10):
                    service.save_snapshot(key, {"thread": key, "iter": _})
                    loaded = service.load_snapshot(key)
                    assert loaded is not None
                    assert loaded["thread"] == key
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_non_serializable_data(self, service):
        """Handle non-serializable data gracefully (falls back to str conversion)."""
        from datetime import datetime

        data = {"name": "test", "timestamp": datetime.now()}
        service.save_snapshot("non_serial", data)
        result = service.load_snapshot("non_serial")
        assert result is not None
        assert result["name"] == "test"
        # datetime should have been converted to string via default=str
        assert isinstance(result["timestamp"], str)

    def test_sanitize_key(self, service):
        """Sanitize special characters in keys."""
        service.save_snapshot("my/key:bad?chars", "data")
        result = service.load_snapshot("my/key:bad?chars")
        assert result == "data"

    def test_corrupted_file(self, service, snap_dir):
        """Corrupted snapshot files are handled gracefully."""
        bad_file = snap_dir / "corrupted.json"
        bad_file.write_text("not valid json{{{")
        result = service.load_snapshot("corrupted")
        assert result is None
        # Corrupted file should be cleaned up
        assert not bad_file.exists()

    def test_empty_data(self, service):
        """Save and load empty/null data."""
        service.save_snapshot("empty", {})
        assert service.load_snapshot("empty") == {}
        service.save_snapshot("null_val", None)
        assert service.load_snapshot("null_val") is None

    def test_concurrent_same_key(self, service):
        """Multiple threads writing to the same key."""
        results = set()

        def writer(value: int):
            service.save_snapshot("shared", value)
            loaded = service.load_snapshot("shared")
            results.add(loaded)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least one of the writes should have succeeded
        assert len(results) > 0
        assert all(isinstance(r, int) for r in results)
