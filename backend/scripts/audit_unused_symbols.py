"""P3-1: Function-level AST unused-symbol audit (round11-code-redundancy.md §8.2).

Scans backend/app/**/*.py with AST, collects top-level function/class/const
definitions, and computes cross-module + in-module references. Symbols with
zero references are reported. A frozen baseline (JSON) records the current
stock of unused symbols; `--check` fails only when NEW unused symbols appear
(stock must not grow), while the existing stock stays trackable.

Framework-registration exclusions (avoid false positives):
- functions decorated with @router./@app./@background/@task-like decorators
- names listed in module __all__ / re-exported by __init__.py
- private names (leading underscore, module-local by convention)
- SQLAlchemy model classes inheriting a declarative Base
- names referenced via string literals (e.g. "module.func", config keys)

Usage:
    python scripts/audit_unused_symbols.py --baseline   # (re)generate baseline
    python scripts/audit_unused_symbols.py              # --check mode (CI gate)
    python scripts/audit_unused_symbols.py --print      # dump current unused
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
BASELINE_FILE = pathlib.Path(__file__).resolve().parent / ".unused_symbols.baseline.json"

# Decorator prefixes that register a callable with a framework (keep).
_REGISTER_PREFIXES = ("router.", "app.", "background", "task", "lifespan")
# SQLAlchemy/declarative base names — model classes are registered via
# metadata even without direct references.
_BASE_NAMES = {"Base", "DeclarativeBase", "BaseModel"}

_IMPORT_CACHE: dict[str, dict[str, set[str]]] = {}  # module -> {name: ref_kinds}


def _iter_py_files() -> list[pathlib.Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _iter_reference_files() -> list[pathlib.Path]:
    """All backend python files (app + tests + scripts) — a symbol referenced
    by tests or scripts is a real call site, not dead code."""
    backend = APP_DIR.parent
    files = sorted(backend.rglob("*.py"))
    return [f for f in files if "__pycache__" not in str(f)]


def _module_of(path: pathlib.Path) -> str:
    rel = path.relative_to(APP_DIR.parent)  # backend/
    return ".".join(rel.with_suffix("").parts)


def _collect_defs(tree: ast.Module, path: pathlib.Path) -> dict[str, dict]:
    """Top-level function/class/const definitions -> {name: meta}."""
    defs: dict[str, dict] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            meta = {"kind": "func", "line": node.lineno, "registered": False,
                    "base": "", "doc": ast.get_docstring(node) or ""}
            for dec in node.decorator_list:
                dname = _decorator_name(dec)
                if any(dname.startswith(p) for p in _REGISTER_PREFIXES):
                    meta["registered"] = True
            defs[node.name] = meta
        elif isinstance(node, ast.ClassDef):
            meta = {"kind": "class", "line": node.lineno, "registered": False,
                    "base": "", "doc": ast.get_docstring(node) or ""}
            for base in node.bases:
                bname = _decorator_name(base)
                if bname in _BASE_NAMES:
                    meta["registered"] = True
                    meta["base"] = bname
            defs[node.name] = meta
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    defs[t.id] = {"kind": "const", "line": node.lineno,
                                  "registered": False, "base": "", "doc": ""}
    return defs


def _decorator_name(node: ast.AST) -> str:
    """'@router.get' -> 'router.get'; '@app.task' -> 'app.task'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _decorator_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _collect_all_exports(tree: ast.Module) -> set[str]:
    """Names in __all__ (explicit exports)."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return {e.value for e in node.value.elts
                                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _collect_imports(tree: ast.Module) -> list[tuple[str, str]]:
    """(alias, module_path) pairs for imported names."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((a.asname or a.name.split(".")[0], a.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                out.append((a.asname or a.name, f"{mod}.{a.name}" if mod else a.name))
    return out


def _referenced_names(tree: ast.Module) -> set[str]:
    """All Name loads + attribute access chains + string literals in module."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # capture root of attribute chain (obj.name -> obj)
            root = node
            while isinstance(root.value, ast.Attribute):
                root = root.value
            if isinstance(root.value, ast.Name):
                names.add(root.value.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # string refs like "app.services.x" or "module.func"
            names.add(node.value)
    return names


def _attr_accesses(tree: ast.Module) -> set[tuple[str, str]]:
    """(root_name, attr) pairs for direct attribute accesses (obj.attr)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            out.add((node.value.id, node.attr))
    return out


def _alias_to_module_map(imports: list[tuple[str, str]]) -> dict[str, str]:
    """Map local aliases to the module they point at (from app.x import y)."""
    m: dict[str, str] = {}
    for alias, target in imports:
        if target.startswith("app."):
            m[alias] = target
    return m


def scan() -> dict[str, dict]:
    """Return {module_path: {name: meta}} for symbols with zero references."""
    modules: dict[str, dict[str, dict]] = {}
    exports: dict[str, set[str]] = {}
    for path in _iter_py_files():
        mod = _module_of(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except SyntaxError:
            continue
        modules[mod] = _collect_defs(tree, path)
        exports[mod] = _collect_all_exports(tree)

    # Count references across all files (app + tests + scripts).
    ref_counts: dict[str, dict[str, int]] = {
        mod: {name: 0 for name in defs} for mod, defs in modules.items()
    }

    for path in _iter_reference_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except SyntaxError:
            continue
        names = _referenced_names(tree)
        imports = _collect_imports(tree)
        alias_map = _alias_to_module_map(imports)
        attr_accesses = _attr_accesses(tree)

        for mod, defs in modules.items():
            for name in defs:
                if name in names:
                    ref_counts[mod][name] += 1
                # `alias.attr` where alias imports the module:
                #   from app.x import mod as m -> m.func
                for alias, target in alias_map.items():
                    if target == mod and (alias, name) in attr_accesses:
                        ref_counts[mod][name] += 1
                # string ref "app.services.x.func" or "app.services.x"
                for s in names:
                    if isinstance(s, str) and (f"{mod}.{name}" == s
                                               or s.startswith(f"{mod}.")):
                        ref_counts[mod][name] += 1

        # `from app.x import name` — the imported name is a real reference
        # to app.x.name (alias names are ast.alias, not Name nodes).
        for alias, target in imports:
            if target.startswith("app."):
                mod_path, _, sym = target.rpartition(".")
                if mod_path in modules and sym in modules[mod_path]:
                    ref_counts[mod_path][sym] += 1

    unused: dict[str, dict] = {}
    for mod, defs in modules.items():
        for name, meta in defs.items():
            if name.startswith("_"):
                continue  # private, module-local convention
            if meta["registered"]:
                continue  # framework-registered (router/task/Base model)
            if name in exports.get(mod, set()):
                continue  # explicit __all__ export
            if ref_counts[mod][name] > 0:
                continue
            unused.setdefault(mod, {})[name] = {
                "kind": meta["kind"], "line": meta["line"],
                "doc": (meta["doc"] or "").splitlines()[0][:80] if meta["doc"] else "",
            }
    return unused


def main() -> int:
    mode = "--baseline" if "--baseline" in sys.argv else "--check"
    unused = scan()

    if "--print" in sys.argv:
        print(json.dumps(unused, indent=2, ensure_ascii=False))
        return 0

    if mode == "--baseline":
        BASELINE_FILE.write_text(
            json.dumps(unused, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        total = sum(len(v) for v in unused.values())
        print(f"[P3-1] baseline written: {total} unused symbols -> "
              f"{BASELINE_FILE.name}")
        return 0

    if not BASELINE_FILE.exists():
        print("[P3-1] no baseline; run --baseline first", file=sys.stderr)
        return 1

    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    new_unused: dict[str, dict] = {}
    for mod, syms in unused.items():
        for name in syms:
            if mod not in baseline or name not in baseline.get(mod, {}):
                new_unused.setdefault(mod, {})[name] = syms[name]

    total = sum(len(v) for v in unused.values())
    if new_unused:
        print(f"[P3-1] FAIL: {sum(len(v) for v in new_unused.values())} NEW "
              f"unused symbol(s) (stock was {total})")
        for mod, syms in sorted(new_unused.items()):
            for name, meta in sorted(syms.items()):
                print(f"  {mod}:{name} ({meta['kind']}, line {meta['line']})")
        print("  Delete them or add a real call site; dead code must not grow.")
        return 1
    print(f"[P3-1] OK: unused stock {total} (no growth vs baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
