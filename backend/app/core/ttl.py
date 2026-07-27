"""统一 TTL 配置。

所有缓存生存时间集中定义在此文件，模块间共享同一来源，
避免散落在各 fetcher/service 中的零散 _TTL / _QUOTE_TTL 产生不一致。
"""

CACHE_TTL = {
    # ── 实时行情 (秒) ───────────────────────────────────────────
    "quote_a": 5,           # A 股实时行情
    "quote_hk": 10,         # 港股实时行情
    "quote_us": 15,         # 美股实时行情
    "quote_index": 3,       # 指数实时点位
    "quote_futures": 10,    # 期货实时行情

    # ── 资讯 ────────────────────────────────────────────────────
    "news_headlines": 60,   # 头条快讯
    "news_macro": 60,       # 宏观资讯
    "news_global": 60,      # 国际资讯
    "news_stock": 60,       # 个股资讯
    "news_telegraph": 60,   # 财联社快讯
    "news_emotion": 60,      # 市场情绪
    "news_wind": 120,        # 市场风向

    # ── 板块 ────────────────────────────────────────────────────
    "sector_industry": 60,    # 行业板块行情
    "sector_concept": 60,    # 概念板块行情
    "sector_stocks": 60,     # 板块成分股
    "sector_history": 120,   # 板块历史数据
    "sector_hot_plates": 60, # 热门板块
    "sector_heat": 120,      # 板块热度
    "sector_popular": 60,    # 板块人气股

    # ── 元数据 (长 TTL) ─────────────────────────────────────────
    "etf_list": 3600,        # ETF 全量列表
    "instrument_list": 3600, # 全量证券列表
    "nav": 3600,             # 基金净值（一天更新一次即可）
    "all_stocks": 3600,      # 全量股票列表
}
