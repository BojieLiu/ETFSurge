"""集中日志配置（标准库 logging）。

使用方式：
    from ..core.logging import get_logger
    logger = get_logger(__name__)

配置项（见 app.config.Settings）：
    log_level: 日志级别，默认 "INFO"
    log_file:  可选，日志文件路径。设置后追加 RotatingFileHandler
               （单文件 10MB 轮转，保留 5 份）；为空则只输出到 stdout。

在应用启动时（app.main.lifespan）调用一次 setup_logging() 即可，幂等。
"""
from __future__ import annotations

import logging
import sys

from ..config import settings

_CONFIGURED = False

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """配置根 logger。幂等，可安全多次调用。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    raw_level = (settings.log_level or "INFO").strip().upper()
    level = logging.getLevelName(raw_level)
    if not isinstance(level, int):
        level = logging.INFO

    formatter = logging.Formatter(_DEFAULT_FORMAT, _DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # 清空可能存在的默认/第三方 handler，避免重复输出
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_file = (settings.log_file or "").strip()
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except (OSError, PermissionError) as exc:
            root.warning("无法创建日志文件 %s: %s", log_file, exc)

    # APScheduler 每 15s 打印 "executed successfully"，噪声大且掩盖真实错误，
    # 仅保留 WARNING 及以上（调度失败仍会经 logger.exception 输出）。
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # S04: numba 内部 SSA DEBUG 日志在日志中泛滥（每个调用数百行），
    # 降级到 WARNING 级别以抑制噪声。
    for numba_logger in ("numba", "numba.core.ssa", "numba.core"):
        logging.getLogger(numba_logger).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """返回命名 logger。"""
    return logging.getLogger(name)
