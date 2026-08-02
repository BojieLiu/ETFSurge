"""
P0-1 (R4-01): 策略检查「行业集中度风险」误导性输出修复。

- 空行业保护：_compute_risk_warnings 对无 sector/industry 字段的 holdings_analysis
  输出 WARN + 「行业数据缺失」标注，而非误导性 HIGH「仅覆盖1个行业」。
- 行业注入：strategy_check 后处理从 market_data_hub 候选池构建 symbol→industry
  映射并回填 holdings_analysis 的 sector/industry 字段（与设计任务同一来源）。
- 真实多行业覆盖时不误报。

mock 数据源与 LLM，无网络。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import _compute_risk_warnings


def test_risk_warnings_blank_industry_degraded_to_warn():
    """P0-1: 全部持仓无行业字段 → WARN + 标注（不 HIGH 误报「仅覆盖1个行业」）。"""
    holdings = [
        {"symbol": f"S{i:06d}", "name": f"ETF{i}", "weight": 0.1} for i in range(1, 11)
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings if w["type"] == "concentration"]
    assert conc, "应产出行业集中度提示"
    assert conc[0]["severity"] == "warning", \
        f"空行业应降级 WARN，实际 {conc[0]['severity']}"
    assert "行业数据缺失" in conc[0]["description"]
    assert len(conc[0]["affected_symbols"]) == 10


def test_risk_warnings_real_industries_no_false_positive():
    """P0-1: 真实覆盖 ≥7 行业（R4-01 场景）不误报行业集中度。"""
    industries = ["券商", "半导体设备", "创新药", "游戏", "黄金", "红利", "港股科技", "宽基"]
    holdings = [
        {"symbol": f"S{i:06d}", "name": f"ETF{i}", "weight": 0.1,
         "sector": industries[i % len(industries)],
         "industry": industries[i % len(industries)]}
        for i in range(10)
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings
            if w["type"] == "concentration" and "行业集中度" in w["description"]]
    assert not conc, "8 行业真实覆盖不应触发行业集中度警告"


def test_risk_warnings_partial_blank_still_warn():
    """P0-1: 部分标的缺行业（空串权重>0 且 unique<=2）→ WARN 非 HIGH。"""
    holdings = [
        {"symbol": "S1", "name": "A", "weight": 0.3, "sector": "券商"},
        {"symbol": "S2", "name": "B", "weight": 0.3},   # 无行业
        {"symbol": "S3", "name": "C", "weight": 0.2},   # 无行业
        {"symbol": "S4", "name": "D", "weight": 0.2},   # 无行业
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings if w["type"] == "concentration"]
    assert conc and conc[0]["severity"] == "warning"
    assert "行业数据缺失" in conc[0]["description"]


_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "512000", "name": "券商ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "hold"}},
    "512000": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "hold"}},
}

_MOCK_FACTORS = {
    "510300": {"technical": 0.3, "momentum": 0.2},
    "512000": {"technical": 0.6, "momentum": 0.5},
    "518880": {"technical": 0.1, "momentum": 0.0},
}

_MOCK_PRICE = {"510300": (3.8, 1.2), "512000": (0.9, 0.5), "518880": (8.4, -0.3)}


@pytest.mark.asyncio
async def test_strategy_check_injects_industry_from_hub_pool():
    """P0-1: strategy_check 后处理从 market_data_hub 候选池注入 sector/industry。"""
    ps._strategy_check_cache.clear()
    llm_holdings = [
        {"symbol": "510300", "name": "沪深300ETF", "weight": 0.2},
        {"symbol": "512000", "name": "券商ETF", "weight": 0.1},
        {"symbol": "518880", "name": "黄金ETF", "weight": 0.1},
    ]
    llm_result = {
        "summary": "测试摘要",
        "suggestions": [{"symbol": "512000", "action": "increase", "reason": "x",
                         "confidence": 0.7, "source": "llm",
                         "suggested_weight": 0.12}],
        "holdings_analysis": llm_holdings,
        "risk_warnings": [],
    }
    # 候选池条目含 industry（与设计任务同一来源）
    pool = {
        "core": [
            {"symbol": "510300", "name": "沪深300ETF", "industry": "宽基指数"},
            {"symbol": "512000", "name": "券商ETF", "industry": "券商"},
            {"symbol": "518880", "name": "黄金ETF", "industry": "商品"},
        ]
    }

    async def _fake_registry_compute(symbols, codes=None, market_data=None, symbol_extra=None):
        return {s: dict(_MOCK_FACTORS.get(s, {})) for s in symbols}

    with patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_MOCK_ETFS), \
         patch.object(ps, "_compute_indicators", new_callable=AsyncMock,
                      return_value=_MOCK_INDICATORS), \
         patch.object(ps, "build_price_map", new_callable=AsyncMock,
                      return_value=_MOCK_PRICE), \
         patch("app.services.market_data_hub.market_data_hub.get_market_regime",
               return_value="range_bound"), \
         patch("app.services.market_data_hub.market_data_hub.get_pool",
               return_value=pool), \
         patch("app.services.market_data_hub.market_data_hub.get_by_code",
               return_value=None), \
         patch("app.factors.factor_registry.registry.compute",
               new=AsyncMock(side_effect=_fake_registry_compute)), \
         patch("app.analysis.llm.generate_strategy_check_report",
               new_callable=AsyncMock, return_value=llm_result):
        from app.database import async_session
        result = await ps.strategy_check(
            MagicMock(), total_capital=500000, portfolio_type="on_exchange"
        )

    holdings = result["holdings_analysis"]
    ind_by_sym = {h["symbol"]: h for h in holdings}
    assert ind_by_sym["510300"].get("industry") == "宽基指数"
    assert ind_by_sym["510300"].get("sector") == "宽基指数"
    assert ind_by_sym["512000"].get("industry") == "券商"
    assert ind_by_sym["518880"].get("industry") == "商品"
    # 注入后风险警告不应误报「仅覆盖1个行业」（3 行业 + 无缺失）
    conc = [w for w in result["risk_warnings"]
            if w.get("type") == "concentration" and "行业集中度" in w.get("description", "")]
    assert not conc, f"行业注入后不应误报行业集中度: {conc}"
