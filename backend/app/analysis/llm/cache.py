"""Report result cache — split from analysis/llm.py (Batch 2)."""

import hashlib
import threading
import time
from typing import Any, AsyncGenerator

_REPORT_CACHE_LOCK = threading.Lock()

_REPORT_CACHE: dict[str, dict] = {}

_REPORT_CACHE_TTL = 8 * 3600

def _report_cache_key(query: str | None, data_as_of: str | None, prompt: str) -> str:
    """缓存键 = (query, data_as_of) + prompt 指纹。

    prompt 指纹捕获市场数据快照内容，保证「同 query + 同市场数据」才命中
    （交易日同源复用），避免不同市场上下文被同一 query 串味。
    """
    ph = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:24]
    return f"{query or 'q'}|{data_as_of or 'live'}|{ph}"


def get_cached_report(query: str | None, data_as_of: str | None, prompt: str) -> dict | None:
    """命中且未过期返回缓存条目（含 text/usage/ts），否则 None。"""
    key = _report_cache_key(query, data_as_of, prompt)
    with _REPORT_CACHE_LOCK:
        entry = _REPORT_CACHE.get(key)
        if entry and (time.monotonic() - entry["ts"]) < _REPORT_CACHE_TTL:
            return entry
    return None


def put_cached_report(
    query: str | None, data_as_of: str | None, prompt: str, text: str, usage: dict
) -> None:
    """写入缓存条目（线程安全）。"""
    key = _report_cache_key(query, data_as_of, prompt)
    with _REPORT_CACHE_LOCK:
        _REPORT_CACHE[key] = {"text": text, "usage": usage, "ts": time.monotonic()}
