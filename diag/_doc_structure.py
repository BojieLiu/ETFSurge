# -*- coding: utf-8 -*-
"""打印 round9 文档章节结构"""
import re

txt = open("docs/round9-container-rediagnosis.md", encoding="utf-8").read()
for i, ln in enumerate(txt.split("\n")):
    m = re.match(r"^(#{1,4}) (.*)$", ln)
    if m:
        print(f"{i+1}: {'  '*(len(m.group(1))-1)}{m.group(2)[:90]}")
