"""round35 B1-F4 (docs/round35-architecture-review.md §4.4/§6.1) —

sector_concentration 单点产出验证：
- allocate() 不再携带基于 layer 名的 HHI 死计算（D4：恒为层预算平方和、
  对持仓不敏感，且恒被 apply_risk_controls 的真实 industry 口径整体覆盖）；
- 行业集中度有且仅有风控层一处产出（industry 缺失时 fallback layer 名）。
"""
import pytest

from app.engine.allocation_engine import allocate
from app.engine.risk_controls import apply_risk_controls


_MATRIX = {
    sym: {
        "technical": 0.3, "momentum": 0.2, "valuation": 0.1, "sentiment": 0.0,
        "price": 3.0, "return_1m": 0.05, "return_3m": 0.10,
        "fund_flow": 0.0, "premium_discount": None,
        "technical.signal.overall": 0.2,
    }
    for sym in (
        "510300", "510500", "512890", "512480", "518880",
        "159915", "513100", "511010",
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


def test_allocate_no_longer_carries_sector_concentration():
    """负向：allocate 返回值不含 sector_concentration 键（死计算已删，
    若回归即说明 layer 名 HHI 复活——对持仓不敏感的误导数值）。"""
    strategies = allocate(
        risk_profile="balanced",
        regime="range_bound",
        factor_matrix=_MATRIX,
        candidates=_CANDIDATES,
    )
    assert len(strategies) == 3
    for s in strategies:
        rm = s.get("risk_metrics")
        assert rm is not None, "risk_metrics 键应保留（空 dict，兼容直接消费方）"
        assert "sector_concentration" not in rm
        assert "sector_breakdown" not in rm


def test_risk_controls_industry_hhi_single_source():
    """正向：apply_risk_controls 输出的 sector_concentration 与手算
    industry-HHI 一致（单点产出 + 数值正确）。"""
    base = {
        "id": "balanced", "label": "平衡型", "allocations": [
            {"symbol": "512480", "layer": "satellite", "weight": 0.30, "industry": "半导体"},
            {"symbol": "513100", "layer": "satellite", "weight": 0.25, "industry": "跨境"},
            {"symbol": "512890", "layer": "core", "weight": 0.45, "industry": "红利"},
        ],
        "layer_budget": {"core": 0.50, "satellite": 0.40, "defense": 0.10},
    }
    out = apply_risk_controls([base], _MATRIX, regime="range_bound")
    s = out[0]
    sector_w: dict[str, float] = {}
    for a in s["allocations"]:
        sec = a.get("industry") or a.get("layer", "其他")
        sector_w[sec] = sector_w.get(sec, 0.0) + a["weight"]
    hhi = sum(w ** 2 for w in sector_w.values())
    assert abs(s["risk_metrics"]["sector_concentration"] - hhi) <= 1e-3
    assert set(s["risk_metrics"]["sector_breakdown"]) == set(sector_w)


def test_layer_fallback_exists_only_in_risk_controls():
    """负向：industry 全缺失时 fallback layer 的行为**有且仅有一处**（风控层）
    ——allocate 已无任何 sector 口径计算。"""
    cands_no_industry = [{**c, "industry": ""} for c in _CANDIDATES]
    strategies = allocate(
        risk_profile="defensive",
        regime="bear",
        factor_matrix=_MATRIX,
        candidates=cands_no_industry,
    )
    for s in strategies:
        assert "sector_concentration" not in (s.get("risk_metrics") or {})

    # 风控层：industry 缺失 → fallback layer 名（唯一 fallback 点），仍产出指标
    base = {
        "id": "defensive", "label": "防御型", "allocations": [
            {"symbol": "512890", "layer": "core", "weight": 0.60},
            {"symbol": "518880", "layer": "defense", "weight": 0.40},
        ],
        "layer_budget": {"core": 0.65, "satellite": 0.20, "defense": 0.15},
    }
    out = apply_risk_controls([base], _MATRIX, regime="bear")
    rm = out[0]["risk_metrics"]
    assert "sector_concentration" in rm
    assert set(rm["sector_breakdown"]) <= {"core", "satellite", "defense", "其他"}
