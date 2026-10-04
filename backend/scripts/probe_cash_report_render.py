"""现实验证：用 DB 里真实 design（id=85）的 strategies_json 重跑报告渲染层。

反假完成·非兜底数据：断言必须来自真实引擎产出（真代码、真权重、真因子分），
不是我自己写的夹具。零网络零 LLM——只跑 §一 纯函数。
"""
import json
import pathlib
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.tasks.design_report import _build_plan_tables  # noqa: E402

DESIGN_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 85
# 真实库在仓库根 data/（backend/data/portfolio.db 是 0 字节陈旧文件）
DB = pathlib.Path(__file__).resolve().parents[2] / "data" / "portfolio.db"

con = sqlite3.connect(DB)
row = con.execute(
    "select strategies_json, design_text, capital from portfolio_designs where id=?",
    (DESIGN_ID,),
).fetchone()
if row is None:
    print(f"BROKEN: design {DESIGN_ID} 不存在")
    sys.exit(2)

strategies = json.loads(row[0])
old_text = row[1]
new_text = _build_plan_tables(strategies)


def _cur_allocs(label):
    return next(s.get("etfs", []) for s in strategies if s.get("label") == label)

print(f"design id={DESIGN_ID}  capital={row[2]}  strategies={len(strategies)}")
print("=" * 78)

# ── 1. 新旧对比：每方案资产结构行 ──
print("[1] 资产结构行（新）")
for ln in new_text.splitlines():
    if ln.startswith("资产结构"):
        print("   ", ln)

# ── 2. 权重列自洽：精确 Σ 必为 100%；显示合计若偏离必须有取整披露 ──
print("\n[2] 每方案权重：精确 Σ 与显示合计")
disclosed = "四舍五入" in new_text
cur_label, acc, bad = None, 0.0, []
for ln in new_text.splitlines():
    if ln.startswith("### "):
        cur_label = ln[4:]
    elif ln.strip().startswith("|") and cur_label:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 8 and cells[1] and cells[1] != "代码":
            raw = cells[3].rstrip("%").lstrip("≈")
            try:
                acc += float(raw)
            except ValueError:
                pass
    elif acc and not ln.strip().startswith("|"):
        exact = sum(e.get("weight") or 0 for e in _cur_allocs(cur_label))
        ok_exact = abs(exact - 1.0) < 1e-6
        ok_shown = abs(acc - 100.0) < 1.0 or disclosed
        verdict = "OK" if (ok_exact and ok_shown) else "MISMATCH"
        print(f"    {cur_label}: Σ精确={exact:.6f}  Σ显示={acc:.0f}%  {verdict}")
        if verdict == "MISMATCH":
            bad.append(cur_label)
        acc = 0.0

# ── 3. 现金与 DB 真值逐位一致（不是渲染层的自洽，是与源数据一致）──
print("\n[3] 现金 vs DB 源数据（精确权重 + 显示取整差）")
ok_cash = True
for s in strategies:
    rows = s.get("etfs", [])
    db_cash = next((e.get("weight") for e in rows if e.get("symbol") == "CASH"), None)
    exact_sum = sum(e.get("weight") or 0 for e in rows)
    shown_sum = sum(round((e.get("weight") or 0) * 100) for e in rows)
    lbl = s.get("label")
    seg = new_text.split(f"### {lbl}", 1)[1][:400]
    in_report = f"现金 {round(db_cash * 100):.0f}%" in seg if db_cash else True
    print(f"    {lbl}: DB现金={db_cash}  Σ精确={exact_sum:.6f}  "
          f"Σ显示={shown_sum}%  报告含该值={in_report}")
    ok_cash = ok_cash and in_report and abs(exact_sum - 1.0) < 1e-6

# ── 4. 现金行真实存在于明细表且列齐全 ──
print("\n[4] 现金行")
for ln in new_text.splitlines():
    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
    if len(cells) == 8 and cells[1] == "CASH":
        print("    ", " | ".join(cells))
        break
else:
    print("     MISSING")

print("\n" + "=" * 78)
print("REALITY:", "PASS" if (ok_cash and not bad) else f"FAIL (bad={bad}, cash_ok={ok_cash})")
sys.exit(0 if (ok_cash and not bad) else 1)