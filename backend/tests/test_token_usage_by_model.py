"""
F16 R56 (combination-design-review.md F16): token_usage 后端按 model 拆分。

- R56 ①: summary() 聚合循环增加 by_model（按 r.model 分桶 prompt/completion）。
- R56 ②: timeseries() bucket 加 by_model + 返回窗口内 total（含 by_model）。
- R56 ③: 数据源改读 SQLite——消除 self._records 截断（_max//2）对窗口统计的影响。

无网络；使用 tmp_path 隔离 SQLite。
"""

import asyncio
import time

import pytest

from app.monitor.token_usage import TokenUsageStore, UsageRecord


def _make_store(tmp_path) -> TokenUsageStore:
    store = TokenUsageStore.__new__(TokenUsageStore)
    store._records = []
    store._lock = asyncio.Lock()
    store._max = 10000
    store._db_path = tmp_path / "token_usage.db"
    store._flush_queue = asyncio.Queue()
    store._flush_task = None
    store._init_db()
    return store


def _rec(function_name="design_report", prompt=100, completion=50, model="deepseek-v4-flash",
         ts=None, success=True, duration=500.0):
    return UsageRecord(
        function_name=function_name,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        model=model,
        timestamp=ts if ts is not None else time.time(),
        success=success,
        duration_ms=duration,
    )


class TestR56SummaryByModel:
    async def test_summary_by_model_buckets(self, tmp_path):
        """R56 ①: summary() 按 model 分桶 prompt/completion/calls。"""
        store = _make_store(tmp_path)
        now = time.time()
        await store.record(_rec(model="deepseek-v4-flash", prompt=100, completion=50, ts=now - 100))
        await store.record(_rec(model="deepseek-v4-flash", prompt=200, completion=100, ts=now - 200))
        await store.record(_rec(model="deepseek-chat", prompt=300, completion=150, ts=now - 300))
        # 强制落盘（record 是异步队列；查询前 drain）
        await asyncio.sleep(0)  # 让 record 入队

        summary = await store.summary()
        by_model = summary["by_model"]
        assert set(by_model.keys()) == {"deepseek-v4-flash", "deepseek-chat"}
        flash = by_model["deepseek-v4-flash"]
        assert flash["calls"] == 2
        assert flash["prompt_tokens"] == 300
        assert flash["completion_tokens"] == 150
        assert flash["total_tokens"] == 450
        chat = by_model["deepseek-chat"]
        assert chat["calls"] == 1
        assert chat["prompt_tokens"] == 300

    async def test_summary_total_consistent(self, tmp_path):
        """R56 ① 联动: total 与 by_model 之和一致。"""
        store = _make_store(tmp_path)
        now = time.time()
        await store.record(_rec(model="a", prompt=100, completion=50, ts=now - 100))
        await store.record(_rec(model="b", prompt=300, completion=150, ts=now - 200))
        summary = await store.summary()
        total = summary["total"]
        bm_sum = {k: 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens", "calls")}
        for m, d in summary["by_model"].items():
            for k in bm_sum:
                bm_sum[k] += d[k]
        assert bm_sum["prompt_tokens"] == total["prompt_tokens"]
        assert bm_sum["completion_tokens"] == total["completion_tokens"]
        assert bm_sum["calls"] == total["calls"]


class TestR56TimeseriesByModel:
    async def test_timeseries_bucket_by_model_and_total(self, tmp_path):
        """R56 ②: bucket 含 by_model + 返回窗口 total（含 by_model）。"""
        store = _make_store(tmp_path)
        now = time.time()
        # 今天 2 条（不同模型），昨天 1 条
        today_key = __import__("datetime").datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        await store.record(_rec(model="deepseek-v4-flash", prompt=100, completion=50, ts=now - 3600))
        await store.record(_rec(model="deepseek-chat", prompt=200, completion=100, ts=now - 7200))
        await store.record(_rec(model="deepseek-v4-flash", prompt=50, completion=25,
                                ts=now - 90000))  # 昨天

        result = await store.timeseries(days=3, granularity="day")
        assert "series" in result, "R56 ②: timeseries 返回 dict（含 series + total）"
        assert "total" in result
        series = result["series"]
        today = [s for s in series if s["date"] == today_key]
        assert today, "今天 bucket 必须存在"
        b = today[0]
        assert b["by_model"]["deepseek-v4-flash"]["prompt_tokens"] == 100
        assert b["by_model"]["deepseek-chat"]["prompt_tokens"] == 200
        # total = 窗口内全部（含昨天）
        assert result["total"]["calls"] == 3
        assert result["total"]["prompt_tokens"] == 350
        assert result["total"]["by_model"]["deepseek-v4-flash"]["prompt_tokens"] == 150
        assert result["total"]["by_model"]["deepseek-chat"]["prompt_tokens"] == 200

    async def test_timeseries_hour_granularity_by_model(self, tmp_path):
        """R56 ②: hour 粒度同样带 by_model。"""
        store = _make_store(tmp_path)
        now = time.time()
        await store.record(_rec(model="deepseek-v4-flash", prompt=10, completion=5, ts=now - 600))
        result = await store.timeseries(granularity="hour", hours=6)
        series = result["series"]
        total_tokens = sum(s["total_tokens"] for s in series)
        assert total_tokens == 15
        assert result["total"]["calls"] == 1


class TestR56ReadFromSqlite:
    async def test_summary_includes_records_not_in_memory(self, tmp_path):
        """R56 ③: summary 读 SQLite 全量——内存截断/未加载的记录也计入。

        旧实现读 self._records（会被截断到 _max//2 且只在启动时加载）——
        重启后新记录若在内存未加载，窗口统计丢失。本用例直接往 SQLite
        插入记录（不经过内存），断言 summary 能统计到。
        """
        store = _make_store(tmp_path)
        # 直接写 SQLite（模拟"内存中没有但 DB 有"的记录）
        store._flush_batch([_rec(model="deepseek-v4-flash", prompt=1000, completion=500)])

        summary = await store.summary()
        assert summary["total"]["calls"] == 1
        assert summary["total"]["prompt_tokens"] == 1000
        assert summary["by_model"]["deepseek-v4-flash"]["completion_tokens"] == 500

    async def test_pending_queue_drained_before_query(self, tmp_path):
        """R56 ③: 查询前强制落盘——队列中未 flush 的记录不丢。"""
        store = _make_store(tmp_path)
        await store.record(_rec(model="deepseek-chat", prompt=111, completion=22))
        await store.record(_rec(model="deepseek-chat", prompt=333, completion=44))
        # 不 sleep——直接查询（record 只入队，尚未刷盘）
        summary = await store.summary()
        assert summary["total"]["calls"] == 2
        assert summary["total"]["prompt_tokens"] == 444
        assert summary["by_model"]["deepseek-chat"]["completion_tokens"] == 66
