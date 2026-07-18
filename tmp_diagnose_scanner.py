#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import akshare as ak
from app.utils.decode import decode_df
from app.fetchers.etf_scanner import _get_col

# 1. Fetch raw data
df = ak.fund_etf_spot_em()
print("=== 原始列名 ===")
for col in list(df.columns)[:8]:
    print(f"  key={repr(col):40s} hex={col.encode('utf-8').hex()}")

# 2. After decode_df
print("\n=== decode_df 后列名 ===")
decode_df(df)
for col in list(df.columns)[:8]:
    print(f"  key={repr(col):40s} hex={col.encode('utf-8').hex()}")

# 3. Check column name matching
print("\n=== 标准列名匹配测试 ===")
row = df.iloc[0].to_dict()
tests = ["代码", "名称", "最新价", "涨跌幅", "成交额", "基金规模", "换手率", "市盈率-动态", "市净率"]
for t in tests:
    v = row.get(t)
    if v is None:
        # Try _get_col
        v2 = _get_col(row, t)
        print(f"  {t}: direct=None  _get_col={v2}")
    else:
        print(f"  {t}: {v}")

# 4. Test filter_etfs
print("\n=== filter_etfs 测试 ===")
from app.fetchers.etf_scanner import filter_etfs
raw_list = df.to_dict(orient="records")
filtered = filter_etfs(raw_list)
print(f"raw={len(raw_list)} filtered={len(filtered)}")

# 5. Show first filtered item if any
if filtered:
    print("\n=== 第一只过滤后的 ETF ===")
    for k, v in filtered[0].items():
        print(f"  {k}: {v}")
else:
    print("\n=== 诊断：是谁导致了过滤？===")
    sample = raw_list[0]
    code = sample.get("代码", "N/A")
    amount = _get_col(sample, *["成交额", "amount", "成交金额", "成交额(元)"])
    scale = _get_col(sample, *["基金规模", "fund_scale", "规模", "最新基金规模"])
    print(f"  第一只 ETF code={code} amount={amount} scale={scale}")
    # Find first ETF that WOULD pass
    for i, row_item in enumerate(raw_list[:50]):
        amt = _get_col(row_item, *["成交额", "amount", "成交金额", "成交额(元)"])
        scl = _get_col(row_item, *["基金规模", "fund_scale", "规模", "最新基金规模"])
        name = str(row_item.get("名称", ""))
        if amt >= 10000000 and scl >= 1.0:
            print(f"  [{i}] code={row_item.get('代码')} name={name} amount={amt} scale={scl}")
            break
    else:
        print("  前50只ETF没有一只通过 amount+scale 过滤")
        for i, row_item in enumerate(raw_list[:3]):
            amt = _get_col(row_item, *["成交额", "amount", "成交金额", "成交额(元)"])
            scl = _get_col(row_item, *["基金规模", "fund_scale", "规模", "最新基金规模"])
            print(f"  [{i}] amount={amt} scale={scl}")
