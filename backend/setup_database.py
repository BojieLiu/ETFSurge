import sqlite3
import os

print("Setting up database for redlow_index ETF replacement...")

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Drop the existing table and recreate with tracked_index column
c.execute("DROP TABLE IF EXISTS portfolio_etfs")
print("✓ Dropped existing portfolio_etfs table")

# Create new table with tracked_index column
c.execute('''
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
print("✓ Created portfolio_etfs table with tracked_index column")

# Insert holdings
print("\nInserting new holdings...")

# On exchange holdings (including new 红利低波ETF)
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

# Off exchange holdings (including new 红利低波ETF联接C with tracked_index)
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

# Set tracked_index for 007467
print("\nSetting tracked_index for 007467...")
cur.execute("UPDATE portfolio_etfs SET tracked_index = '000300' WHERE symbol = '007467'")
print(f"✓ Updated tracked_index for 007467 to 000300 (沪深300)")

conn.commit()

# Verify the changes
print("\n=== Verification ===")
cur.execute('SELECT id, symbol, portfolio_type, tracked_index FROM portfolio_etfs ORDER BY id')
print("All holdings:")
for row in cur.fetchall():
    print(f"  ID: {row['id']:2d}, Symbol: {row['symbol']:6s}, Type: {row['portfolio_type']:12s}, Tracked: {row['tracked_index']}")

# Check for 红利低波ETF-related holdings
print("\n=== 红利低波ETF Holdings ===")
cur.execute('SELECT symbol, name, portfolio_type, tracked_index FROM portfolio_etfs WHERE (symbol IN (\"512890\", \"007467\"))')
for row in cur.fetchall():
    print(f"  {row['symbol']:6s} ({row['name']}) - {row['portfolio_type']}")
if row['tracked_index']:
    print(f"    Tracked Index: {row['tracked_index']}")

conn.close()
print("\n✓ Database setup complete!")
print("=" * 60)
print("Summary:")
print("  - Replaced 红利ETF with 红利低波ETF (512890 on-exchange, 007467 off-exchange)")
print("  - 512890 tracks 中证红利低波动指数 (no tracked_index needed for domestic ETF)")
print("  - 007467 tracks 000300 (沪深300)")
print("=" * 60)