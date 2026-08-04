"""F4 (round6 §14.6): 卫星层非科技主题配额——scanner 卫星分类补
医药/消费/金融/红利/新能源保底代表，防止卫星池被科创系包场。

现象（14.1）：卫星层除红利低波外全部是科创主题；根因 1——卫星候选池
构成偏科技（纯规模排序 TOP25 被科创 ETF 占满）。

本测试驱动 etf_scanner.full_pipeline 增加非科技主题配额注入：
mock 全市场扫描结果（科技 ETF 规模远超非科技），断言 satellite 层
TOP 结果仍包含医药/消费/金融/红利/新能源各至少 1 只代表。
"""
from app.fetchers import etf_scanner
from app.fetchers.etf_scanner import full_pipeline

# 非科技主题关键词（与 F4 规格 §14.6 一致：医药/消费/金融/红利/新能源）
NON_TECH_THEMES = {
    "医药": ("医药", "医疗", "创新药"),
    "消费": ("消费", "食品饮料", "白酒"),
    "金融": ("金融", "银行", "券商", "证券"),
    "红利": ("红利", "股息"),
    "新能源": ("新能源", "光伏", "电池", "锂电"),
}


def _mk_etf(code: str, name: str, scale: float) -> dict:
    return {"代码": code, "名称": name, "最新价": 1.0, "涨跌幅": 0.0,
            "成交额": scale * 0.1, "成交量": 1000, "换手率": 0.5,
            "流通市值": scale, "总市值": scale}


def _mk_tech_set() -> list[dict]:
    """科创系 ETF 集合：规模远大于非科技主题，数量 > top_n(25)，
    纯规模排序 TOP25 必然把非科技主题全部挤出。"""
    themes = ['50', '100', '芯片', '半导体', 'AI', '医药', '新能源', '材料', '信息', '成长',
              '信息', '数据', '软件', '计算机', '电子', '通信', '5G', '机器人', '智能制造', '云计算',
              '大数据', '物联网', '网络安全', '数字', '科技', '半导体设备', '芯片设计', '人工智能', '信息技术', '电子元件']
    return [_mk_etf(f"5881{i:02d}", f"科创{themes[i % len(themes)]}ETF", 2e9 - i * 1e7)
            for i in range(30)]


def _mk_non_tech_set() -> list[dict]:
    return [
        _mk_etf("512010", "医药ETF", 8e8),
        _mk_etf("159928", "消费ETF", 7e8),
        _mk_etf("512800", "银行ETF", 9e8),
        _mk_etf("510880", "红利ETF", 6e8),
        _mk_etf("516160", "新能源ETF", 5e8),
    ]


class TestSatelliteThemeQuota:
    def test_satellite_pool_keeps_non_tech_theme_reps(self, monkeypatch):
        """F4: 科技 ETF 规模霸榜时，卫星层仍保留 5 个非科技主题各 ≥1 只。"""
        raw = _mk_tech_set() + _mk_non_tech_set()
        monkeypatch.setattr("app.fetchers.etf_scanner.fetch_all_etfs_base", lambda: raw)

        layers = full_pipeline()
        sat_names = [e.get("name", "") for e in layers["satellite"]]
        sat_text = "；".join(sat_names)

        for theme, kws in NON_TECH_THEMES.items():
            hit = any(any(k in n for k in kws) for n in sat_names)
            assert hit, f"卫星层缺少主题 {theme} 的代表（仅含: {sat_text[:200]}）"

    def test_theme_quota_picks_largest_representative(self, monkeypatch):
        """F4: 同一主题多只候选时，配额注入应取规模最大者（非随机/非最小）。"""
        raw = _mk_tech_set() + [
            _mk_etf("512010", "医药ETF", 8e8),
            _mk_etf("159938", "医药卫生ETF", 2e8),   # 同主题较小
        ]
        monkeypatch.setattr("app.fetchers.etf_scanner.fetch_all_etfs_base", lambda: raw)

        layers = full_pipeline()
        med = [e.get("name", "") for e in layers["satellite"]
               if any(k in e.get("name", "") for k in NON_TECH_THEMES["医药"])]
        assert med, "医药主题代表缺失"
        assert any("医药ETF" == n or n == "医药ETF" for n in med), \
            f"应保留规模最大的医药ETF, got {med}"

    def test_quota_does_not_duplicate_existing_theme_reps(self, monkeypatch):
        """F4: 主题代表已在 TOP 内时，配额注入不得重复添加（幂等）。"""
        raw = _mk_tech_set() + [
            _mk_etf("512010", "医药ETF", 8e8),
            _mk_etf("512800", "银行ETF", 9e8),
        ]
        monkeypatch.setattr("app.fetchers.etf_scanner.fetch_all_etfs_base", lambda: raw)

        layers = full_pipeline()
        syms = [e.get("symbol") for e in layers["satellite"]]
        assert len(syms) == len(set(syms)), f"卫星层出现重复标的: {syms}"
        assert "512010" in syms and "512800" in syms
