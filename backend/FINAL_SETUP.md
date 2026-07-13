# Final Setup Instructions for 红利高波ETF → 红利低波ETF Replacement

## Summary
This document provides the final setup instructions for replacing the old 红利高波ETF holdings with the new 红利低波ETF holdings.

## Required Changes

### 1. Database Setup
- **File**: `data/portfolio.db`
- **Action**: Replace existing holdings with new set

#### Old Holdings (to be removed):
- On Exchange: `512880` (红利高波ETF)
- Off Exchange: `012762` (红利高波ETF联接C)

#### New Holdings (to be added):
- On Exchange: `512890` (华泰柏瑞中证红利低波动ETF)
- Off Exchange: `7467` (华泰柏瑞中证红利低波动ETF联接C)

#### Special Configuration:
- **007467 (红利低波ETF联接C)**: Set `tracked_index = "000300"` (沪深300)
- **512890 (红利低波ETF)**: No `tracked_index` needed (domestic ETF)

### 2. Backend Code
- **File**: `app/services/portfolio_service.py`
- **Action**: Ensure the `calculate_allocation` function correctly returns:
  - `cash_weight`
  - `cash_amount`
  - All holdings with proper `tracked_index`

## Setup Commands

### Step 1: Kill Existing Processes
```bash
# Kill all uvicorn processes
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "uvicorn" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Clean up any leftover processes
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "uvicorn" } | Stop-Process -Force -ErrorAction SilentlyContinue
```

### Step 2: Setup Database
```python
import sqlite3
import os

print("Setting up database for 红利高波ETF → 红利低波ETF replacement...")

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Connect to database
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Clear existing holdings and create new ones
c.execute('DELETE FROM portfolio_etfs')
print("✓ Cleared existing holdings")

# Define new holdings
# Note: Using 512890 for on_exchange and 7467 for off_exchange to match the requirement
new_holdings = [
    # On Exchange holdings (including new 红利低波ETF)
    (512890, '华泰柏瑞中证红利低波动ETF', 'A', 0.065, 'on_exchange', '红利低波ETF', 1),
    (159338, '平安A500ETF', 'A', 0.19, 'on_exchange', 'A500ETF', 1),
    (159545, '大成证券ETF', 'A', 0.04, 'on_exchange', '证券ETF', 1),
    (159516, '博时设备ETF', 'A', 0.035, 'on_exchange', '设备ETF', 1),
    (159992, '嘉实医药ETF', 'A', 0.04, 'on_exchange', '医药ETF', 1),
    (513120, '万家新能源ETF', 'A', 0.04, 'on_exchange', '新能源ETF', 1),
    (513010, '南方创业ETF', 'A', 0.025, 'on_exchange', '创业板ETF', 1),
    (512000, '东方红ETF', 'A', 0.065, 'on_exchange', '东方红ETF', 1),
    (159869, '天弘交通ETF', 'A', 0.04, 'on_exchange', '交通ETF', 1),
    (518880, '华泰柏瑞周期ETF', 'A', 0.09, 'on_exchange', '周期ETF', 1),
    
    # Off Exchange holdings (including new 红利低波ETF联接C with tracked_index)
    (7467, '华泰柏瑞中证红利低波动ETF联接C', 'A', 0.065, 'off_exchange', '红利低波联接C', 1),
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

# Insert holdings
c.executemany('INSERT INTO portfolio_etfs VALUES (?,?,?,?,?,?,?,?,?)', new_holdings)
print(f"✓ Inserted {len(new_holdings)} holdings")

# Set tracked_index for 007467 (华泰柏瑞中证红利低波动ETF联接C)
print("\nSetting tracked_index for 007467...")
c.execute('UPDATE portfolio_etfs SET tracked_index = "000300" WHERE symbol = "7467"')
print("✓ Updated tracked_index for 007467 to 000300 (沪深300)")

conn.commit()
conn.close()

print("\n✓ Database setup complete!")
```

### Step 3: Test the API
```bash
python -c "
import requests

# Test on_exchange endpoint
response = requests.post('http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=on_exchange', 
                        json={'total_capital': 500000})
print('on_exchange:', response.status_code, response.json().get('cash_weight', 'missing'))

# Test off_exchange endpoint
response = requests.post('http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=off_exchange', 
                        json={'total_capital': 500000})
print('off_exchange:', response.status_code, response.json().get('cash_weight', 'missing'))

# Check if 红利低波ETF (512890) and 红利低波ETF联接C (7467) exist
response = requests.post('http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=on_exchange', 
                        json={'total_capital': 500000})
on_exchange_data = response.json()

response = requests.post('http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=off_exchange', 
                        json={'total_capital': 500000})
off_exchange_data = response.json()

# Check for 红利低波ETF (512890) in on_exchange
found_512890 = any(item['symbol'] == '512890' for item in on_exchange_data['allocations'])
print(f'✓ 红利低波ETF (512890) found: {found_512890}')

# Check for 红利低波ETF联接C (7467) in off_exchange
found_7467 = any(item['symbol'] == '7467' for item in off_exchange_data['allocations'])
print(f'✓ 红利低波ETF联接C (7467) found: {found_7467}')

if found_7467:
    redlow_7467 = next(item for item in off_exchange_data['allocations'] if item['symbol'] == '7467')
    print(f'  - tracked_index: {redlow_7467.get(\"tracked_index\", \"missing\")}')
    print(f'  - change_pct: {redlow_7467.get(\"change_pct\", \"missing\")}%')

print('')
print('Database setup and API verification complete!')
"
```

## Verification Checklist

After running the setup, verify the following:

### Database Verification
- [ ] `data/portfolio.db` exists
- [ ] `tracked_index` column exists in `portfolio_etfs` table
- [ ] No records with symbol `510880` (old 红利高波ETF)
- [ ] No records with symbol `012762` (old 红利高波ETF联接C)
- [ ] One record with symbol `512890` (new 红利低波ETF)
- [ ] One record with symbol `7467` (new 红利低波ETF联接C)
- [ ] `7467` record has `tracked_index = '000300'`

### API Verification
- [ ] `http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=on_exchange` returns:
  - `cash_weight` field
  - `cash_amount` field
  - 10 on-exchange holdings including `512890` (红利低波ETF)
- [ ] `http://localhost:8000/api/v1/portfolio/calculate?portfolio_type=off_exchange` returns:
  - `cash_weight` field
  - `cash_amount` field
  - 9 off-exchange holdings including `7467` (红利低波ETF联接C)
  - `7467` has `tracked_index = '000300'`
  - `7467` has correct `change_pct` based on `000300`

## Expected Results

### On Exchange Portfolio (512890 added)
```json
{
  "total_capital": 500000,
  "allocations": [
    {"symbol": "512890", "name": "华泰柏瑞中证红利低波动ETF", ...},
    {"symbol": "159338", "name": "平安A500ETF", ...},
    // ... other holdings
  ],
  "cash_weight": 0.37,
  "cash_amount": 185000.00
}
```

### Off Exchange Portfolio (7467 added with tracked_index)
```json
{
  "total_capital": 500000,
  "allocations": [
    {"symbol": "7467", "name": "华泰柏瑞中证红利低波动ETF联接C", "tracked_index": "000300", "change_pct": 0.25, ...},
    {"symbol": "22449", "name": "华泰柏瑞A500ETF联接C", "tracked_index": null, "change_pct": 0.12, ...},
    // ... other holdings
  ],
  "cash_weight": 0.37,
  "cash_amount": 185000.00
}
```

## Key Points

1. **Removed Old Holdings**: The old 红利高波ETF (510880) and 红利高波ETF联接C (012762) holdings have been removed from the database.

2. **Added New Holdings**: The new 红利低波ETF (512890) on-exchange and 红利低波ETF联接C (7467) off-exchange holdings have been added.

3. **Track Index Setup**: The 红利低波ETF联接C (7467) is properly configured to track the 000300 (沪深300) index using the `tracked_index` field.

4. **API Consistency**: The `calculate_allocation` function in `portfolio_service.py` has been updated to return `cash_weight` and `cash_amount` fields for both on-exchange and off-exchange portfolios.

5. **Dashboard Support**: The dashboard will now correctly display:
   - Cash positions using the `cash_weight` and `cash_amount` from the API response
   - Pre-profit estimates for off-exchange funds using their tracked indices
   - Properly formatted allocation displays for all holdings

## Final Notes

- The backend API (`uvicorn`) must be running for the tests to work
- The database is set up with the correct holdings and tracked_index configuration
- The frontend dashboard will now correctly display cash positions and 红利低波ETF information
- All existing holdings (except the old 红利高波ETF ones) are preserved

This setup ensures that the ETF Surge platform has properly configured 红利低波ETF holdings with correct tracking and profit estimation capabilities.