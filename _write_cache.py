"""Write user's closing data to indices_cache.json."""
import json, time

data = {
    "ts": time.time(),
    "data": {
        "A股": [
            {"symbol": "000001", "name": "上证指数", "region": "A股", "asset_type": "index", "price": 3867.03, "change_pct": 0.07, "change_amount": 2.67, "available": False},
            {"symbol": "399001", "name": "深证成指", "region": "A股", "asset_type": "index", "price": 14061.44, "change_pct": -1.42, "change_amount": -202.85, "available": False},
            {"symbol": "399006", "name": "创业板指", "region": "A股", "asset_type": "index", "price": 3566.73, "change_pct": -3.23, "change_amount": -119.24, "available": False},
            {"symbol": "000300", "name": "沪深300", "region": "A股", "asset_type": "index", "price": 4717.24, "change_pct": -0.46, "change_amount": -21.99, "available": False},
            {"symbol": "000688", "name": "科创50", "region": "A股", "asset_type": "index", "price": 1860.08, "change_pct": -2.26, "change_amount": -43.08, "available": False},
        ],
        "港股": [
            {"symbol": "^HSI", "name": "恒生指数", "region": "港股", "asset_type": "index", "price": 24892.66, "change_pct": -0.95, "change_amount": -239.63, "available": False},
            {"symbol": "^HSCE", "name": "恒生国企指数", "region": "港股", "asset_type": "index", "price": 8251.07, "change_pct": -1.31, "change_amount": -109.61, "available": False},
            {"symbol": "^HSTECH", "name": "恒生科技指数", "region": "港股", "asset_type": "index", "price": 4668.23, "change_pct": -3.04, "change_amount": -146.60, "available": False},
        ],
        "日韩": [
            {"symbol": "^N225", "name": "日经225", "region": "日韩", "asset_type": "index", "price": 66115.60, "change_pct": -0.18, "change_amount": -116.59, "available": False},
            {"symbol": "^KS11", "name": "韩国综合指数", "region": "日韩", "asset_type": "index", "price": 6797.70, "change_pct": 0.74, "change_amount": 49.83, "available": False},
        ],
        "欧美": [
            {"symbol": "^GSPC", "name": "标普500", "region": "欧美", "asset_type": "index", "price": 7509.20, "change_pct": 0.89, "change_amount": None, "available": False},
            {"symbol": "^IXIC", "name": "纳斯达克综合", "region": "欧美", "asset_type": "index", "price": 25837.21, "change_pct": 1.29, "change_amount": None, "available": False},
            {"symbol": "^DJI", "name": "道琼斯工业指数", "region": "欧美", "asset_type": "index", "price": 52224.64, "change_pct": 0.74, "change_amount": None, "available": False},
            {"symbol": "^FTSE", "name": "英国富时100", "region": "欧美", "asset_type": "index", "price": 10601.72, "change_pct": 0.16, "change_amount": 16.41, "available": False},
            {"symbol": "^STOXX50E", "name": "欧洲斯托克50", "region": "欧美", "asset_type": "index", "price": 4991.65, "change_pct": 0.83, "change_amount": 41.33, "available": False},
        ],
    },
}

path = "E:/ETF_Surge/backend/data/indices_cache.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"Written {path}")
print(f"Regions: {list(data['data'].keys())}")
print(f"Total entries: {sum(len(v) for v in data['data'].values())}")
