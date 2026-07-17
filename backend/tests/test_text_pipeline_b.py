"""
TDD: Text Pipeline Path B - LLM-powered news sentiment analysis.

Uses existing DeepSeek API (llm_complete_with_system) to classify
news headlines by sentiment, sector impact, and Fed/geopolitical relevance.

All LLM calls must be mocked.
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestNewsLLMAnalyzer:
    """LLM 驱动新闻情绪分析"""

    @pytest.fixture
    def analyzer(self):
        from app.analysis.text_pipeline_b import NewsLLMAnalyzer
        return NewsLLMAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_single_headline_returns_structure(self, analyzer):
        """单条新闻分析应返回标准结构"""
        result = analyzer._parse_response('{"sentiment": "positive", "score": 0.8, "sectors": ["科技", "半导体"], "reason": "半导体政策利好"}')
        assert result["sentiment"] == "positive"
        assert result["score"] == 0.8
        assert "半导体" in result["sectors"]

    def test_parse_response_valid_json(self, analyzer):
        """有效 JSON 应正确解析"""
        result = analyzer._parse_response('{"sentiment": "negative", "score": 0.2, "sectors": ["金融"], "reason": "监管收紧"}')
        assert result["sentiment"] == "negative"
        assert result["score"] == 0.2

    def test_parse_response_invalid_json(self, analyzer):
        """无效 JSON 应返回中性默认值"""
        result = analyzer._parse_response("not json at all")
        assert result["sentiment"] == "neutral"
        assert result["score"] == 0.5
        assert result["sectors"] == []

    def test_parse_response_empty(self, analyzer):
        """空字符串应返回中性默认值"""
        result = analyzer._parse_response("")
        assert result["sentiment"] == "neutral"
        assert result["score"] == 0.5

    @pytest.mark.asyncio
    async def test_batch_analyze(self, analyzer):
        """批量分析应返回 {idx: result} 结构"""
        headlines = [
            "央行宣布全面降准0.5个百分点，释放长期流动性",
            "美联储暗示可能继续加息以遏制通胀",
            "今日A股三大指数集体收涨",
        ]
        with patch.object(analyzer, '_call_llm', new=AsyncMock(return_value='{"sentiment": "positive", "score": 0.8, "sectors": ["金融"], "reason": "宽松政策"}')) as mock_llm:
            results = await analyzer.batch_analyze(headlines, max_workers=3)
            assert len(results) == 3
            assert all("sentiment" in r for r in results.values())
            assert all("score" in r for r in results.values())
            assert mock_llm.call_count == 3

    @pytest.mark.asyncio
    async def test_aggregate_sentiment_score(self, analyzer):
        """情绪聚合应输出综合得分"""
        results = {
            0: {"sentiment": "positive", "score": 0.8, "sectors": ["金融"], "reason": ""},
            1: {"sentiment": "negative", "score": 0.3, "sectors": ["科技"], "reason": ""},
            2: {"sentiment": "neutral", "score": 0.5, "sectors": [], "reason": ""},
        }
        agg = analyzer.aggregate(results)
        assert 0.4 <= agg["avg_score"] <= 0.6
        assert "positive_count" in agg
        assert "negative_count" in agg
        assert agg["total"] == 3

    @pytest.mark.asyncio
    async def test_empty_headlines(self, analyzer):
        """空列表应返回空结果"""
        results = await analyzer.batch_analyze([], max_workers=1)
        assert results == {}
        agg = analyzer.aggregate(results)
        assert agg["total"] == 0
        assert agg["avg_score"] == 0.5

    @pytest.mark.asyncio
    async def test_sentiment_macro_breakdown(self, analyzer):
        """应能区分宏观政策、行业、地缘三类情绪"""
        results = {
            0: {"sentiment": "positive", "score": 0.8, "sectors": ["金融"], "reason": "降准利好", "category": "policy"},
            1: {"sentiment": "negative", "score": 0.2, "sectors": ["半导体"], "reason": "制裁", "category": "geopolitical"},
        }
        breakdown = analyzer.breakdown_by_category(results)
        assert "policy" in breakdown
        assert "geopolitical" in breakdown
        assert breakdown["policy"]["avg_score"] > 0.5
        assert breakdown["geopolitical"]["avg_score"] < 0.5

    def test_build_prompt(self, analyzer):
        """构建的 prompt 应包含新闻标题"""
        prompt = analyzer._build_prompt("央行宣布全面降准")
        assert "央行宣布全面降准" in prompt
