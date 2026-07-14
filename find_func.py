# -*- coding: utf-8 -*-
with open('E:/ETF_Surge/backend/app/services/portfolio_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the function and replace it
import re

# Use a more flexible pattern
pattern = r'def _build_price_map\(etfs: list\[PortfolioETF\]\) -> dict\[str, tuple\[float, float\]\]:[\s\S]*?a_symbols = \[e\.symbol for e in etfs if e\.asset_type == "A" and e\.symbol\[:1\] in \("1", "5", "6"\)\]\n\s*hk_symbols = \[e\.symbol for e in etfs if e\.asset_type == "HK"\]\n\s*us_symbols = \[e\.symbol for e in etfs if e\.asset_type == "US"\]'

match = re.search(pattern, content)
if match:
    print("FOUND at position", match.start())
    print(repr(content[match.start():match.start()+300]))
else:
    print("NOT FOUND with regex")
    # Try simpler search
    idx = content.find('def _build_price_map')
    if idx >= 0:
        print("Found def at", idx)
        print(repr(content[idx:idx+300]))