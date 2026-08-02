# -*- coding: utf-8 -*-
"""instruments 表资产类型分布"""
import sqlite3, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
conn = sqlite3.connect('data/portfolio.db')
cur = conn.cursor()
cur.execute('SELECT asset_type, market, COUNT(*) FROM instruments GROUP BY asset_type, market')
for r in cur.fetchall():
    print(f'asset_type={r[0]}, market={r[1]}: {r[2]} 行')
cur.execute("SELECT COUNT(*) FROM instruments WHERE asset_type='stock' AND market='A'")
print('A 股个股(asset_type=stock):', cur.fetchone()[0])
cur.execute("SELECT symbol, name FROM instruments WHERE market='A' AND asset_type='stock' LIMIT 5")
print('个股样本:', [tuple(r) for r in cur.fetchall()])
