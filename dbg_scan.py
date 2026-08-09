"""Debug scan() internals for get_us_unsupported."""
import ast
import sys
import pathlib

sys.path.insert(0, "backend")
from scripts import audit_unused_symbols as A

# Build modules like scan() does
modules = {}
for path in A._iter_py_files():
    mod = A._module_of(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except SyntaxError:
        continue
    modules[mod] = A._collect_defs(tree, path)

mod = "app.fetchers.hk_hot_fetcher"
print("mod in modules:", mod in modules)
print("defs:", list(modules[mod].keys()))

# Reference counting for just this symbol across reference files
count = 0
for path in A._iter_reference_files():
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except SyntaxError:
        continue
    names = A._referenced_names(tree)
    imports = A._collect_imports(tree)
    amap = A._alias_to_module_map(imports)
    name = "get_us_unsupported"
    if name in names:
        count += 1
    for alias, target in amap.items():
        if target == mod and name in names:
            count += 1
print("count after loop:", count)
