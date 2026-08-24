"""
ETF Surge — Strategy budgets and meta-configuration.

Pure functions only — no I/O, no database, no HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Strategy metadata ───────────────────────────────────────────────
# 「单一可校验真相源」：budgets 配置是引擎消费的唯一真相源（非动态涌现）。
# round22 重构（docs/archived/design-portfolio-engine-redesign.md）新增字段：
#   - core_growth_cap: INV-4 核心层「高 beta 成长宽基」占核心预算的上限
#     （def 0.20 / bal 0.40 / agg 0.60，用 _is_growth_wide_basis 代理 beta）。
#   - layer_count 卫星目标随风险档次单调递增（def 4 < bal 6 < agg 8），核心
#     目标非递减（4/5/6），防御目标反向（2/1/1）——满足 INV-3。
#   - 进攻型 layer_budget 改为 core 0.60 / sat 0.30 / def 0.05（cash 0.05），
#     满足 INV-6（进攻防御 ≤0.05、现金 ≤0.10）。
# ── Mandatory anchor codes (round35 B1-F2, §4.2 D2 单一真相源上移) ─────
# 强制锚集合原为 allocation_engine.py 与 pool_balancing.py 两处字面量副本
# （历史 560600→159338 换锚事件证明该集合会变，双份漂移只是时间问题）。
# budgets.py 已是策略元数据单一真相源——锚常量随之上移；allocation_engine
# 模块级 re-export 保兼容（risk_controls 函数内 lazy import 零改动）。
CORE_ANCHORS = {"510300", "159338"}       # 核心层强制锚（沪深300/中证A500）
DEFENSE_ANCHORS = {"518880", "511090"}    # 防御层强制锚（黄金/30年国债），按 defense_count 注入
MANDATORY_CODES = CORE_ANCHORS | DEFENSE_ANCHORS
MANDATORY_MIN_WEIGHT = 0.03
MANDATORY_FLOOR = 0.05

STRATEGY_META: dict[str, dict[str, Any]] = {
    "defensive": {
        "id": "defensive",
        "label": "防御型",
        "color": "#43A047",
        "portfolio_name": "防御稳健组合",
        "positioning": "低波稳健配置，控制回撤，适合保守风险偏好者",
        "expected_return": 0.08,
        "max_drawdown": -0.12,
        "sharpe_ratio": 1.2,
        "layer_budget": {"core": 0.50, "satellite": 0.20, "defense": 0.15},
        "layer_count": {"core": 4, "satellite": 4, "defense": 2},
        "core_growth_cap": 0.20,
        "expected_characteristics": "预期年化波动10-12%，最大回撤区间10-12%",
    },
    "balanced": {
        "id": "balanced",
        "label": "平衡型",
        "color": "#1976D2",
        "portfolio_name": "均衡配置组合",
        "positioning": "核心稳健+卫星增强，攻守兼备，适合中等风险偏好者",
        "expected_return": 0.11,
        "max_drawdown": -0.18,
        "sharpe_ratio": 1.0,
        # §5.1C (round8 §7 拍板): 压卫星 ≤20%（0.30→0.20）、防御抬至 15%（0.10→0.15）、
        # core 0.50 保持 85% 仓位（现金 15%，U6 现金收敛验收不变）
        "layer_budget": {"core": 0.50, "satellite": 0.20, "defense": 0.15},
        "layer_count": {"core": 5, "satellite": 6, "defense": 1},
        "core_growth_cap": 0.40,
        "expected_characteristics": "预期年化波动15-18%，最大回撤区间15-18%",
    },
    "aggressive": {
        "id": "aggressive",
        "label": "进攻型",
        "color": "#E53935",
        "portfolio_name": "锐意进取组合",
        "positioning": "高弹性行业/主题权重大，承受较大回撤博取超额",
        "expected_return": 0.16,
        "max_drawdown": -0.35,
        "sharpe_ratio": 0.8,
        # round22 (#13 INV-6): 进攻型去保守化——防御层压到最低（仅黄金）、现金 <10%，
        # 权重让给核心+卫星。core 0.60 / sat 0.30 / def 0.05（cash = 1 - 0.95 = 0.05）。
        "layer_budget": {"core": 0.60, "satellite": 0.30, "defense": 0.05},
        "layer_count": {"core": 6, "satellite": 8, "defense": 1},
        "core_growth_cap": 0.60,
        "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
    },
}


@dataclass(frozen=True)
class ProfileSpec:
    """round22 单一可校验真相源：从 STRATEGY_META 构造，加载期跑 INV-1~6 校验。

    引擎严格消费本结构（通过 STRATEGY_META 透传），不变量在导入即崩溃（fail-fast），
    杜绝「配置非真相源 → 倒挂组合静默产出」（round21 §12 #10–#14 根因）。
    """

    id: str
    label: str
    color: str
    portfolio_name: str
    positioning: str
    expected_return: float
    max_drawdown: float
    sharpe_ratio: float
    layer_budget: dict[str, float]      # {core, satellite, defense}，sum+cash==1
    layer_count: dict[str, int]         # {core, satellite, defense}，目标数量
    core_growth_cap: float              # INV-4：核心层成长宽基占比上限（占 core 预算）
    expected_characteristics: str
    # round23 §6.2c: c2_adjust 死配置已删除（引擎从不消费；C2 逻辑用硬编码 _RISKY/_SAFE_THEMES）


def build_profile_specs() -> dict[str, ProfileSpec]:
    """从 STRATEGY_META 构造 ProfileSpec（单一真相源）。"""
    specs: dict[str, ProfileSpec] = {}
    for pid, meta in STRATEGY_META.items():
        specs[pid] = ProfileSpec(
            id=meta["id"],
            label=meta["label"],
            color=meta["color"],
            portfolio_name=meta["portfolio_name"],
            positioning=meta["positioning"],
            expected_return=float(meta["expected_return"]),
            max_drawdown=float(meta["max_drawdown"]),
            sharpe_ratio=float(meta["sharpe_ratio"]),
            layer_budget=dict(meta["layer_budget"]),
            layer_count=dict(meta["layer_count"]),
            core_growth_cap=float(meta.get("core_growth_cap", 0.40)),
            expected_characteristics=meta["expected_characteristics"],
        )
    return specs


def _cash_of(layer_budget: dict[str, float]) -> float:
    return 1.0 - (layer_budget["core"] + layer_budget["satellite"] + layer_budget["defense"])


def validate_profile_specs(specs: dict[str, ProfileSpec]) -> None:
    """round22 加载期不变量校验（INV-1~6）。违反即抛 ValueError（fail-fast）。

    INV-1 预算闭合：每方案 core+sat+def+cash==1.0
    INV-2 预算随风险单调：defense 防御≥平衡≥进攻；satellite 防御≤平衡≤进攻；cash 防御≥平衡≥进攻
    INV-3 层数量随风险单调（目标）：satellite 防御<平衡<进攻；defense 防御≥平衡≥进攻；core 非递减
    INV-4 核心成长宽基占比上限：core_growth_cap 防御≤平衡≤进攻
    （INV-5 总标的数单调 / INV-6 进攻压舱 为输出级，由 check_structure_reasonableness 运行时校验）
    """
    profiles = ["defensive", "balanced", "aggressive"]
    for p in profiles:
        spec = specs[p]
        lb = spec.layer_budget
        s = lb["core"] + lb["satellite"] + lb["defense"]
        cash = _cash_of(lb)
        if not (-1e-9 <= s <= 1.0 + 1e-9):
            raise ValueError(f"INV-1 violated ({p}): layer budget sum={s:.4f} not in [0,1]")
        if cash < -1e-9:
            raise ValueError(f"INV-1 violated ({p}): negative cash={cash:.4f}")

    d, b, a = specs["defensive"], specs["balanced"], specs["aggressive"]

    def _cash(spec: ProfileSpec) -> float:
        return _cash_of(spec.layer_budget)

    if not (d.layer_budget["defense"] >= b.layer_budget["defense"] >= a.layer_budget["defense"] - 1e-9):
        raise ValueError(
            f"INV-2 violated: defense budget not monotonic "
            f"(def={d.layer_budget['defense']}, bal={b.layer_budget['defense']}, agg={a.layer_budget['defense']})"
        )
    if not (d.layer_budget["satellite"] <= b.layer_budget["satellite"] <= a.layer_budget["satellite"] + 1e-9):
        raise ValueError(
            f"INV-2 violated: satellite budget not monotonic "
            f"(def={d.layer_budget['satellite']}, bal={b.layer_budget['satellite']}, agg={a.layer_budget['satellite']})"
        )
    if not (_cash(d) >= _cash(b) >= _cash(a) - 1e-9):
        raise ValueError(
            f"INV-2 violated: cash not monotonic "
            f"(def={_cash(d):.4f}, bal={_cash(b):.4f}, agg={_cash(a):.4f})"
        )

    if not (d.layer_count["satellite"] < b.layer_count["satellite"] < a.layer_count["satellite"]):
        raise ValueError(
            f"INV-3 violated: satellite count not strictly increasing "
            f"(def={d.layer_count['satellite']}, bal={b.layer_count['satellite']}, agg={a.layer_count['satellite']})"
        )
    if not (d.layer_count["defense"] >= b.layer_count["defense"] >= a.layer_count["defense"]):
        raise ValueError(
            f"INV-3 violated: defense count not reverse-monotonic "
            f"(def={d.layer_count['defense']}, bal={b.layer_count['defense']}, agg={a.layer_count['defense']})"
        )
    if not (d.layer_count["core"] <= b.layer_count["core"] <= a.layer_count["core"]):
        raise ValueError(
            f"INV-3 violated: core count not non-decreasing "
            f"(def={d.layer_count['core']}, bal={b.layer_count['core']}, agg={a.layer_count['core']})"
        )

    if not (d.core_growth_cap <= b.core_growth_cap <= a.core_growth_cap + 1e-9):
        raise ValueError(
            f"INV-4 violated: core_growth_cap not monotonic "
            f"(def={d.core_growth_cap}, bal={b.core_growth_cap}, agg={a.core_growth_cap})"
        )


@dataclass(frozen=True)
class EngineConfig:
    """round35 B3-F6 (docs/round35-architecture-review.md §6.3): S4 散落魔法数字单一真相源。

    纯搬家——§5-S4 清单逐项收纳，每个字段默认值与原内联字面量逐一相等（不改任何
    行为）；沿用 ProfileSpec 模式做加载期校验（INV-7 阈值序合理性，见
    :func:`validate_engine_config`）。消费点：allocation_engine 各内联字面量改读
    :data:`ENGINE_CONFIG` 单例。
    """

    # ── 打分 → 权重 ──
    #: _power_law_weights softmax 温度（原 allocation_engine 内联 ``* 0.08``）
    softmax_temperature: float = 0.08
    #: 跨方案重叠惩罚——前序方案已选 symbol 在后续方案 composite 上的减分（round20 P1）
    overlap_penalty: float = -1.5
    #: 卫星层负分质量地板：composite ≤ 此值的卫星候选剔除（round22 #11 回退口径）
    satellite_score_floor: float = -2.0

    # ── C2 关键词修正（F0-5 步骤 E / P1-7 强势板块）──
    c2_defensive_safe_bonus: float = 0.8        # 防御型安全主题奖励
    c2_defensive_risky_penalty: float = -1.5    # 防御型高风险主题惩罚
    c2_aggressive_risky_bonus: float = 1.5      # 进攻型高风险主题奖励
    c2_aggressive_safe_penalty: float = -0.3    # 进攻型安全主题惩罚
    c2_strong_sector_bonus: float = 1.5         # 进攻型当日强势板块动态奖励

    # ── 卫星层科创系配额（F0-5 步骤 C / O17）──
    tech_quota_defensive: float = 0.40          # 防御型权重配额（占卫星预算）
    tech_quota_default: float = 0.50            # 平衡/进攻共用配额
    tech_max_count: int = 2                     # 科创系数量上限

    # ── 核心层结构约束 ──
    #: 核心层大盘宽基数量上限（含强制锚；O16→R101 数量软约束）
    large_cap_wide_basis_limit: int = 4
    #: STRATEGY_META.core_growth_cap 缺失时的兜底（主值仍以 meta 为单源）
    core_growth_cap_fallback: float = 0.40

    # ── 相关性阈值族（INV-7 序：warn ≥ cap ≥ concentration）──
    wide_basis_warn: float = 0.95               # 原 WIDE_BASIS_HIGH_CORR_THRESHOLD（R101 软提示）
    corr_cap: float = 0.9                       # enforce_max_correlation threshold 默认
    corr_combined_weight_cap: float = 0.25      # enforce_max_correlation 合计权重上限
    concentration_avg: float = 0.8              # portfolio_concentration_check avg_threshold 默认
    defensive_wording_median_r: float = 0.35    # rationale 措辞守卫「避险/低相关」允许线


ENGINE_CONFIG = EngineConfig()


def validate_engine_config(cfg: EngineConfig) -> None:
    """round35 B3-F6 INV-7：阈值序与配额方向合理性（加载期 fail-fast）。"""
    if not (cfg.wide_basis_warn >= cfg.corr_cap >= cfg.concentration_avg):
        raise ValueError(
            f"INV-7 violated: correlation threshold order broken "
            f"(wide_basis_warn={cfg.wide_basis_warn}, corr_cap={cfg.corr_cap}, "
            f"concentration_avg={cfg.concentration_avg})"
        )
    if cfg.tech_quota_defensive > cfg.tech_quota_default + 1e-9:
        raise ValueError(
            f"INV-7 violated: defensive tech quota {cfg.tech_quota_defensive} "
            f"> default quota {cfg.tech_quota_default}"
        )
    if not (0.0 < cfg.softmax_temperature <= 1.0):
        raise ValueError(f"INV-7 violated: softmax_temperature={cfg.softmax_temperature} out of (0,1]")


# 加载期构造 + 校验（fail-fast）。导入 budgets 模块即触发，违反不变量直接崩溃。
PROFILE_SPECS: dict[str, ProfileSpec] = build_profile_specs()
validate_profile_specs(PROFILE_SPECS)
validate_engine_config(ENGINE_CONFIG)


def dynamic_layer_budget(risk_profile: str, regime: str) -> dict[str, float]:
    """
    Adjust layer budgets dynamically based on market regime.

    Args:
        risk_profile: One of "defensive", "balanced", "aggressive".
        regime: Market regime label (e.g. "bear", "bull_strong", "range_bound").

    Returns:
        {"core": float, "satellite": float, "defense": float}
        Cash ratio = 1 - sum(values).
    """
    if risk_profile not in STRATEGY_META:
        risk_profile = "balanced"
    base = dict(STRATEGY_META[risk_profile]["layer_budget"])

    # ── Defensive rotate / bear / correction: boost defense ──
    if regime in ("defensive_rotate", "bear", "correction"):
        shift = {"defensive": 0.10, "balanced": 0.08, "aggressive": 0.05}.get(
            risk_profile, 0.05
        )
        base["defense"] = min(base.get("defense", 0.05) + shift, 0.30)
        base["satellite"] = max(base.get("satellite", 0.20) - shift * 0.5, 0.10)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)

        # correction / bear: extra satellite reduction
        if regime in ("correction", "bear"):
            sat_reduce = {
                "defensive": 0.00,
                "balanced": 0.03,
                "aggressive": 0.08,
            }.get(risk_profile, 0.00)
            if sat_reduce > 0:
                base["satellite"] = max(base["satellite"] - sat_reduce, 0.08)
                base["core"] = min(base["core"] + sat_reduce * 0.4, 0.60)

        # bear: extra cash protection
        if regime == "bear":
            cash_boost = {
                "defensive": 0.05,
                "balanced": 0.05,
                "aggressive": 0.10,
            }.get(risk_profile, 0.05)
            base["core"] = max(base["core"] - cash_boost * 0.3, 0.30)
            base["satellite"] = max(base["satellite"] - cash_boost * 0.3, 0.05)

    # ── Strong bull: boost satellite ──
    elif regime in ("bull_strong",):
        shift = {"defensive": 0.05, "balanced": 0.08, "aggressive": 0.10}.get(
            risk_profile, 0.05
        )
        base["satellite"] = min(base.get("satellite", 0.20) + shift, 0.50)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)
        base["defense"] = max(base.get("defense", 0.05) - shift * 0.3, 0.03)

    # ── U6 R2: range_bound 下 balanced 微调（satellite +0.02 / defense -0.02，
    # 配合 R1 预算用满使实际现金收敛到理论值，验收 ≤15%） ──
    elif regime in ("range_bound",) and risk_profile == "balanced":
        base["satellite"] = min(base.get("satellite", 0.30) + 0.02, 0.50)
        base["defense"] = max(base.get("defense", 0.10) - 0.02, 0.03)

    # round22 (#13 INV-6): 进攻型 regime 钳制——防御 ≤0.10、现金 ≤0.10（bear 现金 ≤0.15）。
    # 防止任意 regime 下进攻型被抬到过保守（round21 #13 实证 进攻现金 25%/防御 19%）。
    if risk_profile == "aggressive":
        base["defense"] = min(base.get("defense", 0.05), 0.10)
        cash_clamp = 0.15 if regime == "bear" else 0.10
        total_non_cash = base["core"] + base["satellite"] + base["defense"]
        cash = 1.0 - total_non_cash
        if cash > cash_clamp + 1e-9:
            # 超出现金上限 → 把超额压回核心层（进攻型满仓，核心吸收余量）
            excess = cash - cash_clamp
            base["core"] = min(base["core"] + excess, 0.95)

    return base


def adjust_expected_return(
    risk_profile: str,
    regime: str,
    macro: dict[str, Any] | None = None,
) -> float:
    """
    Adjust expected annual return based on market regime.

    Panic/bear lowers expectations; bull markets raise them.

    Args:
        risk_profile: One of "defensive", "balanced", "aggressive".
        regime: Market regime label.
        macro: Optional macro context (reserved for future refinement).

    Returns:
        Adjusted annual return as a float (e.g. 0.08 for 8%).
    """
    _ = macro  # reserved for future macro-based adjustments
    if risk_profile not in STRATEGY_META:
        risk_profile = "balanced"
    base_return = STRATEGY_META[risk_profile]["expected_return"]

    adjustment: dict[str, float] = {
        "panic": -0.04,
        "bear": -0.03,
        "correction": -0.02,
        "defensive_rotate": -0.01,
        "range_bound": 0.0,
        "bull_weakening": 0.01,
        "bull_strong": 0.02,
    }
    adj = adjustment.get(regime, 0.0)
    return round(max(base_return + adj, 0.02), 4)
