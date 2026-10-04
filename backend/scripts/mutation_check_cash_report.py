"""变异测试：改坏源文件看现金仓位用例是否报警。

被测用例并入 tests/test_design_report_format.py 的 round62 段（不新开文件，见该段
注释与 scripts/check_test_baseline.py 的 P3-6 纪律）。

round60 教训 #1/#6：断言数量 != 覆盖；坏掉的 harness 会伪装成覆盖率。
故本脚本校验 returncode + 必须打出摘要，否则报 BROKEN——被测文件被改名/删除时
同样会报 BROKEN（曾实测：目标文件迁移后本脚本拒绝输出存活/杀死统计）。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_FILE = "tests/test_design_report_format.py"
TARGETS = {
    "core_cash_helper": (
        ROOT / "app" / "core" / "cash_weight.py",
        "return max(0.0, round(1.0 - non_cash, 4))",
        "return 0.10",
    ),
    "core_unparseable_returns_none": (
        ROOT / "app" / "core" / "cash_weight.py",
        "        if w is None:\n            return None\n",
        "",
    ),
    "comparison_table_fabricates_10": (
        ROOT / "app" / "tasks" / "design_report.py",
        'cashes.append(f"{w * 100:.0f}%" if w is not None else "—")',
        'cashes.append(f"{w * 100:.0f}%" if w is not None else "10%")',
    ),
    "structure_line_drops_cash": (
        ROOT / "app" / "tasks" / "design_report.py",
        '+ (f" · 现金 {_cash * 100:.0f}%\\n" if _cash is not None else "\\n")',
        '+ "\\n"',
    ),
    "detail_table_skips_cash": (
        ROOT / "app" / "tasks" / "design_report.py",
        "        if _cash_row is not None:\n            _ordered.append(_cash_row)\n",
        "",
    ),
    "cash_row_gets_fund_advice": (
        ROOT / "app" / "tasks" / "design_report.py",
        '                advice = "维持目标比例"',
        '                advice = "等企稳分批，跌破 MA20 暂停"',
    ),
    "cash_row_gets_data_unavailable": (
        ROOT / "app" / "tasks" / "design_report.py",
        '                dcp_txt = "—"',
        '                dcp_txt = "数据源不可用"',
    ),
    "footnote_removed": (
        ROOT / "app" / "tasks" / "design_report.py",
        '    if any((_cash_weight_of(s) or 0) > 0 for s in strategies):',
        "    if False:",
    ),
    "engine_fallback_drops_cash_line": (
        ROOT / "app" / "analysis" / "llm" / "reports.py",
        '        cash_txt = f" · 现金 {cash_w * 100:.0f}%" if cash_w is not None else ""',
        '        cash_txt = ""',
    ),
    "engine_fallback_equity_line_drops_cash": (
        ROOT / "app" / "analysis" / "llm" / "reports.py",
        'f"，现金 {_eq_cash * 100:.0f}%" if _eq_cash else "，无现金仓位"',
        '""',
    ),
    "engine_fallback_equity_line_drops_plan": (
        ROOT / "app" / "analysis" / "llm" / "reports.py",
        '_who = f"（{_eq_s.get(\'label\', \'\')}）" if len(strategies) > 1 else ""',
        '_who = ""',
    ),
    "engine_summary_drops_cash": (
        ROOT / "app" / "tasks" / "design_report.py",
        'cash_txt = f" · 现金 {cash_w * 100:.0f}%" if cash_w is not None else ""',
        'cash_txt = ""',
    ),
    "rounding_note_removed": (
        ROOT / "app" / "tasks" / "design_report.py",
        "    if any(_display_weight_drift(s) for s in strategies):",
        "    if False:",
    ),
    "drift_detector_always_false": (
        ROOT / "app" / "tasks" / "design_report.py",
        "    return abs(shown - 100) >= 1",
        "    return False",
    ),
}


def run_tests():
    p = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    base_rc, base_out = run_tests()
    if base_rc != 0 or " passed" not in base_out:
        print(f"BROKEN: baseline not green ({TEST_FILE}), mutation results meaningless")
        print(base_out[-1500:])
        return 2
    print(f"baseline: green ({TEST_FILE})\n")

    killed, survived, broken = [], [], []
    for name, (path, old, new) in TARGETS.items():
        text = path.read_text(encoding="utf-8")
        if old not in text:
            broken.append(f"{name}: NO-APPLY (pattern not found in {path.name})")
            continue
        backup = text
        try:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            rc, out = run_tests()
        finally:
            path.write_text(backup, encoding="utf-8")
        if rc == 0:
            survived.append(name)
            print(f"SURVIVED  {name}")
        elif " passed" not in out and "failed" not in out and "error" not in out:
            broken.append(f"{name}: harness produced no summary")
            print(f"BROKEN    {name}")
        else:
            killed.append(name)
            print(f"KILLED    {name}")

    rc, out = run_tests()
    if rc != 0:
        broken.append("post-mutation baseline not restored")
        print("\nBROKEN: source not restored cleanly")
        print(out[-1500:])

    print(f"\nkilled={len(killed)} survived={len(survived)} broken={len(broken)}")
    for b in broken:
        print("  BROKEN:", b)
    return 1 if survived or broken else 0


if __name__ == "__main__":
    sys.exit(main())
