"""定时同步脚本（独立进程运行，不阻塞后端）。

调度：
  - 每日 16:30  (收盘后) 同步 instruments（A股/ETF/港股）
  - 每周一 09:00         同步 sectors（行业/概念板块）

启动：
  python -m scripts.run_scheduler
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def _run(coro_fn):
    """在线程中跑 asyncio.run，避免调度器事件循环冲突。"""
    asyncio.run(coro_fn())


def main():
    from scripts.sync_instruments import sync as sync_instruments
    from scripts.sync_sectors import sync as sync_sectors

    sched = BlockingScheduler(timezone="Asia/Shanghai")

    # 每日收盘后同步标的
    sched.add_job(
        lambda: _run(sync_instruments),
        CronTrigger(hour=16, minute=30),
        id="sync_instruments",
        name="每日同步标的",
        replace_existing=True,
    )
    # 每周一同步板块
    sched.add_job(
        lambda: _run(sync_sectors),
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="sync_sectors",
        name="每周同步板块",
        replace_existing=True,
    )

    print("[scheduler] started. Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[scheduler] stopped.")


if __name__ == "__main__":
    main()
