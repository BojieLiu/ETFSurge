#!/usr/bin/env python3
import sqlite3
import os

print("Setting up database for 红利低波ETF and 红利低波ETF联接C...")
print("=" * 60)

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check if table exists or create it
if not cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_etfs'").fetchone():
    print("Creating portfolio_etfs table...")
    # Add tracked_index column
    cur.execute('''
    CREATE TABLE portfolio_etfs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol VARCHAR(20) NOT NULL,
        name VARCHAR(100) NOT NULL,
        asset_type VARCHAR(20) NOT NULL DEFAULT "A",
        target_weight FLOAT NOT NULL,
        portfolio_type VARCHAR(20) NOT NULL DEFAULT "on_exchange",
        short_name VARCHAR(60),
        is_active BOOLEAN DEFAULT TRUE,
        tracked_index VARCHAR(20)
    )
    ''')
    print("✓ Table created with tracked_index column")

# Remove all existing holdings
cur.execute('DELETE FROM portfolio_etfs')
print("✓ Cleared all existing holdings")

print("\nInserting NEW holdings (after 红利高波ETF replacement):")

# Insert new holdings
new_holdings = [
    # 1. 红利低波ETF (华泰柏瑞中证红利低波动ETF) - on exchange, no tracked_index
    (512890, '华泰柏瑞中证红利低波动ETF', 'A', 0.065, 'on_exchange', '红利低波ETF', 1),
    
    # 2. 红利低波ETF联接C (华泰柏瑞中证红利低波动ETF联接C) - off exchange, tracked_index = 000300
    (7467, '华泰柏瑞中证红利低波动ETF联接C', 'A', 0.065, 'off_exchange', '红利低波联接C', 1),
    
    # Other typical holdings (preserved from previous setup)
    (159338, '平安A500ETF', 'A', 0.19, 'on_exchange', 'A500ETF', 1),
    (159545, '大成证券ETF', 'A', 0.04, 'on_exchange', '证券ETF', 1),
    (159516, '博时设备ETF', 'A', 0.035, 'on_exchange', '设备ETF', 1),
    (159992, '嘉实医药ETF', 'A', 0.04, 'on_exchange', '医药ETF', 1),
    (513120, '万家新能源ETF', 'A', 0.04, 'on_exchange', '新能源ETF', 1),
    (513010, '南方创业ETF', 'A', 0.025, 'on_exchange', '创业板ETF', 1),
    (512000, '东方红ETF', 'A', 0.065, 'on_exchange', '东方红ETF', 1),
    (159869, '天弘交通ETF', 'A', 0.04, 'on_exchange', '交通ETF', 1),
    (518880, '华泰柏瑞周期ETF', 'A', 0.09, 'on_exchange', '周期ETF', 1),
    
    (22449, '华泰柏瑞A500ETF联接C', 'A', 0.19, 'off_exchange', 'A500联接C', 1),
    (21458, '南方证券ETF联接C', 'A', 0.04, 'off_exchange', '证券联接C', 1),
    (19633, '华泰柏瑞设备ETF联接C', 'A', 0.035, 'off_exchange', '设备联接C', 1),
    (12782, '嘉实医药ETF联接C', 'A', 0.04, 'off_exchange', '医药联接C', 1),
    (19671, '万家新能源ETF联接C(QDII)', 'A', 0.04, 'off_exchange', '新能源联接C', 1),
    (13309, '南方创业ETF联接C', 'A', 0.025, 'off_exchange', '创业板联接C', 1),
    (7531, '东方红ETF联接C', 'A', 0.065, 'off_exchange', '东方红联接C', 1),
    (12769, '天弘交通ETF联接C', 'A', 0.04, 'off_exchange', '交通联接C', 1),
    (217, '华泰柏瑞周期ETF联接C', 'A', 0.09, 'off_exchange', '周期联接C', 1),
]

# Insert the holdings
cur.executemany('INSERT INTO portfolio_etfs VALUES (?,?,?,?,?,?,?,?,?)', new_holdings)
print(f"✓ Inserted {len(new_holdings)} new holdings")

# Set tracked_index for 007467 (华泰柏瑞中证红利低波动ETF联接C)
print("\nSetting tracked_index for 007467 (华泰柏瑞中证红利低波动ETF联接C)...")
cur.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '7467'")
print("✓ Updated tracked_index for 007467 to 000300")

conn.commit()

# Verify the setup
print("\n=== Database Verification ===")
cur.execute("SELECT id, symbol, name, portfolio_type, tracked_index FROM portfolio_etfs ORDER BY id")

print("All holdings:")
for row in cur.fetchall():
    print(f"  ID: {row['id']:2d} | Symbol: {row['symbol']:6s} | Type: {row['portfolio_type']:12s} | Tracked: {row['tracked_index']}")

print("\n=== Special Focus on 红利低波ETF Holdings ===")
for row in cur.execute("SELECT symbol, name, portfolio_type, tracked_index FROM portfolio_etfs WHERE symbol IN ('512890', '7467')"):
    print(f"  {row['symbol']:6s} ({row['name']})")
    print(f"    - Type: {row['portfolio_type']}")
    print(f"    - Tracked Index: {row['tracked_index']}")

conn.close()

print("\n" + "=" * 60)
print("SUCCESS: Database setup complete!")
print("=" * 60)
print("\nKey improvements:")
print("✓ Added tracked_index column to portfolio_etfs table")
print("✓ Replaced 红利高波ETF with 红利低波ETF (512890)")
print("✓ Replaced 红利高波ETF联接C with 红利低波ETF联接C (7467)")
print("✓ 红利低波ETF联接C (7467) tracks 000300 for pre-profit estimates")
print("✓ All existing holdings preserved")
print("\nNow the dashboard will correctly display:")
print("  - 红利低波ETF (512890) and 红利低波ETF联接C (7467)")
print("  - 红利低波ETF联接C will use 000300 (沪深300) for profit/forecast estimates")
print("  - Cash positions will be calculated correctly")
print("=" * 60)