# -*- coding: utf-8 -*-
"""560600 名称来源核查 + 快照路径定义"""
import json, os, sqlite3, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    # 1. 快照（项目根 data/）
    sp = os.path.join("..", "data", "etf_list_cache.json")
    if os.path.exists(sp):
        data = json.load(open(sp, encoding="utf-8"))
        etfs = data.get("etfs", []) if isinstance(data, dict) else data
        print("[快照] etfs:", len(etfs))
        hit = [e for e in etfs if str(e.get("symbol")) == "560600"]
        print("  560600:", json.dumps(hit, ensure_ascii=False)[:300] if hit else "NOT IN SNAPSHOT")
        # 快照里有多少 560xxx 段 ETF
        seg = [e.get("symbol") for e in etfs if str(e.get("symbol", "")).startswith("56")]
        print("  56xxx 段:", seg[:20], "... 共", len(seg))

    # 2. instruments 表
    db_path = os.path.join("..", "data", "portfolio.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            print("\n[DB tables]:", tables)
            for t in tables:
                if "instrument" in t.lower() or "etf" in t.lower():
                    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
                    sym_col = "symbol" if "symbol" in cols else (cols[0] if cols else None)
                    if sym_col:
                        cur.execute(f"SELECT * FROM {t} WHERE {sym_col}='560600' LIMIT 3")
                        rows = cur.fetchall()
                        print(f"  {t} cols={cols[:10]} 560600 rows={len(rows)}")
                        for r in rows[:2]:
                            print("   ", r[:12])
                    # 名称含 中证A500 的
                    name_col = "name" if "name" in cols else None
                    if name_col:
                        cur.execute(f"SELECT * FROM {t} WHERE {name_col} LIKE '%中证A500%' LIMIT 5")
                        for r in cur.fetchall():
                            print("  A500 hit:", r[:8])
        finally:
            conn.close()

    # 3. _etf_cache_file 定义
    import inspect
    from app.services.strategy_design import _etf_cache_file
    print("\n[_etf_cache_file] source:")
    print(inspect.getsource(_etf_cache_file))


main()
