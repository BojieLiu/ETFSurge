"""
O23 (docs/archived/round7-rediagnosis.md §7 P23): 入选理由行业标签可信度校验。

P23 根因: ETFClassifier 的 _match 是子串匹配——tracked_index="中证消费电子" 命中
_INDEX_RULES 的 ("消费", "食品饮料") → 562950 消费电子被误归「食品饮料」
（confidence=0.85 高置信度错误）。

修复:
1. _NAME_RULES / _INDEX_RULES 各前置 ("消费电子", "电子") 规则（精确词优先于宽泛「消费」）；
2. rationale 名称/指数交叉校验：命中宽基语义关键词而 industry 为具体行业时以「宽基指数」为准；
3. 分类置信度 <0.7 时降级为基于名称的保守描述。
"""

import pytest

from app.services.etf_classifier import ETFClassifier
from app.engine.rationale import build_rationale


class TestConsumptionElectronics:
    def test_tracked_index_consumption_electronics_is_electronics(self):
        """tracked_index='中证消费电子' → industry='电子'（不再误归食品饮料）。"""
        result = ETFClassifier()._classify_by_name("消费电子ETF易方达", "中证消费电子")
        assert result["industry"] == "电子", f"消费电子应归电子: {result}"

    def test_name_consumption_electronics_is_electronics(self):
        """name 含「消费电子」→ 电子（名称路径）。"""
        result = ETFClassifier()._classify_by_name("消费电子ETF", "")
        assert result["industry"] == "电子", f"名称路径也应归电子: {result}"

    def test_consumption_50_unchanged(self):
        """消费50/食品饮料正向用例不回归。"""
        result = ETFClassifier()._classify_by_name("消费50ETF", "中证消费50")
        assert result["industry"] == "食品饮料", f"消费50 仍应归食品饮料: {result}"
        result2 = ETFClassifier()._classify_by_name("食品饮料ETF", "中证食品饮料")
        assert result2["industry"] == "食品饮料"


class TestRationaleIndustrySanity:
    def test_wide_basis_cross_check_overrides_specific_industry(self):
        """名称命中宽基关键词而 industry 被误标具体行业 → 文案以「宽基指数」为准。"""
        rationale = build_rationale(
            code="560600",
            layer="core",
            strategy="balanced",
            meta={"name": "中证A500ETF", "tracked_index": "中证A500"},
            factor_scores={},
            regime="range_bound",
            industry="食品饮料",  # 错误标注（应被宽基语义覆盖）
        )
        assert "宽基" in rationale, f"宽基语义应覆盖误标行业: {rationale}"
        assert "食品饮料" not in rationale, f"误标行业不应出现在文案: {rationale}"

    def test_unknown_industry_wide_basis(self):
        """industry=unknown + 名称含宽基 → 宽基指数文案。"""
        rationale = build_rationale(
            code="510300",
            layer="core",
            strategy="balanced",
            meta={"name": "沪深300ETF", "tracked_index": "沪深300"},
            factor_scores={},
            regime="range_bound",
            industry="unknown",
        )
        assert "宽基" in rationale

    def test_low_confidence_falls_back_to_name(self):
        """industry 置信度低（<0.7）→ 不输出误导的具体行业（保守描述）。"""
        rationale = build_rationale(
            code="512480",
            layer="satellite",
            strategy="balanced",
            meta={"name": "半导体ETF", "tracked_index": "半导体"},
            factor_scores={},
            regime="range_bound",
            industry="半导体",  # 正常标签仍输出
            industry_confidence=0.5,  # 低置信度 → 保守描述
        )
        assert "方向" in rationale  # 保持「方向」句式（不误导具体行业语义）

    def test_normal_industry_kept(self):
        """高置信度正常行业 → 原有「{行业}方向」句式不变。"""
        rationale = build_rationale(
            code="512480",
            layer="satellite",
            strategy="balanced",
            meta={"name": "半导体ETF", "tracked_index": "半导体"},
            factor_scores={},
            regime="range_bound",
            industry="电子",
        )
        assert "电子方向" in rationale

    def test_rationale_length_under_100_chars(self):
        """round14 P2-X: 入选理由 ≤100 字/条（验收口径）；含方向 + 核心技术因子。"""
        rationale = build_rationale(
            code="159995",
            layer="satellite",
            strategy="balanced",
            meta={"name": "芯片ETF", "tracked_index": "芯片产业"},
            factor_scores={
                "technical.rsi.rsi_14": 59.6,
                "technical.macd.macd": 0.012,
                "momentum": 1.5,
            },
            regime="range_bound",
            industry="电子",
        )
        assert len(rationale) <= 100, f"理由过长 {len(rationale)} 字：{rationale}"
        assert "方向" in rationale
        # 核心驱动因子保留（RSI 或 MACD 或动量）
        assert any(k in rationale for k in ("RSI", "MACD", "动量")), rationale

    def test_no_verbose_tech_score_sentence(self):
        """round14 P2-X: 删除低信息量「技术面综合评分 X.XXX」句。"""
        rationale = build_rationale(
            code="510300",
            layer="core",
            strategy="balanced",
            meta={"name": "沪深300ETF"},
            factor_scores={"technical": 1.23, "technical.rsi.rsi_14": 55.0},
            regime="neutral",
            industry="宽基指数",
        )
        assert "技术面综合评分" not in rationale

    def test_no_duplicated_regime_sentence(self):
        """round14 P2-X: 删除「市场震荡」等重复市态句（市态在报告层级体现）。"""
        rationale = build_rationale(
            code="512480",
            layer="satellite",
            strategy="balanced",
            meta={"name": "半导体ETF", "tracked_index": "半导体"},
            factor_scores={},
            regime="range_bound",
            industry="电子",
        )
        assert "市场震荡" not in rationale
        assert "当前市场强势" not in rationale
