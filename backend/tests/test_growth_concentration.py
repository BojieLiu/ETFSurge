"""F6 (round6 §14.4/§14.6): 核心层成长风格集中度约束。

现象（14.4）：进攻方案核心层科创50 16.3% + 创业板 14.7% = 31%
（高 beta 成长宽基），叠加卫星科创主题 16.4% → 成长/科技风格合计约 47%，
风格集中度风险（科创50 与创业板同受成长/科技风格驱动，相关性高）。

修复：核心层同风格高 beta 成长宽基（科创50/创业板/科创100 等）合计
≤ 核心层预算的 40%（与 F4 科技裁剪口径一致：budget × 40%）。
"""
from app.engine import risk_controls
from app.engine.allocation_engine import _is_growth_wide_basis

_FM = {
    "510300": {"price": 4.0, "return_1m": 0.01},
    "588000": {"price": 1.0, "return_1m": 0.05},
    "159915": {"price": 2.5, "return_1m": 0.04},
    "588190": {"price": 1.0, "return_1m": 0.05},
    "512010": {"price": 1.2, "return_1m": 0.01},
}


def _mk_alloc(symbol: str, name: str, layer: str, weight: float, industry: str = "宽基") -> dict:
    return {"symbol": symbol, "name": name, "layer": layer,
            "weight": weight, "industry": industry}


class TestGrowthConcentration:
    def test_growth_wide_basis_detector(self):
        """F6: 成长宽基判定——科创50/创业板/科创100 是，沪深300/红利不是。"""
        assert _is_growth_wide_basis({"name": "科创50ETF", "industry": "宽基"})
        assert _is_growth_wide_basis({"name": "创业板ETF", "industry": "宽基"})
        assert _is_growth_wide_basis({"name": "科创100ETF", "industry": "宽基"})
        assert not _is_growth_wide_basis({"name": "沪深300ETF", "industry": "宽基"})
        assert not _is_growth_wide_basis({"name": "红利低波ETF", "industry": "宽基"})
        # 科创主题 ETF（非宽基）不算成长宽基——行业字段能区分时
        assert not _is_growth_wide_basis({"name": "科创芯片ETF", "industry": "半导体"})

    def test_core_growth_over_40pct_capped(self):
        """F6: 核心层成长宽基合计 > 核心预算 40% → 压缩到阈值。"""
        s = {
            "id": "aggressive", "name": "aggressive",
            "allocations": [
                _mk_alloc("510300", "沪深300ETF", "core", 0.14),
                _mk_alloc("588000", "科创50ETF", "core", 0.16),
                _mk_alloc("159915", "创业板ETF", "core", 0.15),
            ],
            "layer_budget": {"core": 0.45, "satellite": 0.30, "defense": 0.11},
        }
        out = risk_controls.apply_risk_controls([s], _FM)
        allocs = out[0]["allocations"]
        core_budget = 0.45
        growth = [a for a in allocs if _is_growth_wide_basis(a)]
        growth_sum = sum(a.get("weight", 0) for a in growth)
        assert growth_sum <= core_budget * 0.4 + 1e-6, \
            f"成长宽基合计应 ≤ {core_budget*0.4:.2f}, got {growth_sum:.2f}"

    def test_core_growth_within_limit_untouched(self):
        """F6: 成长宽基合计未超限时不触发（回归）。"""
        s = {
            "id": "defensive", "name": "defensive",
            "allocations": [
                _mk_alloc("510300", "沪深300ETF", "core", 0.30),
                _mk_alloc("588000", "科创50ETF", "core", 0.10),
            ],
            "layer_budget": {"core": 0.51, "satellite": 0.20, "defense": 0.15},
        }
        out = risk_controls.apply_risk_controls([s], _FM)
        allocs = out[0]["allocations"]
        growth = [a for a in allocs if _is_growth_wide_basis(a)]
        growth_sum = sum(a.get("weight", 0) for a in growth)
        assert growth_sum > 0.09, f"未超限不应压缩: {growth_sum}"
