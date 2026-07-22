"""Probe: check akshare HK stock data for industry/sector info."""
import sys
sys.path.insert(0, ".")

import akshare as ak

print("=== akshare 港股全量字段 ===")
df = ak.stock_hk_spot_em()
print(f"列数: {len(df.columns)}")
print(f"列名: {list(df.columns)}")
print(f"行数: {len(df)}")
if len(df) > 0:
    for col in df.columns:
        val = df[col].iloc[0]
        print(f"  {col}: {val}")

print("\n=== stock_hk_industry_ci ===")
try:
    df2 = ak.stock_hk_industry_ci()
    print(f"列数: {len(df2)}")
    print(f"列名: {list(df2.columns)}")
    if len(df2) > 0:
        print(df2.head(5).to_string())
except Exception as e:
    print(f"失败: {e}")

print("\n=== stock_hk_ggt_components_em ===")
try:
    df3 = ak.stock_hk_ggt_components_em()
    print(f"列数: {len(df3)}")
    print(f"列名: {list(df3.columns)}")
    if len(df3) > 0:
        for col in df3.columns:
            print(f"  {col}: {df3[col].iloc[0]}")
except Exception as e:
    print(f"失败: {e}")
