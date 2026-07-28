#!/usr/bin/env python3
"""Fix duplicate report_text lines in strategy_check.py model."""
import os

path = os.path.join(os.path.dirname(__file__), "backend", "app", "models", "strategy_check.py")

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Remove duplicate column definition
dup_col = '    report_text = Column(Text, nullable=True)\n\n    # Q02'
if dup_col in content:
    content = content.replace(dup_col, '    # Q02', 1)

# Remove duplicate to_dict line
dup_dict = '"report_text": self.report_text or "",\n            "report_text": self.report_text or "",'
if dup_dict in content:
    content = content.replace(dup_dict, '"report_text": self.report_text or "",', 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed duplicates in strategy_check.py")
