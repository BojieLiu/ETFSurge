"""Audit SourceRegistry coverage vs direct external API calls."""
import os
import glob

base = 'E:/ETF_Surge/backend/app'

# All modules that use SourceRegistry
reg_users = []
direct_users = []

for fpath in sorted(glob.glob(os.path.join(base, '**/*.py'), recursive=True)):
    with open(fpath, 'r', encoding='utf-8') as f:
        try:
            content = f.read()
        except UnicodeDecodeError:
            continue
    
    rel = os.path.relpath(fpath, base).replace('\\', '/')
    
    # Skip non-business files
    if rel.startswith('__') or '/__pycache__/' in fpath:
        continue
    
    uses_reg = 'registry.route(' in content or 'registry._health(' in content
    has_external = any(kw in content.lower() for kw in [
        'push2.eastmoney', 'ak.stock_individual_fund_flow', 'ak.fund_etf',
        'ak.stock_zh_a_hist', 'ak.stock_board', 'ak.index_global',
        'ak.stock_margin', 'ak.stock_news', 'ak.macro_china_pmi',
        'ak.bond_china_yield', 'levistock', 'yfinance', 'tushare',
        'finnhub', 'alphavantage', 'twelvedata',
    ])
    
    if uses_reg:
        reg_users.append(rel)
    if has_external and not uses_reg:
        # Check if it's in our target paths
        if rel.startswith(('services/', 'fetchers/', 'factors/')):
            direct_users.append(rel)

print("=== Modules USING SourceRegistry circuit breaker ===")
for m in reg_users:
    print(f"  {m}")

print()
print("=== Modules with external API calls but NOT using SourceRegistry ===")
for m in direct_users:
    print(f"  {m} (UNPROTECTED)")
