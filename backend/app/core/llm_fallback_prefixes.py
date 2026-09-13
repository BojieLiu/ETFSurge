"""LLM fallback summary prefixes — single source of truth (round55 R186 方案B).

背景：reports._classify_llm_failure_cause（写入口径）与
services/portfolio/strategy_check.py F1-9 兜底识别（消费口径）各手写一份
前缀字符串——分类器新增 envelope 分支（round51 R164）时识别器未同步，
check108 出现「summary 写兜底而 is_fallback=False/quality=full」矛盾
（R163→R177→R186 三现同型）。两边同引本模块 + 一致性单测锁死。

约束：本模块零依赖（不得 import analysis/services，避免循环 import）。
"""

from __future__ import annotations

TIMEOUT_PREFIX = "LLM 分析超时"
QUOTA_PREFIX = "LLM 分析配额耗尽"
PARSE_FAIL_PREFIX = "LLM 分析结果解析失败"
ENVELOPE_PREFIX = "LLM 网关返回错误信封"

FALLBACK_PREFIXES: tuple[str, ...] = (
    TIMEOUT_PREFIX,
    QUOTA_PREFIX,
    PARSE_FAIL_PREFIX,
    ENVELOPE_PREFIX,
)


def is_llm_fallback_summary(summary: str | None) -> bool:
    """F1-9 兜底识别：summary 以任一兜底前缀开头即视为 LLM 失败。"""
    if not summary:
        return False
    return str(summary).startswith(FALLBACK_PREFIXES)
