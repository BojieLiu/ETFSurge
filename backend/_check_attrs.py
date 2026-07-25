#!/usr/bin/env python3
"""Check which cache attributes the pool_manager uses."""
import ast

with open("backend/app/services/pool_manager.py", encoding="utf-8") as f:
    tree = ast.parse(f.read())

for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                if "cache" in target.attr.lower() or "ts" in target.attr.lower():
                    print(target.attr)
