# -*- coding: utf-8 -*-
"""提取 round8 文档的 O 项清单与验收描述（供验证用）"""
import re
import sys

txt = open("docs/archived/round8-rediagnosis.md", encoding="utf-8").read()
lines = txt.split("\n")
out = []
for i, ln in enumerate(lines):
    m = re.match(r"^#{2,3}\s+(.+)$", ln)
    if m and re.search(r"(O\d+|验收|问题清单|遗留|未修复)", m.group(1)):
        out.append(f"{i+1}: {m.group(1)[:110]}")
print("\n".join(out))
