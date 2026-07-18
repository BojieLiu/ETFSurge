#!/usr/bin/env python3
import subprocess, sys

msg = (
    "fix: SCALE_NAMES 列名同步当前 akshare fund_etf_spot_em() 实际列名\n"
    "\n"
    "当前 akshare(2026) 的 fund_etf_spot_em() 返回 37 列，不包含 '基金规模'\n"
    "但包含 '流通市值'(列33)。原 SCALE_NAMES 全部失效导致 1549→0 全过滤。\n"
    "修复后 filter_etfs 能正确读取流通市值作为规模代理。\n"
    "\n"
    "TDD: 5 新用例(列名兼容/小盘剔除/纯债剔除/DataFrame 输入/输出结构)\n"
    "E2E: 27/27 全部通过; 回归: 7/7 优化测试全过"
)

subprocess.run(["git", "commit", "-m", msg], cwd=r"E:\ETF_Surge")
subprocess.run(["git", "push"], cwd=r"E:\ETF_Surge")
