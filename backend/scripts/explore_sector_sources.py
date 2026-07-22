"""
快速调研：港股和美股行业分类数据的可用性。

检查现有代码库中可用的数据源：
1. akshare 的港股数据是否含行业信息
2. Finnhub API 能否提供行业分类
3. Stooq 是否有行业/板块信息
"""

# ── 1. akshare 港股全量数据字段探查 ──────────────────────────

def check_akshare_hk_fields():
    """检查 akshare stock_hk_spot_em 返回哪些字段"""
    import akshare as ak
    df = ak.stock_hk_spot_em()
    print("=== akshare 港股全量字段 ===")
    print(f"列数: {len(df.columns)}")
    print(f"列名: {list(df.columns)}")
    print(f"行数: {len(df)}")
    # 样本
    if len(df) > 0:
        print(f"\n第一行:\n{df.iloc[0].to_dict()}")
    return df


def check_akshare_hk_industry():
    """检查 akshare 是否提供港股行业分类"""
    # 测试 stock_hk_ggt_components_em (港股通成分股)
    try:
        import akshare as ak
        df = ak.stock_hk_ggt_components_em()
        print("\n=== 港股通成分股字段 ===")
        print(f"列名: {list(df.columns)}")
        if len(df) > 0:
            print(f"第一行: {df.iloc[0].to_dict()}")
    except Exception as e:
        print(f"\nstock_hk_ggt_components_em 失败: {e}")

    # 测试 stock_hk_fh_temp (港股分类)
    try:
        df = ak.stock_hk_industry_ci()
        print("\n=== 港股行业分类 (stock_hk_industry_ci) ===")
        print(f"列名: {list(df.columns)}")
        if len(df) > 0:
            print(f"前3行: {df.head(3).to_dict()}")
    except Exception as e:
        print(f"\nstock_hk_industry_ci 失败: {e}")


# ── 2. Finnhub API 行业分类探查 ─────────────────────────────

def check_finnhub_sector():
    """检查 Finnhub 是否提供行业分类"""
    from backend.app.config import settings
    import urllib.request
    import json

    key = settings.finnhub_api_key
    if not key or key.startswith("your_"):
        print("\n=== Finnhub: 无 API key，跳过 ===")
        return

    # Finnhub stock profile2 包含行业信息
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol=AAPL&token={key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"\n=== Finnhub stock/profile2 (AAPL) ===")
        print(f"字段: {list(data.keys()) if data else 'empty'}")
        if data:
            print(f"finnhubIndustry: {data.get('finnhubIndustry')}")
            print(f"sector: {data.get('sector')}")
    except Exception as e:
        print(f"\nFinnhub profile2 失败: {e}")

    # Finnhub 也有 /stock/symbol?exchange=US 返回全量股票列表含行业
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"\n=== Finnhub stock/symbol (US) ===")
        if data and len(data) > 0:
            print(f"总数: {len(data)}")
            print(f"第一行字段: {list(data[0].keys())}")
            print(f"第一行: {data[0]}")
    except Exception as e:
        print(f"\nFinnhub stock/symbol 失败: {e}")

    # 检查 Finnhub 是否有 aggregation by sector
    try:
        url = f"https://finnhub.io/api/v1/sector-performance?token={key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"\n=== Finnhub sector-performance ===")
        print(f"数据: {data[:10] if data else 'empty'}")
    except Exception as e:
        print(f"\nFinnhub sector-performance 失败: {e}")


# ── 3. 港股现有数据中的交易所行业 ──────────────────────────

def check_existing_hk_data():
    """检查 china_market 中港股行情是否包含行业信息"""
    from backend.app.fetchers.china_market import fetch_hk_stock_realtime
    
    items = fetch_hk_stock_realtime("00700")
    print(f"\n=== 现有港股行情 (00700) ===")
    print(f"返回: {items}")

    # 查看 akshare 港股数据结构
    import akshare as ak
    df = ak.stock_hk_spot_em()
    if df is not None and not df.empty:
        print(f"\n=== ak.stock_hk_spot_em 全部列 ===")
        for col in df.columns:
            print(f"  {col}: {df[col].iloc[0]}")


# ── 4. 替代方案：通过 ETF 名称关键词推断板块 ────────────────

def check_etf_naming_patterns():
    """检查美股和港股 ETF 的名称模式，看能否通过名称推断类别"""
    # 美股行业 ETF 列表
    us_sector_etfs = {
        "XLK": "科技",
        "XLF": "金融",
        "XLV": "医疗保健",
        "XLI": "工业",
        "XLE": "能源",
        "XLB": "材料",
        "XLRE": "房地产",
        "XLC": "通信服务",
        "XLU": "公用事业",
        "XLY": "非必需消费",
        "XLP": "必需消费",
        "SMH": "半导体",
        "IBB": "生物科技",
        "ARKK": "创新科技",
        "KRE": "区域银行",
        "KBE": "银行",
        "OIH": "油田服务",
        "XOP": "油气勘探",
        "GDX": "黄金矿业",
        "GDXJ": "小型金矿",
        "TAN": "太阳能",
        "ICLN": "清洁能源",
        "LIT": "锂电池",
        "BOTZ": "机器人",
        "ROBO": "机器人",
        "ARKQ": "自动驾驶",
        "ARKW": "下一代互联网",
        "ARKG": "基因组学",
        "ARKF": "金融科技",
    }
    print(f"\n=== 美股行业 ETF (可直接追踪) ===")
    print(f"共 {len(us_sector_etfs)} 只")

    # 港股行业/板块 ETF
    hk_sector_etfs = {
        "2800": "恒指追踪",
        "2828": "恒生中国企业",
        "3032": "恒生科技",
        "3067": "恒生科技指数",
        "2833": "恒生指数",
        "2823": "A50",
        "3049": "沪深300",
        "2822": "富时A50",
        "2827": "标普中国A股",
        "2836": "印度ETF",
        "2840": "SPDR金ETF",
        "3076": "富时中国",
        "3165": "恒生ESG",
        "3188": "华夏沪深300",
    }
    print(f"\n=== 港股主题 ETF (少量分类) ===")
    print(f"共 {len(hk_sector_etfs)} 只")


if __name__ == "__main__":
    print("=" * 60)
    print("ETF Surge — 板块数据源调研")
    print("=" * 60)

    # check_akshare_hk_fields()
    # check_akshare_hk_industry()
    # check_finnhub_sector()
    # check_existing_hk_data()
    check_etf_naming_patterns()
