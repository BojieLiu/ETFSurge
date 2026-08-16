"""round25 R28: 综合信号前后端双断修复——holdings_analysis 序列化携带 composite_decision。

问题（round25 §2.5 实证）：R25 的 `_attach_composite_decisions` 已把 composite_decision
附加到 factor_breakdowns[sym]，但 holdings_analysis 序列化循环从不拷贝该字段 → API
响应无 composite_decision；前端 StrategyCheckResult 无「综合信号」列。整链断裂。

修复（round25 R28-a）：
- LLM 路径 `strategy_check` 的 holdings_analysis 后处理循环拷贝 `composite_decision`
  （与 factor_summary/tech_signal 同位置）；
- 规则兜底路径 `_build_rule_fallback_holdings_analysis` 同样拷贝；
- 字段缺失（因子数据不足/未附加）时整字段不出现（诚实降级，不填默认冒充）。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import _attach_composite_decisions


class TestHoldingsAnalysisCompositeDecision:
    """R28-a: holdings_analysis 每项携带 composite_decision。"""

    def test_serialize_copies_composite_decision(self):
        """factor_breakdowns 有 composite_decision → holdings_analysis 项含该字段。"""
        # 直接构造最小 factor_breakdowns + 空 LLM 结果，走 strategy_check 后处理
        fbs = {
            "510300": {
                "factor_scores": {"momentum": 0.5, "valuation": 0.3, "technical": 0.2},
                "technical_signal": {"signal": "hold", "score": 0.0, "reasons": []},
            },
        }
        _attach_composite_decisions(fbs, {"filled_count": 14, "total_count": 20})
        # 模拟 strategy_check 的 holdings_analysis 后处理：拷贝逻辑与 _build_rule_fallback 一致
        holdings = _build_fallback_for(fbs, {"510300": 0.4})
        h = holdings[0]
        assert h["symbol"] == "510300"
        assert "composite_decision" in h, "holdings_analysis 项必须携带 composite_decision（R28）"
        cd = h["composite_decision"]
        assert "signal" in cd and "score" in cd and "degraded" in cd

    def test_composite_absent_keeps_field_absent(self):
        """factor_breakdowns 无 composite_decision（未附加/附加失败）→ 响应字段不出现。"""
        fbs = {
            "510300": {
                "factor_scores": {"momentum": 0.5},
                "technical_signal": {"signal": "hold"},
                # 无 composite_decision
            },
        }
        holdings = _build_fallback_for(fbs, {"510300": 0.4})
        h = holdings[0]
        assert "composite_decision" not in h, "字段缺失时整字段不出现（诚实降级，负向）"

    @pytest.mark.asyncio
    async def test_strategy_check_llm_path_serializes_composite(self):
        """完整 strategy_check LLM 路径：holdings_analysis 项含 composite_decision。"""
        ps._strategy_check_cache.clear()
        etfs = [
            {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.4,
             "asset_type": "ETF", "portfolio_type": "on_exchange"},
            {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.3,
             "asset_type": "ETF", "portfolio_type": "on_exchange"},
        ]
        indicators = {"510300": {"signal": {"signal": "buy"}},
                      "518880": {"signal": {"signal": "hold"}}}
        factors = {
            "510300": {"technical.ma.sma_5": 0.8, "technical.rsi.rsi_14": 58.2,
                       "technical.signal.overall": 0.4},
            "518880": {"technical.ma.sma_5": -0.7, "technical.rsi.rsi_14": 41.3,
                       "technical.signal.overall": -0.5},
        }
        price = {"510300": (3.8, 1.2), "518880": (2.5, -0.5)}
        llm_result = {
            "summary": "测试报告",
            "suggestions": [],
            "holdings_analysis": [
                {"symbol": "510300", "name": "沪深300ETF"},
                {"symbol": "518880", "name": "黄金ETF"},
            ],
            "risk_warnings": [],
        }
        with patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=etfs), \
             patch.object(ps, "_compute_indicators", new_callable=AsyncMock, return_value=indicators), \
             patch.object(ps, "build_price_map", new_callable=AsyncMock, return_value=price), \
             patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"), \
             patch("app.factors.factor_registry.registry.compute", new_callable=AsyncMock, return_value=factors), \
             patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value=llm_result):
            result = await ps.strategy_check(db=None, total_capital=100000)

        holdings = result.get("holdings_analysis", [])
        assert holdings, "holdings_analysis 不应为空"
        for h in holdings:
            sym = h["symbol"]
            if sym in factors:
                assert "composite_decision" in h, (
                    f"{sym} holdings_analysis 项必须携带 composite_decision（R28-a）"
                )
                cd = h["composite_decision"]
                assert "degraded" in cd
                # 与 technical_signal 方向一致性：cd.technical_signal 存在
                assert cd.get("technical_signal") in ("buy", "hold", "sell", None)


def _build_fallback_for(fbs, weight_map):
    """调用 _build_rule_fallback_holdings_analysis 构造骨架（R28 拷贝逻辑所在）。"""
    etfs = [{"symbol": s, "name": s, "target_weight": w} for s, w in weight_map.items()]
    market_data = [{"symbol": s, "name": s, "target_weight": w} for s, w in weight_map.items()]
    return ps._build_rule_fallback_holdings_analysis(
        etfs=etfs, market_data=market_data,
        factor_breakdowns=fbs, weight_map=weight_map, regime="range_bound",
    )