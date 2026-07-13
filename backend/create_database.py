import sqlite3

# Remove existing database if any
try:
    import os
    if os.path.exists('data/portfolio.db'):
        os.remove('data/portfolio.db')
        print('Removed existing database')
except:
    pass

# Create new database with proper schema
conn = sqlite3.connect('data/portfolio.db')
c = conn.cursor()

# Create portfolio_etfs table with tracked_index column
c.execute('''
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

# Insert the new holdings after our ETF replacement
# On exchange (512890 is our new 红利低波ETF - 华泰柏瑞中证红利低波动ETF, tracked by 中证红利低波动指数)
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
    
    # Off exchange (007467 is our new 红利低波ETF联接C - 华泰柏瑞中证红利低波动ETF联接C, tracked by 000300)
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

# Insert each holding
for holding in holdings:
    c.execute('INSERT INTO portfolio_etfs (symbol, name, asset_type, target_weight, portfolio_type, short_name, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)', holding)

conn.commit()
conn.close()

print("Database created with new holdings!")
print("\nHoldings summary:")
print(f"On exchange: {sum(1 for h in holdings if h[4] == 'on_exchange')} funds")
print(f"Off exchange: {sum(1 for h in holdings if h[4] == 'off_exchange')} funds")
print(f"Total: {len(holdings)} funds")