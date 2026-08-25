"""round36 §8-B: 事件循环滞后看门狗——把「静默挂死」变成带现场证据的告警。

背景（docs/round36-B5-allocate-pipeline.md §8.2 R3 / known-env-issues §1.1
2026-08-25 更新）：设计管线等同步重段冻结事件循环时，连 120s 周期探针日志
都停摆，诊断只能靠 netstat/进程取证。本模块以 1s 打点检测 loop lag，
超阈值即 WARNING + 全任务栈转储落盘 ``logs/loop_lag_*.log``。

纯 asyncio + logging，无业务依赖；lifespan 经 ``background_tasks.spawn``
孵化（shutdown_all 统一取消），见 app/main.py。
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class LoopLagWatchdog:
    """循环滞后监控：每 *interval* 秒调度一次自检，实际唤醒晚于计划
    *threshold* 秒即判定 lag（单线程循环被同步代码占用的直接证据）。"""

    def __init__(
        self,
        interval: float = 1.0,
        threshold: float = 5.0,
        dump_dir: str | Path = "logs",
        max_dumps: int = 20,
    ) -> None:
        self.interval = interval
        self.threshold = threshold
        self.dump_dir = Path(dump_dir)
        self.max_dumps = max_dumps  # 转储文件数封顶（防冻结频发刷盘）
        self._dump_count = 0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        logger.info(
            "[loop_watchdog] started (interval=%.2fs, threshold=%.1fs, dump_dir=%s)",
            self.interval, self.threshold, self.dump_dir,
        )
        while True:
            scheduled = loop.time() + self.interval
            await asyncio.sleep(self.interval)
            lag = loop.time() - scheduled
            if lag >= self.threshold:
                self._emit(lag, loop)

    def _emit(self, lag: float, loop: asyncio.AbstractEventLoop) -> None:
        if self._dump_count >= self.max_dumps:
            logger.warning(
                "[loop_watchdog] lag %.2fs (≥%.1fs) — dump cap %d reached, skip file",
                lag, self.threshold, self.max_dumps,
            )
            return
        current = asyncio.current_task()
        sections: list[str] = [
            f"loop lag {lag:.3f}s (threshold {self.threshold:.1f}s) "
            f"at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        ]
        for task in asyncio.all_tasks(loop):
            if task is current:
                continue
            stack = task.get_stack(limit=24)
            if not stack:
                continue
            # 最内层帧 format_stack 会沿 f_back 链给出完整调用链
            frames = "".join(traceback.format_stack(stack[-1]))
            sections.append(f"\n── task {task.get_name()} ──\n{frames}")
        try:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.dump_dir / f"loop_lag_{ts}_{int(lag*1000)}ms.log"
            path.write_text("\n".join(sections), encoding="utf-8")
            self._dump_count += 1
            target: str = str(path)
        except Exception as e:  # 转储失败不阻断告警
            target = f"<dump failed: {e}>"
        logger.warning(
            "[loop_watchdog] event loop lag %.2fs ≥ %.1fs — %d live tasks, stacks -> %s",
            lag, self.threshold, len(sections) - 1, target,
        )


def start_loop_watchdog(
    interval: float = 1.0,
    threshold: float = 5.0,
    dump_dir: str | Path = "logs",
) -> asyncio.Task:
    """lifespan 入口：经 background_tasks.spawn 孵化（强引用 + 统一关停）。"""
    from .background_tasks import spawn

    return spawn(
        LoopLagWatchdog(interval=interval, threshold=threshold, dump_dir=dump_dir).run(),
        name="loop-watchdog",
    )
