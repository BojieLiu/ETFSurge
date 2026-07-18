#!/usr/bin/env python3
"""在 etf_scanner.py 的 filter_etfs 中添加候选池为空的 ERROR 日志"""
import sys

with open(r"E:\ETF_Surge\backend\app\fetchers\etf_scanner.py", "r", encoding="utf-8") as f:
    content = f.read()

old_line = '    logger.info("[etf_scanner] filter_etfs: %d -> %d", len(raw_list), len(results))'
new_lines = old_line + """
    # P4-b: 候选池为空时输出 ERROR 日志
    if len(results) == 0 and len(raw_list) > 0:
        logger.error(
            "[etf_scanner] filter_etfs: ALL %d ETFs filtered out! "
            "Check column name matching (garbled keys). First raw keys: %s",
            len(raw_list), list(raw_list[0].keys()) if raw_list else "N/A"
        )"""

if old_line in content:
    content = content.replace(old_line, new_lines, 1)
    with open(r"E:\ETF_Surge\backend\app\fetchers\etf_scanner.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: applied filter_etfs ERROR log")
else:
    print("FAIL: cannot find target line")
    print("Looking for:", repr(old_line[:40]))
    sys.exit(1)
