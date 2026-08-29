"""R50 B2: llm_error_timeseries 单测.

覆盖:
  - classify_error 各错误码
  - bucket_ts 按 hour/day 粒度截断
  - query_records DB 不存在返 []
  - analyze 聚合逻辑 (overall / provider / code / 异常窗口)
  - render_markdown 输出包含关键章节
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


# ── 1. classify_error ──────────────────────────────────────────


def test_classify_error_401():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    assert mod.classify_error("'401 Authorization Required'") == "401"


def test_classify_error_429():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    assert mod.classify_error("HTTP 429") == "429"
    assert mod.classify_error("'429 Too Many Requests'") == "429"


def test_classify_error_timeout():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    assert mod.classify_error("wait_for timeout") == "timeout"
    assert mod.classify_error("TimeoutError") == "timeout"


def test_classify_error_empty_unknown():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    assert mod.classify_error("") == "empty"
    assert mod.classify_error("random unknown text") == "unknown"


# ── 2. bucket_ts ──────────────────────────────────────────


def test_bucket_ts_day_granularity():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    # 2026-08-29 18:30:45 UTC
    ts = datetime(2026, 8, 29, 18, 30, 45, tzinfo=timezone.utc).timestamp()
    assert mod.bucket_ts(ts, "day") == "2026-08-29"


def test_bucket_ts_hour_granularity():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    ts = datetime(2026, 8, 29, 18, 30, 45, tzinfo=timezone.utc).timestamp()
    assert mod.bucket_ts(ts, "hour") == "2026-08-29 18:00"


def test_bucket_ts_hour_minute_59_truncates():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    ts = datetime(2026, 8, 29, 18, 59, 59, tzinfo=timezone.utc).timestamp()
    assert mod.bucket_ts(ts, "hour") == "2026-08-29 18:00"


# ── 3. query_records DB 不存在 ──────────────────────────


def test_query_records_db_not_exist(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    fake_db = tmp_path / "nonexistent.db"
    records = mod.query_records(fake_db, 0.0)
    assert records == []


# ── 4. analyze 聚合 ──────────────────────────────────


def _make_db_with_records(tmp_path: Path) -> Path:
    """构造测试 DB: 4 个 provider × 7 天 × 2 success/fail."""
    db = tmp_path / "test_token_usage.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("""
            CREATE TABLE usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_name TEXT, prompt_tokens INT, completion_tokens INT,
                total_tokens INT, model TEXT, timestamp REAL, success INT,
                duration_ms REAL, error_message TEXT, provider TEXT
            )
        """)
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        rows = []
        # 3 天前: provider=zen, 10 success + 2 fail (429)
        for i in range(12):
            ts = (now - timedelta(days=3, hours=i)).timestamp()
            err = "'429 Too Many Requests'" if i >= 10 else ""
            rows.append(("f", 1, 1, 2, "m", ts, 0 if err else 1, 100.0, err, "opencode_zen"))
        # 2 天前: provider=deepseek, 5 success + 1 fail (timeout)
        for i in range(6):
            ts = (now - timedelta(days=2, hours=i)).timestamp()
            err = "wait_for timeout" if i == 5 else ""
            rows.append(("f", 1, 1, 2, "m", ts, 0 if err else 1, 100.0, err, "deepseek"))
        # 1 天前: provider=openrouter, 3 success + 3 fail (503) → 50% 错误率, 触发异常窗口
        for i in range(6):
            ts = (now - timedelta(days=1, hours=i)).timestamp()
            err = "'503 Service Unavailable'" if i >= 3 else ""
            rows.append(("f", 1, 1, 2, "m", ts, 0 if err else 1, 100.0, err, "openrouter"))
        # 今天: provider=zen, 4 success
        for i in range(4):
            ts = (now - timedelta(hours=i)).timestamp()
            rows.append(("f", 1, 1, 2, "m", ts, 1, 100.0, "", "opencode_zen"))
        conn.executemany(
            "INSERT INTO usage_records (function_name, prompt_tokens, completion_tokens, "
            "total_tokens, model, timestamp, success, duration_ms, error_message, provider) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )
    return db


def test_analyze_aggregate(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    db = _make_db_with_records(tmp_path)
    records = mod.query_records(db, 0.0)
    assert len(records) == 28

    result = mod.analyze(records, "day")
    # 6 fail out of 28 → 21.4%
    assert result["total_calls"] == 28
    assert result["total_errors"] == 6
    assert abs(result["overall_error_rate"] - 0.2143) < 0.01
    # 3 个 provider: opencode_zen / deepseek / openrouter
    assert set(result["provider_bucket"].keys()) == {"opencode_zen", "deepseek", "openrouter"}
    # 错误码: 429 / timeout / 503
    assert "429" in result["code_bucket"]
    assert "timeout" in result["code_bucket"]
    assert "503" in result["code_bucket"]


def test_analyze_alert_buckets(tmp_path):
    """单 bucket 错误率 ≥ 30% 且 calls ≥ 5 → 异常窗口."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    db = _make_db_with_records(tmp_path)
    records = mod.query_records(db, 0.0)
    result = mod.analyze(records, "day")
    # openrouter 那天 6 calls / 3 fail = 50% → 触发
    assert any(a["rate"] >= 0.3 and a["calls"] >= 5 for a in result["alert_buckets"])


def test_render_markdown_contains_key_sections(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    db = _make_db_with_records(tmp_path)
    records = mod.query_records(db, 0.0)
    result = mod.analyze(records, "day")
    md = mod.render_markdown(result, "day", 168.0)
    assert "# LLM 错误率时序分析 (R50 B2)" in md
    assert "## 1. 整体时序" in md
    assert "## 2. Provider x Bucket 错误率" in md
    assert "## 3. 错误码 x Bucket 错误数" in md
    assert "## 4. 异常窗口" in md
    # provider 名字出现
    assert "opencode_zen" in md
    assert "openrouter" in md


def test_render_markdown_empty_data():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import llm_error_timeseries as mod
    empty = {
        "total_calls": 0, "total_errors": 0, "overall_error_rate": 0.0,
        "buckets_count": 0, "overall_bucket": {}, "provider_bucket": {},
        "code_bucket": {}, "alert_buckets": [],
    }
    md = mod.render_markdown(empty, "day", 168.0)
    assert "(无数据" in md
    assert "## 1. 整体时序" in md
