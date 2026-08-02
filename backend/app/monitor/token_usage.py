"""DeepSeek token 用量监控 — 进程内存 + SQLite 持久化。"""

import time
import asyncio
import sqlite3
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

from ..config import settings


@dataclass
class UsageRecord:
    """单次 LLM 调用的 token 消耗记录。"""
    function_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    timestamp: float
    success: bool
    duration_ms: float
    error_message: str = ""
    provider: str = ""


class TokenUsageStore:
    """进程内 token 使用统计（async 线程安全）+ SQLite 持久化。

    - 内存中保留最近 max_records 条，供快速查询
    - SQLite 持久化所有记录，重启不丢失
    - 记录写入采用批量异步刷盘，不阻塞请求
    """

    def __init__(self, max_records: int = 10000):
        self._records: list[UsageRecord] = []
        self._lock = asyncio.Lock()
        self._max = max_records
        self._db_path = self._get_db_path()
        self._flush_queue: asyncio.Queue = asyncio.Queue()
        self._flush_task: asyncio.Task | None = None
        self._db_ready = False
        self._init_db()

    def _ensure_flush_task(self) -> None:
        """确保后台刷盘任务已启动（需在事件循环中调用）。"""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_worker())

    def _get_db_path(self) -> Path:
        # 复用项目的 data 目录
        data_dir = Path(settings.database_url.replace("sqlite+aiosqlite:///", "")).parent
        return data_dir / "token_usage.db"

    def _init_db(self) -> None:
        """初始化 SQLite 表并加载历史数据。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    function_name TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    success INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    error_message TEXT DEFAULT '',
                    provider TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_records(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_function ON usage_records(function_name)")

            # Migration: add provider column if it doesn't exist (pre-v0.9 DBs)
            try:
                conn.execute("ALTER TABLE usage_records ADD COLUMN provider TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # column already exists

            conn.commit()

        # 启动时加载最近记录到内存
        self._load_recent()

    def _row_to_record(self, row) -> UsageRecord:
        """SQLite Row → UsageRecord。"""
        return UsageRecord(
            function_name=row["function_name"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"],
            model=row["model"],
            timestamp=row["timestamp"],
            success=bool(row["success"]),
            duration_ms=row["duration_ms"],
            error_message=row["error_message"] or "",
            provider=row["provider"] if "provider" in row.keys() else "",
        )

    def _load_recent(self) -> None:
        """从 DB 加载最近 max_records 条到内存。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM usage_records ORDER BY id DESC LIMIT ?",
                (self._max,)
            ).fetchall()
        # 倒序存入，保持时间正序
        for row in reversed(rows):
            self._records.append(self._row_to_record(row))

    def _drain_pending(self) -> None:
        """R56 ③: 查询前把内存队列中未落盘的记录强制刷入 SQLite。

        否则 summary/timeseries 改读 DB 后会丢最近未 flush 的记录。
        """
        batch = []
        while not self._flush_queue.empty():
            try:
                batch.append(self._flush_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            self._flush_batch(batch)

    async def _load_all_from_db(self, cutoff_ts: float | None = None) -> list[UsageRecord]:
        """R56 ③: 从 SQLite 读全量记录（消除 self._records 截断影响）。

        查询前先强制落盘队列中的新记录；同步 sqlite3 放入线程池避免阻塞事件循环。
        cutoff_ts: 只取 timestamp >= cutoff_ts 的记录（窗口过滤下推到 SQL）。
        """
        def _query() -> list[UsageRecord]:
            self._drain_pending()
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                if cutoff_ts is not None:
                    rows = conn.execute(
                        "SELECT * FROM usage_records WHERE timestamp >= ?",
                        (cutoff_ts,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM usage_records").fetchall()
            return [self._row_to_record(r) for r in rows]

        return await asyncio.to_thread(_query)

    async def record(self, entry: UsageRecord) -> None:
        """记录一次调用（内存 + 入队异步持久化）。"""
        self._ensure_flush_task()
        async with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max:
                self._records = self._records[-self._max // 2:]
        # 非阻塞入队
        self._flush_queue.put_nowait(entry)

    async def _flush_worker(self) -> None:
        """后台批量刷盘，每 100 条或 5 秒刷一次。"""
        batch = []
        try:
            while True:
                # 等待新记录或超时
                try:
                    entry = await asyncio.wait_for(self._flush_queue.get(), timeout=5.0)
                    batch.append(entry)
                except asyncio.TimeoutError:
                    pass

                # 积累 100 条或队列空时刷盘
                if len(batch) >= 100 or (batch and self._flush_queue.empty()):
                    self._flush_batch(batch)
                    batch.clear()
        except asyncio.CancelledError:
            if batch:
                self._flush_batch(batch)
            raise

    def _flush_batch(self, batch: list[UsageRecord]) -> None:
        """同步批量写入 SQLite。"""
        if not batch:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                """INSERT INTO usage_records
                   (function_name, prompt_tokens, completion_tokens, total_tokens,
                    model, timestamp, success, duration_ms, error_message, provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(r.function_name, r.prompt_tokens, r.completion_tokens, r.total_tokens,
                  r.model, r.timestamp, int(r.success), r.duration_ms, r.error_message,
                  r.provider)
                 for r in batch]
            )
            conn.commit()

    async def summary(self) -> dict:
        """按 function 聚合 + 时间窗口统计 + 按 model 分桶（R56 ①）。"""
        # R56 ③: 改读 SQLite 全量（旧读 self._records 会被截断到 _max//2，
        # 且启动后新记录若超上限则早期记录丢失，影响 by_function/窗口统计）
        records = await self._load_all_from_db()

        now = time.time()
        h1 = now - 3600
        d1 = now - 86400

        total = {"calls": 0, "errors": 0, "prompt_tokens": 0,
                 "completion_tokens": 0, "total_tokens": 0,
                 "total_duration_ms": 0.0}
        hourly = {"calls": 0, "tokens": 0}
        daily = {"calls": 0, "tokens": 0}
        by_func: dict[str, dict] = {}
        # R56 ①: 按 model 分桶
        by_model: dict[str, dict] = {}

        for r in records:
            total["calls"] += 1
            total["prompt_tokens"] += r.prompt_tokens
            total["completion_tokens"] += r.completion_tokens
            total["total_tokens"] += r.total_tokens
            total["total_duration_ms"] += r.duration_ms
            if not r.success:
                total["errors"] += 1

            if r.timestamp >= h1:
                hourly["calls"] += 1
                hourly["tokens"] += r.total_tokens
            if r.timestamp >= d1:
                daily["calls"] += 1
                daily["tokens"] += r.total_tokens

            fn = r.function_name or "unknown"
            if fn not in by_func:
                by_func[fn] = {"calls": 0, "errors": 0, "prompt_tokens": 0,
                               "completion_tokens": 0, "total_tokens": 0,
                               "total_duration_ms": 0.0}
            f = by_func[fn]
            f["calls"] += 1
            f["prompt_tokens"] += r.prompt_tokens
            f["completion_tokens"] += r.completion_tokens
            f["total_tokens"] += r.total_tokens
            f["total_duration_ms"] += r.duration_ms
            if not r.success:
                f["errors"] += 1

            m = r.model or "unknown"
            if m not in by_model:
                by_model[m] = {"calls": 0, "errors": 0, "prompt_tokens": 0,
                               "completion_tokens": 0, "total_tokens": 0,
                               "total_duration_ms": 0.0}
            bm = by_model[m]
            bm["calls"] += 1
            bm["prompt_tokens"] += r.prompt_tokens
            bm["completion_tokens"] += r.completion_tokens
            bm["total_tokens"] += r.total_tokens
            bm["total_duration_ms"] += r.duration_ms
            if not r.success:
                bm["errors"] += 1

        def _finalize(d: dict) -> dict:
            if d["calls"] > 0:
                d["avg_duration_ms"] = round(
                    d.pop("total_duration_ms") / d["calls"], 1
                )
            else:
                d.pop("total_duration_ms", None)
                d["avg_duration_ms"] = 0
            return d

        total = _finalize(total)
        total["error_rate"] = (
            round(total["errors"] / total["calls"] * 100, 1)
            if total["calls"] > 0 else 0
        )
        by_func = {k: _finalize(v) for k, v in sorted(by_func.items())}
        by_model = {k: _finalize(v) for k, v in sorted(by_model.items())}

        return {
            "total": total,
            "hourly": hourly,
            "daily": daily,
            "by_function": by_func,
            # R56 ①: 前端据此按 model 计算费用（R57）
            "by_model": by_model,
        }

    async def timeseries(self, days: int = 30, granularity: str = "day", hours: int = 24) -> dict:
        """按小时/天/月聚合的时间序列数据，适合前端图表展示。

        granularity: "hour" → 格式 "YYYY-MM-DD HH:00"
                     "day"  → 格式 "YYYY-MM-DD"
                     "month" → 格式 "YYYY-MM"

        R56 ②: 返回 dict {series, total}——series 每个 bucket 含 by_model；
        total 为窗口内聚合（含 by_model），供前端窗口费用计算。
        """
        now = datetime.now()
        bucket: dict[str, dict] = {}

        if granularity == "hour":
            for i in range(hours - 1, -1, -1):
                d = now - timedelta(hours=i)
                key = d.strftime("%Y-%m-%d %H:00")
                bucket[key] = {"calls": 0, "errors": 0,
                               "prompt_tokens": 0, "completion_tokens": 0,
                               "total_tokens": 0, "by_model": {}}
            cutoff = now - timedelta(hours=hours)
            key_fmt = "%Y-%m-%d %H:00"
        elif granularity == "month":
            months = days
            for i in range(months - 1, -1, -1):
                m = now.month - i
                y = now.year
                while m < 1:
                    m += 12
                    y -= 1
                key = f"{y}-{m:02d}"
                bucket[key] = {"calls": 0, "errors": 0,
                               "prompt_tokens": 0, "completion_tokens": 0,
                               "total_tokens": 0, "by_model": {}}
            cutoff = now - timedelta(days=365)
            key_fmt = "%Y-%m"
        else:
            for i in range(days - 1, -1, -1):
                d = now - timedelta(days=i)
                key = d.strftime("%Y-%m-%d")
                bucket[key] = {"calls": 0, "errors": 0,
                               "prompt_tokens": 0, "completion_tokens": 0,
                               "total_tokens": 0, "by_model": {}}
            cutoff = now - timedelta(days=days)
            key_fmt = "%Y-%m-%d"

        ts_cutoff = cutoff.timestamp()
        # R56 ③: 窗口过滤下推 SQL（只取 cutoff 后记录），全量读 DB
        records = await self._load_all_from_db(cutoff_ts=ts_cutoff)

        total: dict = {"calls": 0, "errors": 0, "prompt_tokens": 0,
                       "completion_tokens": 0, "total_tokens": 0,
                       "by_model": {}}
        for r in records:
            if r.timestamp < ts_cutoff:
                continue
            key = datetime.fromtimestamp(r.timestamp).strftime(key_fmt)
            if key not in bucket:
                continue
            b = bucket[key]
            b["calls"] += 1
            b["prompt_tokens"] += r.prompt_tokens
            b["completion_tokens"] += r.completion_tokens
            b["total_tokens"] += r.total_tokens
            if not r.success:
                b["errors"] += 1
            # R56 ②: bucket 内按 model 拆分
            m = r.model or "unknown"
            bm = b["by_model"].setdefault(
                m, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            bm["calls"] += 1
            bm["prompt_tokens"] += r.prompt_tokens
            bm["completion_tokens"] += r.completion_tokens
            bm["total_tokens"] += r.total_tokens

            # 窗口 total（含 by_model）
            total["calls"] += 1
            total["prompt_tokens"] += r.prompt_tokens
            total["completion_tokens"] += r.completion_tokens
            total["total_tokens"] += r.total_tokens
            if not r.success:
                total["errors"] += 1
            tbm = total["by_model"].setdefault(
                m, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            tbm["calls"] += 1
            tbm["prompt_tokens"] += r.prompt_tokens
            tbm["completion_tokens"] += r.completion_tokens
            tbm["total_tokens"] += r.total_tokens

        series = []
        for date_str, data in bucket.items():
            series.append({
                "date": date_str,
                "calls": data["calls"],
                "errors": data["errors"],
                "prompt_tokens": data["prompt_tokens"],
                "completion_tokens": data["completion_tokens"],
                "total_tokens": data["total_tokens"],
                "by_model": data["by_model"],
            })

        return {"series": series, "total": total}

    async def recent_failures(self, limit: int = 50) -> list[dict]:
        """返回最近失败的调用记录（含错误信息）。"""
        async with self._lock:
            records = list(self._records)

        failures = []
        for r in reversed(records):
            if r.success:
                continue
            failures.append({
                "function_name": r.function_name,
                "timestamp": datetime.fromtimestamp(r.timestamp).isoformat(),
                "duration_ms": r.duration_ms,
                "error_message": r.error_message,
            })
            if len(failures) >= limit:
                break
        return failures

    async def shutdown(self) -> None:
        """关闭时刷盘剩余队列并取消后台任务。"""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass


token_store = TokenUsageStore()