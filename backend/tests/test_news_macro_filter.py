"""
O7 (docs/archived/round7-rediagnosis.md §7 P9): 资讯分级合理——国际重磅分级 + 宏观 tab 过滤。

P9 问题:
1. 国际重磅新闻（美联储/沙特阿美/BP/OPEC 等）全 level=1, stars=1——关键词表缺
   国际宏观重磅词（美联储/非农/OPEC/利率决议 等）。
2. 宏观 tab 混入个股/营销软文——宏观源（新浪滚动）未过滤非宏观内容。

修复:
1. _LEVEL_KEYWORDS 补国际重磅词（L4: 利率决议/非农/OPEC/美联储决议；L2: 原油/通胀/失业率）。
2. 宏观源增加个股/营销过滤（_is_macro_relevant 判定，不相关条目剔除）。
"""

import pytest

from app.fetchers import levistock_fetcher as lf
from app.fetchers import news_fetcher as nf


class TestInternationalLeveling:
    def test_fed_rate_decision_level4(self):
        """美联储利率决议 → L4（重磅宏观事件）。"""
        assert lf.classify_news_level("美联储公布利率决议，维持利率不变") >= 4
        assert lf.classify_news_level("美联储主席鲍威尔表示年内将降息") >= 2

    def test_nonfarm_payrolls_level4(self):
        """美国非农数据 → L4。"""
        assert lf.classify_news_level("美国6月非农就业数据超预期") >= 4

    def test_opec_oil_level4(self):
        """OPEC 会议/减产 → L4（能源市场重磅）。"""
        assert lf.classify_news_level("OPEC+宣布延长减产协议") >= 4

    def test_inflation_unemployment_level2(self):
        """通胀/失业率数据 → L2（重要数据但非紧急）。"""
        assert lf.classify_news_level("美国5月CPI同比上涨3.1%") >= 2
        assert lf.classify_news_level("初请失业金人数上升") >= 2


class TestMacroFilter:
    def test_macro_relevant_kept(self):
        """宏观/政策新闻 → 保留。"""
        assert nf._is_macro_relevant("央行开展5000亿元逆回购操作") is True
        assert nf._is_macro_relevant("国务院常务会议部署稳经济政策") is True
        assert nf._is_macro_relevant("美联储决议对全球市场的影响") is True

    def test_stock_news_filtered(self):
        """个股新闻（含 6 位代码/公司名+股价）→ 过滤。"""
        assert nf._is_macro_relevant("贵州茅台股价再创新高") is False
        assert nf._is_macro_relevant("600519涨停，主力资金净流入") is False
        assert nf._is_macro_relevant("某某公司发布半年报预告") is False

    def test_marketing_filtered(self):
        """营销软文 → 过滤。"""
        assert nf._is_macro_relevant("限时抢购！开户送好礼") is False
        assert nf._is_macro_relevant("下载APP领红包，新手专享") is False
