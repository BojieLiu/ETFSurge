"""round35 B1-F5 (docs/round35-architecture-review.md §4.5/§6.1) —

O24 归因链恢复验证：引擎侧 rank_info（层内排名 N/M + 主驱动因子）必须经编排层
转发进入**生产** selection_rationale（此前 strategy_design 重调 build_rationale
不带 rank_info 整体覆盖 → 排名归因在生产输出中丢失）。

负向对照：无 rank_info 时 rationale 不含排名文案——证明正向断言真正依赖转发链
（若编排层转发被移除，正向断言即 FAIL，测试能抓假）。
"""
import re

import pytest

from app.engine.allocation_engine import allocate, build_rationale


_MATRIX = {
    sym: {
        "technical": 0.3 + i * 0.01, "momentum": 0.2, "valuation": 0.1,
        "sentiment": 0.0, "price": 3.0, "return_1m": 0.05, "return_3m": 0.10,
        "fund_flow": 0.0, "premium_discount": None,
        "technical.signal.overall": 0.2,
    }
    for i, sym in enumerate(
        ("510300", "510500", "512890", "512480", "518880",
         "159915", "513100", "511010")
    )
}

_CANDIDATES = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "industry": "宽基指数"},
    {"symbol": "510500", "name": "中证500ETF", "layer": "core", "industry": "宽基指数"},
    {"symbol": "512890", "name": "红利低波ETF", "layer": "core", "industry": "红利"},
    {"symbol": "512480", "name": "半导体ETF", "layer": "satellite", "industry": "半导体"},
    {"symbol": "159915", "name": "创业板ETF", "layer": "satellite", "industry": "成长"},
    {"symbol": "513100", "name": "纳指ETF", "layer": "satellite", "industry": "跨境"},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "industry": "商品"},
    {"symbol": "511010", "name": "国债ETF", "layer": "defense", "industry": "固收"},
]


def test_allocate_attaches_rank_info():
    """引擎侧：每只非 CASH 分配携带 _rank_info，rank 从 1 起、不超候选总数。"""
    strategies = allocate(
        risk_profile="balanced", regime="range_bound",
        factor_matrix=_MATRIX, candidates=_CANDIDATES,
    )
    seen_ranked = False
    for s in strategies:
        for a in s.get("allocations", []):
            if a.get("symbol") == "CASH":
                assert "_rank_info" not in a, "CASH 行不应携带 rank_info"
                continue
            ri = a.get("_rank_info")
            if ri is None:
                continue  # 某些后处理注入的行（如 C2 注入）可无 rank_info
            seen_ranked = True
            assert 1 <= ri["rank"] <= ri["total_candidates"]
            assert ri["dominant_factor"]
    # 至少一个方案的真实选股带排名归因（防全空夹具假绿）
    assert seen_ranked, "allocate 未产出任何 _rank_info"


def test_rationale_rank_text_requires_forwarding():
    """对照：同一输入下，带 rank_info 的 rationale 含排名+主驱动文案；
    不带（=编排层覆盖回归形态）则不含——断言依赖转发链而非恒真。"""
    common = dict(
        code="512480", layer="satellite", strategy="balanced",
        factor_scores={"technical": 0.9, "momentum": 0.4}, regime="range_bound",
    )
    with_rank = build_rationale(**common, rank_info={
        "rank": 2, "total_candidates": 7, "dominant_factor": "技术面",
    })
    without_rank = build_rationale(**common)
    assert "同类候选池排名 2/7" in with_rank
    assert "主驱动因子" in with_rank
    assert "同类候选池排名" not in without_rank


@pytest.mark.asyncio
async def test_production_pipeline_rationale_has_rank_attribution():
    """端到端：mock hub 最小夹具走完整编排流 → 生产 etfs[].selection_rationale
    含「同类候选池排名 N/M」与「主驱动因子」，且内部键 _rank_info 不残留。"""
    from unittest.mock import patch

    from app.services.strategy_design import generate_enhanced_design

    async def mock_refresh(*args, **kwargs):
        pass

    with patch("app.services.market_data_hub.market_data_hub.refresh", side_effect=mock_refresh), \
         patch("app.services.market_data_hub.market_data_hub.get_pool",
               side_effect=lambda layer=None: (
                   {c["layer"]: [c for c in _CANDIDATES if c["layer"] == c["layer"]]
                    for c in []} or {
                       "core": [c for c in _CANDIDATES if c["layer"] == "core"],
                       "satellite": [c for c in _CANDIDATES if c["layer"] == "satellite"],
                       "defense": [c for c in _CANDIDATES if c["layer"] == "defense"],
                   } if layer is None else [c for c in _CANDIDATES if c["layer"] == layer]
               )), \
         patch("app.services.market_data_hub.market_data_hub.get_factor_matrix", return_value=_MATRIX), \
         patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"), \
         patch("app.services.market_data_hub.market_data_hub.get_market_sentiment",
               return_value={"sentiment_index": 50, "sentiment_label": "中性"}), \
         patch("app.services.market_data_hub.market_data_hub.get_index_realtime", return_value=[]), \
         patch("app.services.market_data_hub.market_data_hub.get_sector_momentum", return_value=[]):
        result = await generate_enhanced_design(capital=500000)

    assert "strategies" in result and len(result["strategies"]) == 3, (
        f"expected 3 strategies, got: {list(result)[:5]}"
    )
    rank_pat = re.compile(r"同类候选池排名 \d+/\d+")
    hits = 0
    for s in result["strategies"]:
        for a in s.get("etfs", []):
            assert "_rank_info" not in a, (
                f"{a.get('symbol')}: 编排层未 pop 内部键 _rank_info（会泄漏到 API 输出）"
            )
            text = a.get("selection_rationale") or ""
            if rank_pat.search(text) and "主驱动因子" in text:
                hits += 1
    assert hits >= 3, (
        f"生产 rationale 缺排名归因（O24 回归）：仅 {hits} 条命中排名文案"
    )
