# -*- coding: utf-8 -*-
"""直接调 hk_hot_fetcher 函数定位个股 0 条"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.fetchers import hk_hot_fetcher as hk

rows = hk._fetch_hk_rows()
print("[_fetch_hk_rows] len:", len(rows))
stocks = hk.get_hk_hot_stocks(10)
print("[get_hk_hot_stocks(10)] len:", len(stocks))
if stocks:
    print("  样例:", json.dumps(stocks[0], ensure_ascii=False))
plates = hk.get_hk_hot_plates(10)
print("[get_hk_hot_plates(10)] len:", len(plates))

# 路由层验证
from app.services.market_data_hub import market_data_hub
rk = market_data_hub.get_stock_hot_rank(10, "HK")
print("[hub.get_stock_hot_rank(10,'HK')] len:", len(rk))
