"""F5 (round6 §14.3/§14.6): 红利禁落卫星层——层归属约束。

现象（14.3）：平衡/进攻方案红利低波 14.4%/15% 落在卫星层——层级错配，
红利低波是低波防御资产（R5-0-4 明确列为"防守型核心"），放卫星违背资产属性。

修复方向：
1. 默认池 515080 中证红利 layer 改 core（allocation_engine._DEFAULT_CANDIDATES）；
2. risk_controls 增加"红利不得落 satellite 层"校验——R5-0-4 扩展为
   权重+层归属双条件：satellite 层的红利标的移到 core（core 有容量时）
   或剔除（核心已满时）。
"""
from app.engine import allocation_engine, risk_controls
from app.engine.allocation_engine import _DEFAULT_CANDIDATES

# F5 测试用最小 factor_matrix：提供 price/return 避免 remove_stale_candidates
# 在空 matrix 下误杀全部标的（既有管线行为，非 F5 引入）。
_FM = {
    "510300": {"price": 4.0, "return_1m": 0.01},
    "510050": {"price": 3.0, "return_1m": 0.01},
    "159919": {"price": 4.1, "return_1m": 0.01},
    "510500": {"price": 6.0, "return_1m": 0.01},
    "159915": {"price": 2.5, "return_1m": 0.02},
    "512890": {"price": 1.2, "return_1m": 0.005},
    "515080": {"price": 1.1, "return_1m": 0.005},
}


def _mk_strategy(sid: str, allocs: list[dict]) -> dict:
    return {
        "id": sid,
        "name": sid,
        "allocations": allocs,
        "layer_budget": {"core": 0.40, "satellite": 0.30, "defense": 0.10},
    }


def _mk_alloc(symbol: str, name: str, layer: str, weight: float) -> dict:
    return {"symbol": symbol, "name": name, "layer": layer,
            "weight": weight, "industry": "宽基"}


class TestDividendLayerConstraint:
    def test_default_pool_515080_is_core(self):
        """F5: 默认池中 515080 中证红利 layer 必须为 core（不再允许进卫星）。"""
        entry = next(e for e in _DEFAULT_CANDIDATES if e.get("symbol") == "515080")
        assert entry.get("layer") == "core", \
            f"515080 默认 layer 应为 core, got {entry.get('layer')}"

    def test_dividend_in_satellite_moves_to_core(self):
        """F5: satellite 层红利标的 → 移至 core（core 有容量时），权重不变。"""
        s = _mk_strategy("s1", [
            _mk_alloc("510300", "沪深300ETF", "core", 0.30),
            _mk_alloc("512890", "红利低波ETF", "satellite", 0.14),
        ])
        out = risk_controls.apply_risk_controls([s], _FM)
        allocs = out[0]["allocations"]
        div = next(a for a in allocs if a.get("symbol") == "512890")
        assert div.get("layer") == "core", f"红利应移至 core, got {div.get('layer')}"
        # 移动后权重受既有 core 层预算（0.40）约束可能微降，但不得增加
        assert div.get("weight", 0) <= 0.14 + 1e-6, \
            f"移动不得增加权重: {div.get('weight')}"

    def test_dividend_in_satellite_removed_when_core_full(self):
        """F5: core 无容量时（已满 4 只）→ 红利从 satellite 剔除（防止层级错配）。"""
        s = _mk_strategy("s2", [
            _mk_alloc("510300", "沪深300ETF", "core", 0.12),
            _mk_alloc("510050", "上证50ETF", "core", 0.12),
            _mk_alloc("159919", "沪深300ETF", "core", 0.10),
            _mk_alloc("510500", "中证500ETF", "core", 0.10),
            _mk_alloc("515080", "中证红利ETF", "satellite", 0.10),
        ])
        out = risk_controls.apply_risk_controls([s], _FM)
        allocs = out[0]["allocations"]
        divs = [a for a in allocs if a.get("symbol") == "515080"]
        assert not divs, "core 已满时红利应从卫星剔除, got %s" % divs

    def test_non_dividend_satellite_untouched(self):
        """F5: 非红利卫星标的不受影响（回归）。"""
        s = _mk_strategy("s3", [
            _mk_alloc("510300", "沪深300ETF", "core", 0.30),
            _mk_alloc("159915", "创业板ETF", "satellite", 0.15),
        ])
        out = risk_controls.apply_risk_controls([s], _FM)
        allocs = out[0]["allocations"]
        sat = [a for a in allocs if a.get("layer") == "satellite"]
        assert any(a.get("symbol") == "159915" for a in sat)
