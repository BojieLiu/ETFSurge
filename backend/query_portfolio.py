# Query portfolio holdings
import sqlite3

conn = sqlite3.connect('E:\\\ETF_Surge\\\\backend\\\\data\\\\portfolio.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('=== 场外基金 ===')
cur.execute('''
    SELECT id, symbol, name, asset_type, target_weight, portfolio_type, tracked_index 
    FROM portfolio_etfs 
    WHERE is_active = 1 AND portfolio_type = 'off_exchange'
''')
for row in cur.fetchall():
    print(f'{row["id"]:2d} | {row["symbol"]:6s} | {row["name"]:30s} | {row["tracked_index"]}')

print('\n=== 场内基金 ===')
cur.execute('''
    SELECT id, symbol, name, asset_type, target_weight, portfolio_type, tracked_index 
    FROM portfolio_etfs 
    WHERE is_active = 1 AND portfolio_type = 'on_exchange'
''')
for row in cur.fetchall():
    print(f'{row["id"]:2d} | {row["symbol"]:6s} | {row["name"]:30s} | tracked_index: {row["tracked_index"]}')

conn.close()
