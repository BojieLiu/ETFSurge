"""
check_api_usage.py — 扫描前端 API 方法的调用覆盖

检测 frontend/src/api/index.js 中定义了哪些 API 方法，
然后在 frontend/src/ 中搜索这些方法是否被实际调用。

用法:
  python backend/scripts/check_api_usage.py
  python backend/scripts/check_api_usage.py --exit-zero  # 软警告模式

在 pre-commit 中集成，防止定义后从未调用的死 API 方法。
"""
import ast
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
API_FILE = PROJECT_ROOT / "frontend" / "src" / "api" / "index.js"
FRONTEND_SRC = PROJECT_ROOT / "frontend" / "src"


def extract_api_methods(api_file: Path) -> dict[str, str]:
    """从 api/index.js 中提取所有导出的 API 方法名。"""
    content = api_file.read_text(encoding="utf-8")
    methods: dict[str, str] = {}
    # 匹配对象方法定义: 行首空白后的 methodName: (
    pattern = re.compile(r'^\s{2,}(\w+)\s*:\s*(?:\(|function)', re.MULTILINE)
    for m in pattern.finditer(content):
        name = m.group(1)
        # 跳过保留字
        if name in ('get', 'post', 'put', 'delete', 'patch', 'defaults',
                     'interceptors', 'create', 'use', 'config', 'headers',
                     'baseURL', 'timeout', 'responseType', 'params',
                     'transformRequest', 'transformResponse'):
            continue
        if name not in methods:
            methods[name] = name
    return methods


def find_calls_in_source(methods: dict[str, str], src_dir: Path) -> dict[str, list[str]]:
    """在 frontend/src/ 中搜索各 API 方法的调用位置。"""
    calls: dict[str, list[str]] = {}
    for method_name in methods:
        calls[method_name] = []
        # 匹配: .methodName( 或 methodName( (排除 import 语句)
        pattern = re.compile(
            r'\.' + re.escape(method_name) + r'\s*\('
        )
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith(('.js', '.vue')):
                    continue
                fpath = Path(root) / fname
                if fpath.resolve() == API_FILE.resolve():
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for match in pattern.finditer(text):
                        rel_path = fpath.relative_to(src_dir.parent)
                        line_num = text[:match.start()].count('\n') + 1
                        calls[method_name].append(f"{rel_path}:{line_num}")
                except Exception:
                    continue
    return calls


def main():
    exit_zero = "--exit-zero" in sys.argv
    if not API_FILE.exists():
        print(f"[check_api_usage] API file not found: {API_FILE}")
        sys.exit(0 if exit_zero else 1)

    methods = extract_api_methods(API_FILE)
    if not methods:
        print(f"[check_api_usage] no methods extracted from {API_FILE}")
        sys.exit(0 if exit_zero else 1)

    calls = find_calls_in_source(methods, FRONTEND_SRC)
    unused = sorted(name for name, sites in calls.items() if not sites)
    used = sorted(name for name, sites in calls.items() if sites)

    print(f"\n  API methods total: {len(methods)}")
    print(f"  Called:           {len(used)}")
    print(f"  Unused:           {len(unused)}")

    if unused:
        print("\n  WARNING: the following API methods are defined but never called:\n")
        for name in unused:
            print(f"    - {name}")
        print()

    if not unused:
        print("  All API methods have call sites.\n")

    if unused and not exit_zero:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
