"""
TDD: Text pipeline path A - keyword-driven macro/policy/geopolitical factors.

All external calls (news_fetcher, levistock) must be mocked.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestKeywordPolicyFactors:
    """关键词驱动宏观政策因子"""

    @pytest.fixture
    def pipeline(self):
        from app.analysis.text_pipeline import TextPipeline
        return TextPipeline()

    def test_easing_score_detected(self, pipeline):
        """新闻含"降准""降息"等宽松关键词应提高宽松分"""
        headlines = [
            "央行宣布全面降准0.5个百分点",
            "国务院常务会议部署稳增长措施",
        ]
        score = pipeline.compute_policy_score(headlines)
        assert score > 0.5  # 宽松信号明显

    def test_tightening_score_detected(self, pipeline):
        """新闻含"加息""收紧"等收紧关键词应提高收紧分"""
        headlines = [
            "美联储暗示继续加息对抗通胀",
            "央行收紧流动性管理",
        ]
        tightening = pipeline.compute_tightening_score(headlines)
        assert tightening > 0.5

    def test_fed_hawkish_detected(self, pipeline):
        """美联储鹰派信号"""
        headlines = [
            "美联储主席鲍威尔：必要时将继续大幅加息",
            "FOMC纪要显示多数官员支持进一步收紧",
        ]
        hawkish = pipeline.compute_fed_hawkish_score(headlines)
        dovish = pipeline.compute_fed_dovish_score(headlines)
        assert hawkish > dovish

    def test_fed_dovish_detected(self, pipeline):
        """美联储鸽派信号"""
        headlines = [
            "美联储官员：加息周期接近尾声",
            "鲍威尔暗示可能暂停加息",
        ]
        dovish = pipeline.compute_fed_dovish_score(headlines)
        hawkish = pipeline.compute_fed_hawkish_score(headlines)
        assert dovish >= hawkish

    def test_geopolitical_score(self, pipeline):
        """地缘风险关键词应提高地缘风险分"""
        headlines = [
            "突发：俄乌冲突升级，双方在边境集结军队",
            "美国宣布对俄罗斯实施新一轮制裁",
        ]
        score = pipeline.compute_geopolitical_score(headlines)
        assert score > 0.5

    def test_geopolitical_low_when_normal(self, pipeline):
        """正常新闻不应触发地缘风险评分"""
        headlines = [
            "A股三大指数集体收涨",
            "新能源板块持续走强",
            "央行开展逆回购操作",
        ]
        score = pipeline.compute_geopolitical_score(headlines)
        assert score < 0.3

    def test_empty_headlines(self, pipeline):
        """空新闻列表应返回中性值"""
        assert pipeline.compute_policy_score([]) == 0.5
        assert pipeline.compute_fed_hawkish_score([]) == 0.5
        assert pipeline.compute_geopolitical_score([]) == 0.5

    def test_crisis_flag_triggered(self, pipeline):
        """极端关键词触发黑天鹅标记"""
        headlines = [
            "紧急：全球股市崩盘，触发熔断机制",
            "多国宣布进入经济紧急状态",
        ]
        flag = pipeline.compute_crisis_flag(headlines)
        assert flag is True

    def test_crisis_flag_not_triggered(self, pipeline):
        """普通新闻不应触发黑天鹅标记"""
        headlines = [
            "市场震荡整理，成交量萎缩",
            "北向资金小幅流出",
        ]
        flag = pipeline.compute_crisis_flag(headlines)
        assert flag is False

    def test_data_surprise_positive(self, pipeline):
        """关键数据超预期"""
        headlines = [
            "中国3月PMI超预期回升至52.5",
            "美国非农数据大超市场预期",
        ]
        result = pipeline.compute_data_surprise_score(headlines)
        assert result["score"] > 0.5
        assert len(result["matched_keywords"]) > 0

    def test_compute_all(self, pipeline):
        """批量计算所有宏观信号应返回完整结构"""
        headlines = [
            "央行全面降准0.5个百分点",
            "美联储暗示暂停加息",
        ]
        result = pipeline.compute_all(headlines)
        expected_keys = {
            "policy_easing", "policy_tightening",
            "fed_hawkish", "fed_dovish",
            "geopolitical_score", "crisis_flag",
            "data_surprise",
        }
        assert set(result.keys()) == expected_keys
