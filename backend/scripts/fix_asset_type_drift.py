"""fix_asset_type_drift.py — 订正 portfolio_etfs.asset_type 口径漂移（R176 / round52 §7.3 方案E-1）。

背景（round52 §7.1）：2026-09-01 持仓重灌（commit 3fb66b1）的 seed CSV 第 4 列把
场内 ETF 写成 `asset_type='ETF'`，而 pricing 全链路（`_split_symbols` / `allocation.py`
基本面分支 / `hub.get_asset_realtime`）只认 `'A'` → **带 portfolio_type 过滤的请求**
（页面 tab 切「场内」/「场外」）四个批量分支全空 → `price_map` 空 dict → 现价/涨跌幅
恒 0（用户截图 ¥0.00 / +0.00%）。无类型查询时靠场外 15 只的 tracked_index 批量捎带
才「看起来正常」，掩盖了该缺陷（8-27 灌录口径为 'A' 时代未显形）。

订正范围：**仅** `UPPER(TRIM(asset_type)) = 'ETF'` 的行改为 `'A'`；HK/US 等其它
市场的持仓**不动**（误改会让港股/美股标的走错批量分支）。幂等（二次运行 0 更新）。

用法（Dry-run 为默认，必须显式 --apply 才写库）：
    python scripts/fix_asset_type_drift.py                        # 默认 data/portfolio.db，dry-run
    python scripts/fix_asset_type_drift.py --db-path <path>       # 指定库
    python scripts/fix_asset_type_drift.py --apply                # 真正写库

退出码：0 = 无漂移或订正成功；1 = 写库失败；2 = 库不可用/缺表。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# 项目根 data/portfolio.db（backend/scripts -> 项目根；与 verify_e2e.py 同口径）。
# 注意：backend/data/portfolio.db 是历史遗留空库，不是生产库。
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "portfolio.db")
DRIFT_VALUE = "ETF"
TARGET_VALUE = "A"


def normalize_db_asset_types(db_path: str, apply: bool = False) -> dict:
    """扫描并订正 asset_type='ETF' → 'A'。

    Returns:
        {"matched": [symbol...], "updated": int, "applied": bool, "error": str|None}
    """
    out: dict = {"matched": [], "updated": 0, "applied": apply, "error": None}
    try:
        conn = sqlite3.connect(db_path)
    except Exception as exc:  # 库不可读（路径错/权限）
        out["error"] = f"connect failed: {exc}"
        return out
    try:
        rows = conn.execute(
            "SELECT id, symbol, portfolio_type, asset_type FROM portfolio_etfs"
        ).fetchall()
    except sqlite3.Error as exc:  # 缺表/非项目库
        out["error"] = f"query failed: {exc}"
        conn.close()
        return out

    drifted = [
        (rid, sym)
        for rid, sym, _pt, at in rows
        if str(at or "").strip().upper() == DRIFT_VALUE
    ]
    out["matched"] = [sym for _rid, sym in drifted]

    if apply and drifted:
        try:
            conn.executemany(
                "UPDATE portfolio_etfs SET asset_type = ? WHERE id = ?",
                [(TARGET_VALUE, rid) for rid, _sym in drifted],
            )
            conn.commit()
            out["updated"] = len(drifted)
        except sqlite3.Error as exc:
            conn.rollback()
            out["error"] = f"update failed: {exc}"
    conn.close()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="订正 portfolio_etfs.asset_type 漂移（ETF → A，R176）"
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="SQLite 库路径")
    parser.add_argument("--apply", action="store_true",
                        help="真正写库（默认 dry-run，只报告不修改）")
    args = parser.parse_args(argv)

    db_path = args.db_path
    if not Path(db_path).exists():
        print(f"[ERROR] 数据库不存在: {db_path}")
        return 2

    report = normalize_db_asset_types(db_path, apply=args.apply)
    if report["error"]:
        print(f"[ERROR] {report['error']}（db={db_path}）")
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    if not report["matched"]:
        print(f"[{mode}] 无 asset_type='{DRIFT_VALUE}' 漂移行（口径已一致）")
        return 0
    print(f"[{mode}] 命中漂移行 {len(report['matched'])} 条: {', '.join(report['matched'])}")
    if args.apply:
        print(f"[APPLY] 已订正 {report['updated']} 条 → asset_type='{TARGET_VALUE}'")
    else:
        print("[DRY-RUN] 未写库；确认后加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
