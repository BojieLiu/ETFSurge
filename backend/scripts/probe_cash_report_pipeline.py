"""现实验证（链路层）：检查**真实链路生成**的 design_text 是否已含现金仓位。

数据源：data/portfolio.db 里最新几条 design 的 design_text（由 verify_e2e 刚跑出的
design-async 任务写入，非本脚本生成）。
"""
import pathlib
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "portfolio.db"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3

con = sqlite3.connect(DB)
rows = list(con.execute(
    "select id, created_at, status, report_quality, design_text from portfolio_designs "
    "where design_text is not null and design_text != '' order by id desc limit ?", (N,)
))

if not rows:
    print("BROKEN: 无 design_text 可查")
    sys.exit(2)

all_ok = True
for did, created, status, quality, txt in rows:
    lines = txt.splitlines()
    struct = [ln for ln in lines if ln.startswith("资产结构")]
    struct_ok = all("现金" in ln for ln in struct) if struct else False
    cash_rows = [ln for ln in lines
                 if ln.strip().startswith("|") and " | CASH | " in ln]
    cash_row_ok = len(cash_rows) >= 1 and all(
        "维持目标比例" in ln and "| — |" in ln for ln in cash_rows)
    cmp_row = next((ln for ln in lines if ln.strip().startswith("| 现金仓位")), None)
    notes = [ln for ln in lines if ln.strip().startswith("> 注：现金")]
    drift = [ln for ln in lines if "四舍五入" in ln]

    print("=" * 74)
    print(f"design id={did}  {created}  status={status}  quality={quality}")
    print(f"  对比表现金仓位行 : {cmp_row}")
    print(f"  资产结构行({len(struct)}) 全部含现金 : {struct_ok}")
    for ln in struct:
        print(f"      {ln}")
    print(f"  明细表 CASH 行({len(cash_rows)}) 口径正确 : {cash_row_ok}")
    for ln in cash_rows:
        print(f"      {ln[:120]}")
    print(f"  现金脚注 : {'YES' if notes else 'NO'}")
    print(f"  取整披露 : {'YES' if drift else 'NO (无漂移)'}")

    ok = struct_ok and cash_row_ok and cmp_row is not None and bool(notes)
    all_ok = all_ok and ok
    print(f"  => {'PASS' if ok else 'FAIL'}")

print("=" * 74)
print("PIPELINE REALITY:", "PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)