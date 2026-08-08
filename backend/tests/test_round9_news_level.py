"""
round9 (docs/round9-container-rediagnosis.md §6.4) P2-1 资讯分级校准专项：

- stars 独立「新鲜度」维度（与 level 解耦）
- 弱化词降级（或将/可能/有望… 未实现事件不标 L5/L4）
"""

from datetime import datetime, timedelta

from app.fetchers.levistock_fetcher import classify_news_level
from app.fetchers.news_fetcher import _compute_stars


class TestStarsFreshnessDimension:
    def test_stars_follows_freshness_not_level(self):
        """P2-1: stars 按时间新鲜度（<1h 5★），与 level 解耦。"""
        now = datetime.now()
        assert _compute_stars(5, (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")) == 5
        assert _compute_stars(1, (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")) == 5
        assert _compute_stars(4, (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")) == 4
        assert _compute_stars(5, (now - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")) == 3
        assert _compute_stars(2, (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")) == 2
        assert _compute_stars(5, (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")) == 1

    def test_stars_parses_iso_and_slash_formats(self):
        """P2-1: stars 兼容 ISO/斜杠时间格式。"""
        now = datetime.now()
        iso = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        slash = (now - timedelta(hours=2)).strftime("%Y/%m/%d %H:%M:%S")
        assert _compute_stars(3, iso) == 4
        assert _compute_stars(3, slash) == 4

    def test_stars_unparseable_time_falls_back_to_level(self):
        """P2-1: 时间不可解析（如 "10:00" 无日期）回退 level，字段保持非空。"""
        assert _compute_stars(5, "10:00") == 5
        assert _compute_stars(2, "") == 2
        assert _compute_stars(4, None) == 4


class TestLevelWeakeningCalibration:
    def test_unrealized_events_downgraded(self):
        """P2-1: 弱化词（或将/有望/拟…）未实现事件不标重大/利好。"""
        assert classify_news_level("央行或将降准") == 3          # L4→L3
        assert classify_news_level("证监会拟放宽外资准入") == 3    # L4→L3
        assert classify_news_level("突发冲突或将升级") == 4        # L5→L4
        assert classify_news_level("财政部拟实施新一批减税政策") == 3  # L4→L3

    def test_confirmed_events_keep_level(self):
        """P2-1: 已实现事件保持原级别。"""
        assert classify_news_level("突发：地缘冲突升级") == 5
        assert classify_news_level("【重大】央行紧急降准") == 5
        assert classify_news_level("利好：某板块业绩超预期") == 4   # 「超预期」不被降级
        assert classify_news_level("央行宣布降准0.5个百分点") == 4

    def test_weakening_not_applied_below_level_4(self):
        """P2-1: 弱化规则只作用于 L5/L4，不把 L3/L2 再降。"""
        assert classify_news_level("利空：指数或继续下探") == 3    # 弱化词不影响 L3
        assert classify_news_level("下周资本市场大事提醒：或迎重磅IPO") == 2

    def test_level5_share_not_dominant_on_headline_mix(self):
        """P2-1 验收近似: 常规头条混合样本中 L5 不占 50%（分布合理性回归）。"""
        titles = [
            "央行或将降准",            # 3
            "某公司发布年报业绩",       # 2（发布→L2）
            "市场午后小幅拉升",        # 2
            "突发：地震已致多人受伤",   # 5
            "两家科技巨头宣布战略合作",  # 4
            "普通公司公告",            # 2
            "美国CPI数据公布",         # 2
            "台风登陆沿海地区",        # 5
        ]
        levels = [classify_news_level(t) for t in titles]
        l5 = sum(1 for l in levels if l == 5)
        l1 = sum(1 for l in levels if l == 1)
        assert l5 / len(levels) < 0.3, f"L5 占比 {l5}/{len(levels)} 应 <30%: {levels}"
        assert l1 >= 0, f"存在 L1: {levels}"
