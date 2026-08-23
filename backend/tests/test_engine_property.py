"""engine/ 属性测试（hypothesis）—— round36 工具链落地（2026-08-23）。

对纯函数策略引擎验证「任意合法输入下都成立」的不变量。
example 测试只验点，property 验面——随机输入专打边界与组合路径：

P1 apply_risk_controls 后：任意单只权重 ≤ max_single_weight（0.30）
   依据：单只钳制先于一切重分配；其后唯一增权路径是 9-F1 熊市释放回流
   defense 层，而 defense 预算 < 0.30 且层预算校验在其后兜底压回。
P2 apply_risk_controls 后：有预算层的实际合计 ≤ 层预算 + 容差
   依据：层预算校验（step2）位于 F5 红利迁移 / F6 成长压缩 / 9-F1 回流之后，
   其后仅剩 HHI 压缩与归一化（均只减不增）。
P3 总权重 ≤ max(输入总权重, 1.0)：管线内所有重分配均为「内部转移」，
   无净增路径；归一化只在 >1 时向下缩放。
P4 risk_metrics.sector_concentration 与 allocations 重算 HHI 自洽
   （内部一致性——防 metrics 与实际分配脱节）。
P5 allocate() 全管线：恒返回 defensive/balanced/aggressive 三方案、
   结构完整、单只 ≤ MAX_WEIGHT、总权重 ≤ 1。

运行：cd backend && python -m pytest tests/test_engine_property.py -q
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.engine.allocation_engine import MAX_WEIGHT, allocate
from app.engine.risk_controls import RISK_SETTINGS, apply_risk_controls

# ──────────────────────────── 输入生成器 ────────────────────────────

LAYER_KEYS = ("core", "satellite", "defense")

# [56]\d{5} 会偶发命中 MANDATORY_CODES（510300/159338）→ 强制锚豁免分支也被随机覆盖
SYMBOLS = st.from_regex(r"[56]\d{5}", fullmatch=True)

NAMES = st.sampled_from([
    # 混合覆盖 _is_growth_wide_basis（科创50/创业板）/ _is_dividend_etf（红利）关键词分支
    "沪深300ETF", "中证500ETF", "科创50ETF", "创业板ETF", "创业板50ETF",
    "红利低波ETF", "中证红利ETF", "纳指ETF", "黄金ETF", "国债ETF",
])

INDUSTRIES = st.sampled_from(["宽基", "科技成长", "红利", "海外", "商品", "债券"])

WEIGHTS = st.floats(min_value=0.001, max_value=0.45, allow_nan=False, allow_infinity=False)

# 卫星 ≤0.30、防御 ≤0.25：保证 P1 的推导前提（任何层预算都不超过单只上限）
LAYER_BUDGETS = st.fixed_dictionaries({
    "core": st.floats(0.30, 0.60, allow_nan=False),
    "satellite": st.floats(0.05, 0.30, allow_nan=False),
    "defense": st.floats(0.02, 0.25, allow_nan=False),
})

ALLOCS = st.lists(
    st.fixed_dictionaries({
        "symbol": SYMBOLS,
        "name": NAMES,
        "layer": st.sampled_from(LAYER_KEYS),
        "weight": WEIGHTS,
        "industry": INDUSTRIES,
        "factor_score": st.floats(-1.5, 1.5, allow_nan=False),
    }),
    min_size=1,
    max_size=12,
)

FACTOR_VALUES = st.fixed_dictionaries({
    "technical": st.floats(-1, 1, allow_nan=False),
    "momentum": st.floats(-1, 1, allow_nan=False),
    "valuation": st.floats(-1, 1, allow_nan=False),
    "sentiment": st.floats(-1, 1, allow_nan=False),
    # remove_stale_candidates / filter_extreme_drawdown 消费的字段：
    # return_1m 下探 -0.60 以触发 -40% 月跌幅剔除 + 幸存者回补路径
    "price": st.floats(0.01, 100, allow_nan=False),
    "return_1m": st.floats(-0.60, 0.60, allow_nan=False),
    "return_3m": st.floats(-0.80, 0.80, allow_nan=False),
})

REGIMES = st.sampled_from(["neutral", "bull", "bear", "correction", "panic"])

TOL_W = 2e-4    # 单值容差（引擎全程 round(4)，粒度 1e-4）
TOL_SUM = 5e-3  # 合计容差（≤12 只 × 多步 round 累积漂移上界）


def _make_strategies(allocs, budgets):
    """构造输入策略。逐条 dict() 拷贝——apply_risk_controls 就地修改入参。"""
    return [{
        "id": "balanced",
        "profile": "balanced",
        "layer_budget": dict(budgets),
        "allocations": [dict(a) for a in allocs],
    }]


# ──────────────────────────── 属性 ────────────────────────────

@settings(max_examples=200, deadline=None)
@given(allocs=ALLOCS, budgets=LAYER_BUDGETS,
       factor_matrix=st.dictionaries(SYMBOLS, FACTOR_VALUES, max_size=20),
       regime=REGIMES)
def test_p1_single_weight_never_exceeds_cap(allocs, budgets, factor_matrix, regime):
    out = apply_risk_controls(_make_strategies(allocs, budgets), factor_matrix, regime)
    for s in out:
        for a in s["allocations"]:
            assert a["weight"] <= RISK_SETTINGS.max_single_weight + TOL_W, (
                f"P1 违约: {a['symbol']}={a['weight']:.4f} (cap={RISK_SETTINGS.max_single_weight})"
            )


@settings(max_examples=200, deadline=None)
@given(allocs=ALLOCS, budgets=LAYER_BUDGETS,
       factor_matrix=st.dictionaries(SYMBOLS, FACTOR_VALUES, max_size=20),
       regime=REGIMES)
def test_p2_layer_actual_never_exceeds_budget(allocs, budgets, factor_matrix, regime):
    out = apply_risk_controls(_make_strategies(allocs, budgets), factor_matrix, regime)
    for s in out:
        layer_actual: dict[str, float] = {}
        for a in s["allocations"]:
            lay = a.get("layer", "core")
            layer_actual[lay] = layer_actual.get(lay, 0.0) + a["weight"]
        for lay, budget in s["layer_budget"].items():
            actual = layer_actual.get(lay, 0.0)
            assert actual <= budget + TOL_SUM * len(layer_actual), (
                f"P2 违约: {lay} actual={actual:.4f} budget={budget}"
            )


@settings(max_examples=200, deadline=None)
@given(allocs=ALLOCS, budgets=LAYER_BUDGETS,
       factor_matrix=st.dictionaries(SYMBOLS, FACTOR_VALUES, max_size=20),
       regime=REGIMES)
def test_p3_total_weight_bounded_by_input(allocs, budgets, factor_matrix, regime):
    strategies_in = _make_strategies(allocs, budgets)
    in_total = sum(a["weight"] for a in strategies_in[0]["allocations"])
    out = apply_risk_controls(strategies_in, factor_matrix, regime)
    for s in out:
        out_total = sum(a["weight"] for a in s["allocations"])
        assert out_total <= max(in_total, 1.0) + TOL_SUM, (
            f"P3 违约: out={out_total:.4f} > max(in={in_total:.4f}, 1.0)"
        )


@settings(max_examples=200, deadline=None)
@given(allocs=ALLOCS, budgets=LAYER_BUDGETS,
       factor_matrix=st.dictionaries(SYMBOLS, FACTOR_VALUES, max_size=20),
       regime=REGIMES)
def test_p4_risk_metrics_consistent_with_allocations(allocs, budgets, factor_matrix, regime):
    out = apply_risk_controls(_make_strategies(allocs, budgets), factor_matrix, regime)
    for s in out:
        metrics = s.get("risk_metrics")
        if not metrics or not s["allocations"]:
            continue  # 空分配的策略被引擎跳过，不产 metrics
        sector_w: dict[str, float] = {}
        for a in s["allocations"]:
            sec = a.get("industry") or a.get("layer", "其他")
            sector_w[sec] = sector_w.get(sec, 0.0) + a["weight"]
        hhi = sum(w ** 2 for w in sector_w.values())
        reported = metrics["sector_concentration"]
        assert abs(hhi - reported) <= 2e-3, (
            f"P4 违约: 重算 HHI={hhi:.4f} vs 报告 {reported}"
        )


# ────────────── allocate() 全管线冒烟属性 ──────────────

_POOL = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "segment": "hs300"},
    {"symbol": "510500", "name": "中证500ETF", "layer": "core", "segment": "zz500"},
    {"symbol": "512890", "name": "红利低波ETF", "layer": "core", "segment": "dividend"},
    {"symbol": "588000", "name": "科创50ETF", "layer": "core", "segment": "kc50"},
    {"symbol": "159915", "name": "创业板ETF", "layer": "satellite", "segment": "cyb"},
    {"symbol": "513100", "name": "纳指ETF", "layer": "satellite", "segment": "nsdq"},
    {"symbol": "561560", "name": "碳中和ETF", "layer": "satellite", "segment": "carbon"},
    {"symbol": "512480", "name": "半导体ETF", "layer": "satellite", "segment": "semi"},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "segment": "gold"},
    {"symbol": "511010", "name": "国债ETF", "layer": "defense", "segment": "bond"},
    {"symbol": "513500", "name": "标普500ETF", "layer": "defense", "segment": "sp500"},
]

_MATRIX = {
    c["symbol"]: {
        "technical": 0.3, "momentum": 0.2, "valuation": 0.1, "sentiment": 0.0,
        "price": 3.0, "return_1m": 0.05, "return_3m": 0.10,
    }
    for c in _POOL
}


@settings(max_examples=30, deadline=None)
@given(regime=REGIMES,
       jitter=st.dictionaries(
           st.sampled_from([c["symbol"] for c in _POOL]),
           st.floats(-0.8, 0.8, allow_nan=False),
       ))
def test_p5_allocate_pipeline_three_sound_strategies(regime, jitter):
    matrix = {sym: {**vals, "technical": vals["technical"] + jitter.get(sym, 0.0)}
              for sym, vals in _MATRIX.items()}
    out = allocate(
        risk_profile="balanced",
        regime=regime,
        factor_matrix=matrix,
        candidates=[dict(c) for c in _POOL],
        factor_definitions={},   # A1 纯度参数化：调用方注入，None 走内置默认
        ic_series=None,
    )
    assert {s["id"] for s in out} == {"defensive", "balanced", "aggressive"}
    for s in out:
        total = sum(a["weight"] for a in s["allocations"])
        assert total <= 1.0 + TOL_SUM, f"P5: {s['id']} 总权重 {total:.4f} > 1"
        for a in s["allocations"]:
            assert a["weight"] <= MAX_WEIGHT + TOL_W, (
                f"P5: {s['id']}/{a['symbol']}={a['weight']:.4f} > {MAX_WEIGHT}"
            )
