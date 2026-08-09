#!/usr/bin/env python3
"""One-time repair of existing mojibake ETF names in the database."""
import sqlite3, sys

DB = "data/portfolio.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Find garbled names (contains latin1 supplement chars)
cur.execute("SELECT rowid, symbol, name, short_name FROM portfolio_etfs")
fixed_count = 0
for row in cur.fetchall():
    rowid, symbol, name, short_name = row
    changed = False
    for field_name, field_val in [("name", name), ("short_name", short_name)]:
        if field_val is None:
            continue
        # Check for latin1-supplement bytes (0x80-0xFF) → indicates mojibake
        if any('\x80' <= c <= '\xff' for c in field_val):
            try:
                fixed = field_val.encode("latin1").decode("utf-8")
                if fixed != field_val:
                    print(f"  REPAIR {symbol}: {field_name} {repr(field_val[:30])} -> {repr(fixed[:30])}")
                    cur.execute(f"UPDATE portfolio_etfs SET {field_name}=? WHERE rowid=?",
                                (fixed, rowid))
                    changed = True
                    fixed_count += 1
            except:
                print(f"  SKIP {symbol}: {field_name} {repr(field_val[:30])} (decode failed)")
        # Check for replacement character U+FFFD
        if '\ufffd' in field_val:
            print(f"  BAD CHAR {symbol}: {field_name} {repr(field_val[:30])}")

if fixed_count > 0:
    conn.commit()
    print(f"\n  Repaired {fixed_count} garbled names")
else:
    print("  No garbled names found (already clean)")

conn.close()
sys.exit(0)
