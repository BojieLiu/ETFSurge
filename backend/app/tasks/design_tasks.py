"""
design_tasks.py — 向后兼容层

所有核心逻辑已移至 task_manager.py 和 worker_registry.py。
此文件保留仅用于向后兼容导入路径。
"""
from __future__ import annotations

import logging
from typing import Any

# Re-export from task_manager.py for backward compatibility
from .task_manager import (
    TaskManager,
    TaskNotifyManager,
    task_manager,
    notify_manager,
    _notify,
    design_worker,
)

from .worker_registry import register_worker

# Register design worker
register_worker("design", design_worker)

logger = logging.getLogger(__name__)
