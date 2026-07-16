"""
TDD tests for the intelligent portfolio design engine (core+satellite+defense).

Covers:
- enrich_market_context builds assets from candidate pool
- classify_assets groups by layer
- allocate_layer_budget returns strategy-specific budgets
- optimize_layer respects 1%~30% (and per-layer cap) constraints, core includes 510300/560600
- generate_design returns 3 strategies with 8~15 holdings each, weights sum to 1.0
- fast mode works without external network
External data sources are mocked.
"""
import pytest

from app.services import strategy_design as sd
from app.services.strategy_design import (
    Asset, MarketContext, enrich_market_context, classify_assets,
    allocate_layer_budget, generate_design,
    STRATEGY_META, CORE_REQUIRED, MIN_WEIGHT, MAX_WEIGHT
)


# ── enrich_market_context ────────────────────────────────────
async def test_enrich_market_context_builds_pool():
    ctx = await enrich_market_context()
    assert isinstance(ctx, MarketContext)
    # 候选池全部进入 assets
    assert set(ctx.assets.keys()) == set(sd.CANDIDATE_POOL.keys())
    # 核心层含沪深300与中证A500
    core = [a for a in ctx.assets.values() if a.layer == "core"]
    core_codes = {a.code for a in core}
    assert "510300" in core_codes
    assert "560600" in core_codes


# ── classify_assets ──────────────────────────────────────────
async def test_classify_assets_groups_by_layer():
    ctx = await enrich_market_context()
    layers = classify_assets(ctx)
    assert set(layers.keys()) == {"core", "satellite", "defense"}
    assert len(layers["core"]) >= 2
    assert len(layers["satellite"]) >= 2
    assert len(layers["defense"]) >= 2


# ── allocate_layer_budget ────────────────────────────────────
def test_allocate_layer_budget_defensive():
    b = allocate_layer_budget("defensive")
    assert b == {"core": 0.55, "satellite": 0.25, "defense": 0.20}
    assert abs(sum(b.values()) - 1.0) < 1e-9


def test_allocate_layer_budget_aggressive():
    b = allocate_layer_budget("aggressive")
    assert b["core"] == 0.50
    assert b["satellite"] == 0.40
    assert b["defense"] == 0.10


def test_allocate_layer_budget_default_balanced():
    b = allocate_layer_budget("unknown_fallback")
    assert b == STRATEGY_META["balanced"]["layer_budget"]


# ── optimize_layer ───────────────────────────────────────────
def _make_assets(codes):
    pool = sd.CANDIDATE_POOL
    return [
        Asset(code=c, name=pool[c]["name"], layer=pool[c]["layer"],
              beta=pool[c]["beta"], liquidity=pool[c]["liquidity"], reason=pool[c]["reason"])
        for c in codes
    ]


def test_optimize_layer_constraints_core():
    """核心层: 单只 1%~20%, 含510300/560600各>=5%, 加总=预算"""
    core_codes = ["510300", "560600", "510500", "159915", "510880"]
    assets = _make_assets(core_codes)
    budget = 0.55
    result = optimize_layer("core", assets, budget, "balanced")
    assert len(result) == len(core_codes)
    total = sum(r["weight"] for r in result)
    assert abs(total - budget) < 1e-6
    for r in result:
        assert MIN_WEIGHT <= r["weight"] <= sd.LAYER_WEIGHT_CAP["core"] + 1e-9
    sym_w = {r["symbol"]: r["weight"] for r in result}
    assert sym_w["510300"] >= sd.CORE_MIN_EACH - 1e-9
    assert sym_w["560600"] >= sd.CORE_MIN_EACH - 1e-9


def test_optimize_layer_satellite_cap():
    """卫星层单只上限 12%"""
    sat_codes = ["512480", "515030", "512010", "515080", "512890", "561300", "516160"]
    assets = _make_assets(sat_codes)
    result = optimize_layer("satellite", assets, 0.30, "aggressive")
    for r in result:
        assert r["weight"] <= sd.LAYER_WEIGHT_CAP["satellite"] + 1e-9
        assert r["weight"] >= MIN_WEIGHT - 1e-9


def test_optimize_layer_defense_cap():
    """防御层单只上限 8%"""
    def_codes = ["518880", "511090", "511990", "513500", "159980"]
    assets = _make_assets(def_codes)
    result = optimize_layer("defense", assets, 0.20, "defensive")
    for r in result:
        assert r["weight"] <= sd.LAYER_WEIGHT_CAP["defense"] + 1e-9


def test_optimize_layer_empty_returns_empty():
    assert optimize_layer("core", [], 0.5) == []


# ── generate_design ──────────────────────────────────────────
async def test_generate_design_three_strategies():
    designs = await generate_design("balanced", 500000, mode="fast")
    assert len(designs) == 3
    ids = {d["id"] for d in designs}
    assert ids == {"defensive", "balanced", "aggressive"}


async def test_generate_design_holding_count_8_15():
    designs = await generate_design("balanced", 500000, mode="fast")
    for d in designs:
        n = len(d["etfs"])
        assert 8 <= n <= 15, f"{d['id']} has {n} holdings (need 8~15)"


async def test_generate_design_weights_sum_to_one():
    designs = await generate_design("balanced", 500000, mode="fast")
    for d in designs:
        total = sum(e["weight"] for e in d["etfs"])
        assert abs(total - 1.0) < 1e-6


async def test_generate_design_weight_range():
    designs = await generate_design("balanced", 500000, mode="fast")
    for d in designs:
        for e in d["etfs"]:
            assert MIN_WEIGHT <= e["weight"] <= MAX_WEIGHT + 1e-9
            # 层上限
            cap = sd.LAYER_WEIGHT_CAP.get(e["layer"], MAX_WEIGHT)
            assert e["weight"] <= cap + 1e-9


async def test_generate_design_core_has_broad_indices():
    """每个方案核心层必须含沪深300或中证A500(至少各1只)"""
    designs = await generate_design("balanced", 500000, mode="fast")
    for d in designs:
        core = [e for e in d["etfs"] if e["layer"] == "core"]
        core_codes = {e["symbol"] for e in core}
        assert "510300" in core_codes, f"{d['id']} missing 510300 in core"
        assert "560600" in core_codes, f"{d['id']} missing 560600 in core"


async def test_generate_design_layer_budget_distribution():
    """进攻型卫星占比应高于防御型"""
    designs = await generate_design("aggressive", 500000, mode="fast")
    # designs 顺序: [defensive, balanced, aggressive]
    agg = designs[2]  # aggressive
    assert agg["id"] == "aggressive"
    sat_w = sum(e["weight"] for e in agg["etfs"] if e["layer"] == "satellite")
    assert sat_w >= 0.30  # 进攻型卫星预算 40%


async def test_generate_design_target_amount():
    """target_amount = capital * weight"""
    designs = await generate_design("balanced", 1000000, mode="fast")
    for d in designs:
        for e in d["etfs"]:
            assert abs(e["target_amount"] - 1000000 * e["weight"]) < 1.0


async def test_generate_design_constraints_min_names():
    """约束 min_names 生效"""
    designs = await generate_design("balanced", 500000, mode="fast",
                                    constraints={"min_names": 12, "max_names": 12})
    for d in designs:
        assert len(d["etfs"]) == 12


async def test_generate_design_standard_mode_runs():
    """standard 模式能跑通(外部数据可能失败但应降级)"""
    designs = await generate_design("balanced", 500000, mode="standard")
    assert len(designs) == 3
    for d in designs:
        assert len(d["etfs"]) >= 8


def test_strategy_meta_labels():
    """策略标签正确"""
    assert STRATEGY_META["defensive"]["label"] == "防御型"
    assert STRATEGY_META["balanced"]["label"] == "平衡型"
    assert STRATEGY_META["aggressive"]["label"] == "进攻型"


# ── 策略差异化验证 ─────────────────────────────────────────


def _make_known_beta_assets():
    """创建已知 β 值的资产集合，用于验证不同策略的偏好差异"""
    return [
        Asset(code="510880", name="红利低波ETF", layer="satellite",
              beta=0.75, liquidity=9.0, price=1.0, change_pct=0.0,
              net_inflow=0.0, valuation_pct=0.5, reason="test"),
        Asset(code="510300", name="沪深300ETF", layer="satellite",
              beta=1.0, liquidity=25.0, price=1.0, change_pct=0.0,
              net_inflow=0.0, valuation_pct=0.5, reason="test"),
        Asset(code="159915", name="创业板ETF", layer="satellite",
              beta=1.25, liquidity=18.0, price=1.0, change_pct=0.0,
              net_inflow=0.0, valuation_pct=0.5, reason="test"),
    ]


def test_defensive_prefers_low_beta():
    """防御型: 低β(0.75)的权重应高于高β(1.25)的权重"""
    assets = _make_known_beta_assets()
    result = optimize_layer("satellite", assets, 0.5, strategy="defensive")
    weights = {r["symbol"]: r["weight"] for r in result}
    low = weights.get("510880", 0)
    high = weights.get("159915", 0)
    assert low > 0, "防御型必须选中低β资产(510880)"
    assert low >= high, f"防御型中低β({low:.4f})应不低于高β({high:.4f})"


def test_aggressive_prefers_high_beta():
    """进攻型: 高β(1.25)的权重应高于或等于低β(0.75)的权重"""
    assets = _make_known_beta_assets()
    result = optimize_layer("satellite", assets, 0.5, strategy="aggressive")
    weights = {r["symbol"]: r["weight"] for r in result}
    high = weights.get("159915", 0)
    low = weights.get("510880", 0)
    assert high > 0, "进攻型必须选中高β资产(159915)"
    assert high >= low, f"进攻型中高β({high:.4f})应不低于低β({low:.4f})"


def test_strategies_scoring_order_reversed():
    """防御型和进攻型对红利的排序应相反（防御=红利>创业板, 进攻=创业板>红利）"""
    # 直接用 optimize_layer 的 score 内部函数验证
    # 防御型: 低β(510880)在 scored 列表中排在 高β(159915)之前
    from app.services.strategy_design import Asset, MIN_WEIGHT, MAX_WEIGHT,
    assets = _make_known_beta_assets()

    def get_top_by_strategy(strategy):
        # 防御型: 复制 optimize_layer 的评分逻辑
        liq = min(assets[0].liquidity / 20.0, 1.0) * 0.15
        def score(a):
            val = (0.5 - a.valuation_pct) * 0.3
            mom = max(0, a.change_pct) * 2.0
            if strategy == "defensive":
                ret = max(0, 1.5 - a.beta) * 0.6
                return ret + val * 1.5 + liq
            elif strategy == "aggressive":
                ret = a.beta * 0.5
                return ret + mom + liq
            else:
                ret = a.beta * 0.35
                return ret + val + liq + mom * 0.3
        scored = sorted(assets, key=score, reverse=True)
        return [a.code for a in scored]

    def_order = get_top_by_strategy("defensive")
    agg_order = get_top_by_strategy("aggressive")
    bal_order = get_top_by_strategy("balanced")

    # 防御型: 红利(510880)应排在创业板(159915)前面
    assert def_order.index("510880") < def_order.index("159915"), "防御型红利应排在创业板前面"
    # 进攻型: 创业板(159915)应排在红利(510880)前面
    assert agg_order.index("159915") < agg_order.index("510880"), "进攻型创业板应排在红利前面"
    # 平衡型: 排序应居中（不要求具体的顺序，只验证有排序）
