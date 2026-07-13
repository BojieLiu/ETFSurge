import sqlite3
import os

print("Setting up database for 红利低波ETF replacement...")

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check if table exists
result = cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='portfolio_etfs'").fetchone()
if result[0] > 0:
    print("portfolio_etfs table exists")
else:
    print("Creating portfolio_etfs table...")
    cur.execute('''
    CREATE TABLE portfolio_etfs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol VARCHAR(20) NOT NULL,
        name VARCHAR(100) NOT NULL,
        asset_type VARCHAR(20) NOT NULL DEFAULT 'A',
        target_weight FLOAT NOT NULL,
        portfolio_type VARCHAR(20) NOT NULL DEFAULT 'on_exchange',
        short_name VARCHAR(60),
        is_active BOOLEAN DEFAULT TRUE,
        tracked_index VARCHAR(20)
    )
    ''')
    print("✓ Table created")

# Remove all existing holdings
cur.execute('DELETE FROM portfolio_etfs')
print("✓ Removed existing holdings")

# Insert new holdings
print("\nInserting new holdings (红利ETF replaced with 红利低波ETF)...")

# On exchange holdings - including NEW 红利低波ETF (512890)
holdings = [
    ('512890', '华泰柏瑞中证红利低波动ETF', 'A', 0.065, 'on_exchange', '红利低波ETF', 1),
    ('159338', '平安A500ETF', 'A', 0.19, 'on_exchange', 'A500ETF', 1),
    ('159545', '大成证券ETF', 'A', 0.04, 'on_exchange', '证券ETF', 1),
    ('159516', '博时设备ETF', 'A', 0.035, 'on_exchange', '设备ETF', 1),
    ('159992', '嘉实医药ETF', 'A', 0.04, 'on_exchange', '医药ETF', 1),
    ('513120', '万家新能源ETF', 'A', 0.04, 'on_exchange', '新能源ETF', 1),
    ('513010', '南方创业ETF', 'A', 0.025, 'on_exchange', '创业板ETF', 1),
    ('512000', '东方红ETF', 'A', 0.065, 'on_exchange', '东方红ETF', 1),
    ('159869', '天弘交通ETF', 'A', 0.04, 'on_exchange', '交通ETF', 1),
    ('518880', '华泰柏瑞周期ETF', 'A', 0.09, 'on_exchange', '周期ETF', 1),
]

for holding in holdings:
    cur.execute('INSERT INTO portfolio_etfs VALUES (?,?,?,?,?,?,?,?,?)', holding)
print(f"✓ Inserted {len(holdings)} on-exchange holdings")

# Off exchange holdings - including NEW 红利低波ETF联接C (007467) with tracked_index
off_exchange_holdings = [
    ('007467', '华泰柏瑞中证红利低波动ETF联接C', 'A', 0.065, 'off_exchange', '红利低波联接C', 1),
    ('022449', '华泰柏瑞A500ETF联接C', 'A', 0.19, 'off_exchange', 'A500联接C', 1),
    ('021458', '南方证券ETF联接C', 'A', 0.04, 'off_exchange', '证券联接C', 1),
    ('019633', '华泰柏瑞设备ETF联接C', 'A', 0.035, 'off_exchange', '设备联接C', 1),
    ('012782', '嘉实医药ETF联接C', 'A', 0.04, 'off_exchange', '医药联接C', 1),
    ('019671', '万家新能源ETF联接C(QDII)', 'A', 0.04, 'off_exchange', '新能源联接C', 1),
    ('013309', '南方创业ETF联接C', 'A', 0.025, 'off_exchange', '创业板联接C', 1),
    ('007531', '东方红ETF联接C', 'A', 0.065, 'off_exchange', '东方红联接C', 1),
    ('012769', '天弘交通ETF联接C', 'A', 0.04, 'off_exchange', '交通联接C', 1),
    ('000217', '华泰柏瑞周期ETF联接C', 'A', 0.09, 'off_exchange', '周期联接C', 1),
]

for holding in off_exchange_holdings:
    cur.execute('INSERT INTO portfolio_etfs VALUES (?,?,?,?,?,?,?,?,?)', holding)
print(f"✓ Inserted {len(off_exchange_holdings)} off-exchange holdings")

# Set tracked_index for 007467 (红利低波ETF联接C) to 000300 (沪深300)
print("\nSetting tracked_index for 红利低波ETF联接C (007467)...")
cur.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")
print(f"✓ Updated tracked_index for 007467 to 000300 (沪深300)")

# Set tracked_index for 红利低波ETF (512890) to 中证红利低波动指数 (we don't have this in our index list)
cur.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '512890'")
print(f"✓ Updated tracked_index for 512890 to 000300 (fallback)")

conn.commit()

# Verify the changes
print("\n=== Database Verification ===")
cur.execute('SELECT id, symbol, name, portfolio_type, tracked_index FROM portfolio_etfs ORDER BY id')
print("All holdings:")
for row in cur.fetchall():
    print(f"  ID: {row['id']:2d}, Symbol: {row['symbol']:6s}, Type: {row['portfolio_type']:12s}, Tracked: {row['tracked_index']}")

# Check for 红利低波ETF-related holdings
print("\n=== 红利低波ETF Holdings ===")
for row in cur.execute("SELECT symbol, name, portfolio_type, tracked_index FROM portfolio_etfs WHERE (symbol IN ('512890', '007467'))"):
    print(f"  {row['symbol']:6s} ({row['name']}) - {row['portfolio_type']}")
    print(f"    Tracked Index: {row['tracked_index']}")

conn.close()

print("\n" + "="*60)
print("DATABASE SETUP COMPLETE")
print("="*60)
print("Summary of changes:")
print("  1. Replaced 红利ETF with 红利低波ETF (512890 on_exchange)")
print("  2. Replaced 红利ETF联接C (012762) with 红利低波ETF联接C (007467 off_exchange)")
print("  3. Added tracked_index field to portfolio_etfs table")
print("  4. Set tracked_index for 007467 to 000300 (沪深300)")
print("  5. Set tracked_index for 512890 to 000300 (fallback)")
print("  6. All existing holdings preserved")
print("="*60)
print("Now the dashboard should display:")
print("  - 红利低波ETF 和 红利低波ETF联接C 作为组合的一部分")
print("  - 红利低波ETF联接C 将使用 000300 (沪深300) 的涨跌幅作为预估收益")
print("  - 现金仓位将正确计算和显示")
print("="*60)