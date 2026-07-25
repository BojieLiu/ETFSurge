#!/usr/bin/env python3
"""Fix news_fetcher._ak() to use per-call executor."""
import re

text = open("backend/app/fetchers/news_fetcher.py", "r", encoding="utf-8").read()

# 1. Remove _akshare_executor global, update get_akshare_pool_stats to return empty
old_exec = re.compile(
    r"_akshare_executor = concurrent\.futures\.ThreadPoolExecutor\(max_workers=4\)\n\n\ndef get_akshare_pool_stats",
    re.DOTALL
)

new_exec_text = """def get_akshare_pool_stats() -> dict:
    \"\"\"akshare has no shared pool (per-call executor).\"\"\"
    return {\"max_workers\": 0, \"alive_threads\": 0, \"pending_tasks\": 0, \"note\": \"per-call executor\"}"""

# Replace just the executor definition and function header
text = text.replace(
    "_akshare_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)\n\n\ndef get_akshare_pool_stats()",
    "def get_akshare_pool_stats()"
)

# Remove the old function body and replace with new
old_body_start = text.find("def get_akshare_pool_stats")
old_body_end = text.find("\ndef _ak", old_body_start)
text = text[:old_body_start] + new_exec_text + text[old_body_end:]

# 2. Replace _ak function
old_ak = """def _ak(fn, timeout: int = _AK_TIMEOUT) -> list[dict[str, Any]]:
    \"\"\"\u8c03\u7528\u4e00\u4e2a akshare \u65b0\u95fb\u51fd\u6570, \u5e26\u8d85\u65f6\u4fdd\u62a4, \u5931\u8d25\u8fd4\u56de\u7a7a\u3002

    \u4f7f\u7528\u4e13\u7528\u7ebf\u7a0b\u6c60 _akshare_executor \u9694\u79bb akshare \u7684\u6162\u8bf7\u6c42\uff0c
    \u907f\u514d\u50f5\u5c38\u7ebf\u7a0b\u8017\u5c3d\u4e3b\u5171\u4eab\u7ebf\u7a0b\u6c60 _shared_executor\u3002
    \"\"\"
    def _p():
        with no_proxy():
            import akshare as ak
            df = fn(ak)
        _decode_df(df)
        return df.to_dict(orient=\"records\")
    future = _akshare_executor.submit(_p)
    try:
        return future.result(timeout=timeout) or []
    except concurrent.futures.TimeoutError:
        return []
    except Exception:
        return []"""

new_ak = """def _ak(fn, timeout: int = _AK_TIMEOUT) -> list[dict[str, Any]]:
    \"\"\"Call an akshare news function with timeout, return [] on failure.

    Per-call executor (P0 fix): threads don't leak on timeout.
    \"\"\"
    def _p():
        with no_proxy():
            import akshare as ak
            df = fn(ak)
        _decode_df(df)
        return df.to_dict(orient=\"records\")
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(_p)
        return future.result(timeout=timeout) or []
    except concurrent.futures.TimeoutError:
        return []
    except Exception:
        return []
    finally:
        ex.shutdown(wait=False)"""

if old_ak in text:
    text = text.replace(old_ak, new_ak)
    open("backend/app/fetchers/news_fetcher.py", "w", encoding="utf-8").write(text)
    print("_ak updated OK")
else:
    print("old _ak not found, len=", len(text))
    # Debug: show function content
    idx = text.find("def _ak(")
    if idx >= 0:
        print("Found at", idx)
        print(text[idx:idx+600])
