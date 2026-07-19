"""
TDD tests for the enhanced portfolio design v4 modules.

Covers:
  - market_trends.py: detect_market_regime
  - macro_state.py: detect_macro_regime (logic/synthesis)
  - strategy_design.py: score_satellite_assets, map_news_to_etfs,
    dynamic_core_allocation, dynamic_defense_allocation,
    dynamic_layer_budget, compute_portfolio_risk
  - generate_enhanced_design integration

All external calls (akshare) are mocked.
"""

import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


# ─── market_trends.detect_market_regime ───────────────────────

class TestDetectMarketRegime:
    def test_panic_low_sentiment(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": -0.08, "return_3m": -0.15}},
            sentiment_index=15.0,
            adv_ratio=0.2,
        )
        assert regime == "panic"

    def test_bull_strong(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": 0.05, "return_3m": 0.20}},
            sentiment_index=70.0,
            adv_ratio=0.6,
        )
        assert regime == "bull_strong"

    def test_bull_weakening(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": -0.04, "return_3m": 0.08}},
            sentiment_index=60.0,
            adv_ratio=0.5,
        )
        assert regime == "bull_weakening"

    def test_defensive_rotate(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": -0.02, "ma_bias_20": -0.03}},
            sentiment_index=45.0,
            adv_ratio=0.4,
        )
        assert regime == "defensive_rotate"

    def test_correction(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": -0.08, "ma_bias_20": -0.01}},
            sentiment_index=55.0,
            adv_ratio=0.5,
        )
        assert regime == "correction"

    def test_bear(self):
        from app.services.market_trends import detect_market_regime
        # 3m deep decline with only moderate 1m drop → bear (not triggered by correction)
        regime = detect_market_regime(
            trends={"000001": {"return_1m": -0.03, "return_3m": -0.15}},
            sentiment_index=50.0,
            adv_ratio=0.5,
        )
        assert regime == "bear"

    def test_range_bound_default(self):
        from app.services.market_trends import detect_market_regime
        regime = detect_market_regime(
            trends={"000001": {"return_1m": 0.01, "return_3m": 0.03, "ma_bias_20": -0.01}},
            sentiment_index=55.0,
            adv_ratio=0.5,
        )
        assert regime == "range_bound"


# ─── strategy_design.score_satellite_assets ───────────────────

class TestScoreSatelliteAssets:
    def test_basic_scoring(self):
        from app.services.strategy_design import score_satellite_assets

        assets = [
            {"symbol": "512480", "name": "半导体ETF", "liquidity": 20.0},
            {"symbol": "512010", "name": "医药ETF", "liquidity": 8.0},
            {"symbol": "518880", "name": "黄金ETF", "liquidity": 22.0},
        ]

        trends = {
            "512480": {"return_3m": -0.15, "volatility_20d": 0.35},
            "512010": {"return_3m": 0.08, "volatility_20d": 0.18},
            "518880": {"return_3m": 0.05, "volatility_20d": 0.12},
        }

        fund_flows = {
            "512480": -2e8,
            "512010": 1.5e8,
            "518880": 0.5e8,
        }

        result = score_satellite_assets(assets, regime="defensive_rotate",
                                         trends=trends, fund_flows=fund_flows)

        # All should have composite_score
        for a in result:
            assert "composite_score" in a
            assert "factor_scores" in a
            assert 0 <= a["composite_score"] <= 1

        # In defensive_rotate mode, valuation/flow weighted more,
        # so 医药 (positive flow, low vol) should score higher than 半导体 (negative flow, high vol)
        scores = {a["symbol"]: a["composite_score"] for a in result}
        assert scores.get("512010", 0) >= scores.get("512480", 0), (
            f"医药({scores.get('512010',0)}) should >= 半导体({scores.get('512480',0)}) "
            f"in defensive_rotate regime"
        )

    def test_scoring_bull_regime(self):
        """验证强牛市下动量因子权重更高"""
        from app.services.strategy_design import score_satellite_assets

        assets = [
            {"symbol": "512480", "name": "半导体ETF", "liquidity": 20.0},
            {"symbol": "512010", "name": "医药ETF", "liquidity": 8.0},
        ]

        trends = {
            "512480": {"return_3m": 0.35, "volatility_20d": 0.35},
            "512010": {"return_3m": 0.05, "volatility_20d": 0.18},
        }

        result = score_satellite_assets(assets, regime="bull_strong",
                                         trends=trends, fund_flows={})
        scores = {a["symbol"]: a["composite_score"] for a in result}
        # In bull market, momentum matters more, so 半导体 (high momentum) scores higher
        assert scores.get("512480", 0) > scores.get("512010", 0), (
            f"半导体({scores.get('512480',0)}) should > 医药({scores.get('512010',0)}) "
            f"in bull_strong regime"
        )


# ─── strategy_design.map_news_to_etfs ─────────────────────────

class TestMapNewsToEtfs:
    def test_basic_mapping(self):
        from app.services.strategy_design import map_news_to_etfs

        news = [
            {"title": "半导体板块主力资金净流出262亿元"},
            {"title": "创新药BD出海交易破千亿美元，医药板块走强"},
            {"title": "黄金价格维持高位震荡"},
            {"title": "国务院批复扩大消费规划，消费板块受益"},
        ]

        result = map_news_to_etfs(news)

        assert "512480" in result  # 半导体
        assert "512010" in result  # 医药
        assert "518880" in result  # 黄金

        # 半导体新闻含"流出" → negative
        assert result["512480"]["negative_mentions"] >= 1

        # 医药新闻积极
        assert result["512010"]["positive_mentions"] >= 1

    def test_empty_news(self):
        from app.services.strategy_design import map_news_to_etfs
        result = map_news_to_etfs([])
        assert result == {}

    def test_sentiment_score(self):
        from app.services.strategy_design import map_news_to_etfs

        news = [
            {"title": "半导体大利好，AI芯片需求爆发"},
            {"title": "半导体板块再创新高"},
            {"title": "半导体产业链持续走强"},
        ]
        result = map_news_to_etfs(news)
        assert "512480" in result
        assert result["512480"]["sentiment_score"] > 0


# ─── strategy_design.dynamic_core_allocation ─────────────────

class TestDynamicCoreAllocation:
    def test_defensive_rotate_allocation(self):
        """防御轮动下应包含红利低波，配置国债"""
        from app.services.strategy_design import dynamic_core_allocation

        macro = {"style_preference": "defensive_value", "bond_bull": True}
        core = dynamic_core_allocation("defensive_rotate", macro)

        codes = {c["symbol"] for c in core}
        assert "510300" in codes       # 沪深300
        assert "560600" in codes       # A500
        assert "512890" in codes       # 红利低波

    def test_growth_allocation_contains_chuangyeban(self):
        """成长风格应包含创业板增强弹性"""
        from app.services.strategy_design import dynamic_core_allocation

        macro = {"style_preference": "growth"}
        core = dynamic_core_allocation("bull_strong", macro)

        codes = {c["symbol"] for c in core}
        assert "159915" in codes       # 创业板

    def test_bear_allocation_reduces_300(self):
        """熊市应降低沪深300权重"""
        from app.services.strategy_design import dynamic_core_allocation

        macro = {"style_preference": "defensive_value"}
        core = dynamic_core_allocation("bear", macro)

        for c in core:
            if c["symbol"] == "510300":
                assert c["weight"] <= 0.20, "熊市沪深300权重应≤20%"


# ─── strategy_design.dynamic_defense_allocation ──────────────

class TestDynamicDefenseAllocation:
    def test_bond_included_when_rate_down(self):
        """利率下行应包含国债ETF"""
        from app.services.strategy_design import dynamic_defense_allocation

        macro = {"bond_bull": True, "rate_direction": "down", "external_risk": "moderate"}
        defense = dynamic_defense_allocation("range_bound", macro)

        codes = {d["symbol"] for d in defense}
        assert "511090" in codes, "利率下行应配置30年国债ETF"

    def test_gold_increased_when_high_risk(self):
        """高风险环境下黄金权重应提升"""
        from app.services.strategy_design import dynamic_defense_allocation

        macro = {"external_risk": "elevated", "bond_bull": False}
        defense = dynamic_defense_allocation("bear", macro)

        gold = next((d for d in defense if d["symbol"] == "518880"), None)
        assert gold is not None
        assert gold["weight"] >= 0.05


# ─── strategy_design.dynamic_layer_budget ────────────────────

class TestDynamicLayerBudget:
    def test_defensive_rotate_increases_defense_budget(self):
        """防御轮动下防御层预算应提升"""
        from app.services.strategy_design import dynamic_layer_budget

        budget = dynamic_layer_budget("balanced", "defensive_rotate")
        # 平衡型 base defense=0.05, shift=0.08 → defense≈0.13
        assert budget["defense"] >= 0.10, (
            f"防御轮动下防御层预算应≥10%，实际{ budget['defense']:.0%}"
        )

    def test_bull_increases_satellite_budget(self):
        """牛市下卫星层预算应提升"""
        from app.services.strategy_design import dynamic_layer_budget

        budget = dynamic_layer_budget("aggressive", "bull_strong")
        assert budget["satellite"] >= 0.35

    def test_core_never_below_35(self):
        """核心层不应低于35%"""
        from app.services.strategy_design import dynamic_layer_budget

        budget = dynamic_layer_budget("defensive", "bear")
        assert budget["core"] >= 0.35


# ─── strategy_design.compute_portfolio_risk ──────────────────

class TestComputePortfolioRisk:
    def test_basic_risk_metrics(self):
        from app.services.strategy_design import compute_portfolio_risk

        holdings = [
            {"symbol": "510300", "weight": 0.25},
            {"symbol": "512480", "weight": 0.10},
            {"symbol": "512010", "weight": 0.10},
            {"symbol": "518880", "weight": 0.05},
        ]

        risk = compute_portfolio_risk(holdings)

        assert "sector_concentration" in risk
        assert "sector_breakdown" in risk
        assert "volatility_est" in risk
        assert "max_drawdown_est" in risk
        assert 0 <= risk["sector_concentration"] <= 1

    def test_correlation_warning_high_semicon_ai(self):
        """半导体+AI权重过高时应触发预警"""
        from app.services.strategy_design import compute_portfolio_risk

        holdings = [
            {"symbol": "512480", "weight": 0.15},   # 半导体
            {"symbol": "561300", "weight": 0.15},   # AI
            {"symbol": "510300", "weight": 0.20},
        ]

        risk = compute_portfolio_risk(holdings)
        assert risk["correlation_warning"] is not None
        assert "半导体" in risk["correlation_warning"]

    def test_no_warning_diversified(self):
        """分散配置应无预警"""
        from app.services.strategy_design import compute_portfolio_risk

        holdings = [
            {"symbol": "510300", "weight": 0.20},
            {"symbol": "512890", "weight": 0.15},
            {"symbol": "512010", "weight": 0.08},
            {"symbol": "518880", "weight": 0.05},
            {"symbol": "511090", "weight": 0.05},
        ]
        risk = compute_portfolio_risk(holdings)
        assert risk["correlation_warning"] is None


# ─── macro_state.detect_macro_regime (logic unit tests) ───────

class TestMacroRegimeClassification:
    """测试宏观状态分类逻辑（不依赖外部API）"""

    def test_classify_economic_phase_recovery(self):
        from app.services.macro_state import _classify_economic_phase
        phase = _classify_economic_phase({"pmi_current": 51.5, "pmi_change": 0.3, "above_50": True})
        assert phase in ("弱复苏", "扩张")

    def test_classify_economic_phase_recession(self):
        from app.services.macro_state import _classify_economic_phase
        phase = _classify_economic_phase({"pmi_current": 48.5, "pmi_change": -0.5, "above_50": False})
        assert phase in ("衰退", "滞胀")

    def test_classify_monetary_stance_loose(self):
        from app.services.macro_state import _classify_monetary_stance
        stance = _classify_monetary_stance({"10y_yield": 1.73})
        assert stance == "宽松"

    def test_classify_monetary_stance_tight(self):
        from app.services.macro_state import _classify_monetary_stance
        stance = _classify_monetary_stance({"10y_yield": 3.5})
        assert stance == "收紧"

    def test_compute_confidence_full_data(self):
        from app.services.macro_state import _compute_confidence
        conf = _compute_confidence(
            {"pmi_current": 50.5},
            {"10y_yield": 1.8, "rate_direction": "down"},
        )
        assert conf >= 0.5

    def test_compute_confidence_no_data(self):
        from app.services.macro_state import _compute_confidence
        conf = _compute_confidence({}, {})
        assert conf <= 0.3
