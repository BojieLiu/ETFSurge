"""
TDD tests for the intelligent portfolio design engine (core+satellite+defense) v3.0.

Covers:
- enrich_market_context builds assets from candidate pool
- classify_assets groups by layer
- allocate_layer_budget returns strategy-specific budgets
- generate_enhanced_design returns 3 strategies with 8~15 holdings each, weights sum to 1.0
- fast mode works without external network
- power_law_weights produces reasonable weight distribution
- v3.0 fixed core/defense weights and satellite dual-pool behavior
"""
import pytest

from app.services import strategy_design as sd
from app.services.strategy_design import (
    Asset, MarketContext, enrich_market_context, classify_assets,
    allocate_layer_budget, generate_full_design, power_law_weights,
    STRATEGY_META, CORE_REQUIRED, CORE_FIXED, DEFENSE_FIXED,
    MIN_WEIGHT, MAX_WEIGHT,
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


# ── allocate_layer_budget (v3.0) ─────────────────────────────
def test_allocate_layer_budget_defensive():
    b = allocate_layer_budget("defensive")
    # v3.0: core=50%, satellite=15%, defense=5%, cash=30%
    assert b == {"core": 0.50, "satellite": 0.15, "defense": 0.05}
    assert abs(sum(b.values()) - 0.70) < 1e-9  # 70% invested, 30% cash


def test_allocate_layer_budget_aggressive():
    b = allocate_layer_budget("aggressive")
    # v3.0: core=50%, satellite=35%, defense=5%, cash=10%
    assert b["core"] == 0.50
    assert b["satellite"] == 0.35
    assert b["defense"] == 0.05


def test_allocate_layer_budget_default_balanced():
    b = allocate_layer_budget("unknown_fallback")
    assert b == STRATEGY_META["balanced"]["layer_budget"]


# ── power_law_weights ──────────────────────────────────────────
def test_power_law_weights_basic():
    """幂律分配: 评分越高权重越大"""
    scores = [1.0, 2.0, 3.0]
    weights = power_law_weights(scores, 0.30)
    assert len(weights) == 3
    assert abs(sum(weights) - 0.30) < 1e-6
    # 评分最高的获得最大权重
    assert weights[2] >= weights[1] >= weights[0]


def test_power_law_weights_min_weight():
    """每个标的至少1%"""
    scores = [0.1, 0.1, 0.1]  # 相同低分
    weights = power_law_weights(scores, 0.05)
    for w in weights:
        assert w >= 0.01 - 1e-9


def test_power_law_weights_max_weight():
    """单个权重不超过30%"""
    scores = [100.0, 1.0]
    weights = power_law_weights(scores, 0.50)
    for w in weights:
        assert w <= 0.30 + 1e-9


def test_power_law_weights_empty():
    assert power_law_weights([], 0.30) == []


# ── generate_enhanced_design(v3.0) ──────────────────────────────────
async def test_generate_design_three_strategies():
    designs = await generate_full_design("balanced", 500000)
    assert len(designs) == 3
    ids = {d["id"] for d in designs}
    assert ids == {"defensive", "balanced", "aggressive"}


async def test_generate_design_holding_count_8_15():
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        n = len(d["etfs"])
        assert 8 <= n <= 15, f"{d['id']} has {n} holdings (need 8~15)"


async def test_generate_design_weights_sum_to_one():
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        total = sum(e["weight"] for e in d["etfs"])
        assert abs(total - 1.0) < 1e-6


async def test_generate_design_weight_range():
    """v3.0: 每只权重在 1%~30% 之间（不含现金）"""
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        for e in d["etfs"]:
            if e.get("layer") == "cash":
                continue
            assert MIN_WEIGHT <= e["weight"] <= MAX_WEIGHT + 1e-9, \
                f"{d['id']} {e['symbol']} weight={e['weight']:.4f} out of [{MIN_WEIGHT}, {MAX_WEIGHT}]"


async def test_generate_design_core_has_broad_indices():
    """每个方案核心层必须含沪深300+中证A500+红利低波 (v3.0 fixed)"""
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        core = [e for e in d["etfs"] if e["layer"] == "core"]
        core_codes = {e["symbol"] for e in core}
        assert "510300" in core_codes, f"{d['id']} missing 510300 in core"
        assert "560600" in core_codes, f"{d['id']} missing 560600 in core"


async def test_generate_design_fixed_core_weights():
    """v3.0: 核心层固定权重 510300=25%, 560600=15%, 510880=10%"""
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        core = {e["symbol"]: e["weight"] for e in d["etfs"] if e["layer"] == "core"}
        assert abs(core.get("510300", 0) - 0.25) < 0.02, f"{d['id']} 510300 weight off"
        assert abs(core.get("560600", 0) - 0.15) < 0.02, f"{d['id']} 560600 weight off"
        assert abs(core.get("510880", 0) - 0.10) < 0.02, f"{d['id']} 510880 weight off"


async def test_generate_design_fixed_defense():
    """v3.0: 防御层固定 518880(黄金ETF)=5%"""
    designs = await generate_full_design("balanced", 500000)
    for d in designs:
        defense = {e["symbol"]: e["weight"] for e in d["etfs"] if e["layer"] == "defense"}
        assert abs(defense.get("518880", 0) - 0.05) < 0.01, f"{d['id']} 518880 weight off"


async def test_generate_design_layer_budget_distribution():
    """进攻型卫星占比应高于防御型"""
    designs = await generate_full_design("aggressive", 500000)
    # designs 顺序: [defensive, balanced, aggressive]
    agg = designs[2]  # aggressive
    assert agg["id"] == "aggressive"
    sat_w = sum(e["weight"] for e in agg["etfs"] if e["layer"] == "satellite")
    # 进攻型卫星预算 35%
    assert sat_w >= 0.30


async def test_generate_design_target_amount():
    """target_amount = capital * weight"""
    designs = await generate_full_design("balanced", 1000000)
    for d in designs:
        for e in d["etfs"]:
            if e.get("layer") == "cash":
                continue
            assert abs(e["target_amount"] - 1000000 * e["weight"]) < 1.0


async def test_generate_design_strategies_differ():
    """三个方案的持仓和权重分布不同（各策略现金/卫星预算比例不同）"""
    designs = await generate_full_design("balanced", 500000)
    # 三个策略的卫星预算不同，因此总权重分布应有所不同
    core_weights = set()
    for d in designs:
        core_w = sum(e["weight"] for e in d["etfs"] if e["layer"] == "core")
        core_weights.add(round(core_w, 4))
    # 核心层固定 50% 但经归一化后可能有微小差异
    sat_weights = set()
    for d in designs:
        sat_w = sum(e["weight"] for e in d["etfs"] if e["layer"] == "satellite")
        sat_weights.add(round(sat_w, 4))
    # 至少卫星层权重在不同策略间不同（防御15%, 平衡25%, 进攻35%）
    assert len(sat_weights) >= 2, f"不同策略卫星层权重应不同: {sat_weights}"


# ── 策略元数据 ────────────────────────────────────────────
def test_strategy_meta_labels():
    """策略标签正确"""
    assert STRATEGY_META["defensive"]["label"] == "防御型"
    assert STRATEGY_META["balanced"]["label"] == "平衡型"
    assert STRATEGY_META["aggressive"]["label"] == "进攻型"


# ── v3.0 固定配置验证 ─────────────────────────────────────
def test_core_fixed_weights():
    """v3.0 核心层固定: 沪深300 25%, 中证A500 15%, 红利低波 10%"""
    total = sum(h["weight"] for h in CORE_FIXED)
    assert abs(total - 0.50) < 1e-6  # 核心层合计50%
    codes = {h["symbol"] for h in CORE_FIXED}
    assert codes == {"510300", "560600", "510880"}
    for h in CORE_FIXED:
        assert h["layer"] == "core"


def test_defense_fixed_weights():
    """v3.0 防御层固定: 黄金ETF 5%"""
    assert len(DEFENSE_FIXED) == 1
    assert DEFENSE_FIXED[0]["symbol"] == "518880"
    assert abs(DEFENSE_FIXED[0]["weight"] - 0.05) < 1e-6
    assert DEFENSE_FIXED[0]["layer"] == "defense"


# ── 策略差异化验证 ─────────────────────────────────────────

def test_defensive_highest_cash():
    """防御型现金比例最高(30%), 进攻型最低(10%)"""
    def_b = allocate_layer_budget("defensive")
    bal_b = allocate_layer_budget("balanced")
    agg_b = allocate_layer_budget("aggressive")
    def_cash = 1.0 - sum(def_b.values())
    bal_cash = 1.0 - sum(bal_b.values())
    agg_cash = 1.0 - sum(agg_b.values())
    assert def_cash > bal_cash > agg_cash


def test_aggressive_highest_satellite():
    """进攻型卫星预算最高(35%), 防御型最低(15%)"""
    def_b = allocate_layer_budget("defensive")
    agg_b = allocate_layer_budget("aggressive")
    assert agg_b["satellite"] > def_b["satellite"]
