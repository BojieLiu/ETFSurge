#!/usr/bin/env python3
import sqlite3, json, sys
c = sqlite3.connect("data/portfolio.db").cursor()

c.execute("SELECT id, created_at, status FROM portfolio_designs ORDER BY id DESC LIMIT 3")
for r in c.fetchall():
    print(f"design id={r[0]} created={str(r[1])[:19]} status={r[2]}")

c.execute("SELECT id, created_at, market_regime FROM strategy_check_records ORDER BY id DESC LIMIT 3")
for r in c.fetchall():
    print(f"check id={r[0]} created={str(r[1])[:19]} regime={r[2]}")
c.close()
