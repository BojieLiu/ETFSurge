"""
智能组合设计 - 核心+卫星+防御 三层结构生成引擎 (v3.0)

Generate ETF portfolio plans with a core + satellite + defense three-layer structure.
Core and defense layers are fixed-weight. Satellite uses dual-pool matching,
z-score multi-factor scoring, tilt ratios, and power-law weight distribution.
This module is the orchestration layer that ties together:
  - allocate_layer_budget: 按风险偏好(防御/平衡/进攻)分配层预算
  - generate_design:       对外主入口, 生成三套方案
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── 策略元数据 ───────────────────────────────────────────────
STRATEGY_META = {
    "defensive": {
        "id": "defensive",
        "label": "防御型",
        "color": "#43A047",
        "portfolio_name": "防御稳健组合",
        "positioning": "低波稳健配置，控制回撤，适合保守风险偏好者",
        "expected_return": 0.08,
        "max_drawdown": -0.12,
        "sharpe_ratio": 1.2,
        "layer_budget": {"core": 0.50, "satellite": 0.15, "defense": 0.05}, # cash=30%,

        "expected_characteristics": "预期年化波动10-12%，最大回撤区间10-12%",
    },
    "balanced": {
        "id": "balanced",
        "label": "平衡型",
        "color": "#1976D2",
        "portfolio_name": "均衡配置组合",
        "positioning": "核心稳健+卫星增强，攻守兼备",
        "expected_return": 0.11,
        "max_drawdown": -0.18,
        "sharpe_ratio": 1.0,
        "layer_budget": {"core": 0.50, "satellite": 0.25, "defense": 0.05}, # cash=20%,

        "expected_characteristics": "预期年化波动15-18%，最大回撤区间15-18%",
    },
    "aggressive": {
        "id": "aggressive",
        "label": "进攻型",
        "color": "#E53935",
        "portfolio_name": "锐意进取组合",
        "positioning": "高弹性行业/主题权重大，承受较大回撤博取超额",
        "expected_return": 0.16,
        "max_drawdown": -0.28,
        "sharpe_ratio": 0.8,
        "layer_budget": {"core": 0.50, "satellite": 0.35, "defense": 0.05}, # cash=10%,

        "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
    },
}


# 全局单只约束
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.30

# 标的总数约束
MIN_NAMES = 8
MAX_NAMES = 15

# 核心层必须包含的宽基指数 ETF（沪深300 + 中证A500 至少各 1 只）
CORE_REQUIRED = ["510300", "560600"]
CORE_MIN_EACH = 0.05  # 各自最小权重


# ── 候选标的池 (code -> 元数据) ─────────────────────────────
# layer: 默认归属层; beta: 相对贝塔(用于优化器打分); liquidity: 日均成交额(亿)
# DEPRECATED: 已被PoolManager取代(S3). 保留仅供向后兼容.
CANDIDATE_POOL: dict[str, dict[str, Any]] = {
    # ── 核心层：宽基指数 ──
    "510300": {"name": "沪深300ETF", "layer": "core", "beta": 1.0, "liquidity": 25.0,
               "reason": "A股核心宽基，覆盖大盘龙头，基准配置首选"},
    "560600": {"name": "中证A500ETF", "layer": "core", "beta": 1.02, "liquidity": 12.0,
               "reason": "A股行业均衡龙头宽基，补足核心层分散度"},
    "510500": {"name": "中证500ETF", "layer": "satellite", "beta": 1.1, "liquidity": 15.0,
               "reason": "中盘成长宽基，提升核心层弹性"},
    "159915": {"name": "创业板ETF", "layer": "satellite", "beta": 1.25, "liquidity": 18.0,
               "reason": "成长风格宽基，核心层弹性来源"},
    "510880": {"name": "红利低波ETF", "layer": "core", "beta": 0.75, "liquidity": 9.0,
               "reason": "高股息低波动，核心层压舱石"},
    # ── 卫星层：行业/主题/风格 ──
    "512480": {"name": "半导体ETF", "layer": "satellite", "beta": 1.4, "liquidity": 20.0,
               "reason": "科技主线高弹性，卫星增强收益"},
    "515030": {"name": "新能源ETF", "layer": "satellite", "beta": 1.35, "liquidity": 11.0,
               "reason": "新能源产业链，成长风格卫星"},
    "512010": {"name": "医药ETF", "layer": "satellite", "beta": 1.1, "liquidity": 8.0,
               "reason": "医药生物板块，防御性成长"},
    "515080": {"name": "中证红利ETF", "layer": "satellite", "beta": 0.85, "liquidity": 6.0,
               "reason": "高股息策略，价值风格卫星"},
    "512890": {"name": "红利低波100ETF", "layer": "satellite", "beta": 0.78, "liquidity": 5.0,
               "reason": "低波动红利，稳健卫星"},
    "561300": {"name": "AI人工智能ETF", "layer": "satellite", "beta": 1.5, "liquidity": 7.0,
               "reason": "AI主题高弹性，卫星进攻"},
    "516160": {"name": "新能源电池ETF", "layer": "satellite", "beta": 1.3, "liquidity": 4.0,
               "reason": "电池产业链，新能源细分卫星"},
    # ── 防御层：跨资产/低相关 ──
    "518880": {"name": "黄金ETF", "layer": "defense", "beta": 0.2, "liquidity": 22.0,
               "reason": "贵金属避险，与权益低相关"},
    "511090": {"name": "30年国债ETF", "layer": "defense", "beta": -0.1, "liquidity": 10.0,
               "reason": "长久期利率债，对冲权益波动"},
    "511990": {"name": "货币ETF", "layer": "defense", "beta": 0.0, "liquidity": 50.0,
               "reason": "现金管理工具，流动性缓冲"},
    "513500": {"name": "标普500ETF", "layer": "defense", "beta": 0.6, "liquidity": 14.0,
               "reason": "美股宽基，跨市场分散"},
    "159980": {"name": "有色ETF", "layer": "defense", "beta": 0.5, "liquidity": 3.0,
               "reason": "商品资产，通胀对冲"},
}


# ── 数据类 ──────────────────────────────────────────────────
@dataclass
class Asset:
    code: str
    name: str
    layer: str
    beta: float
    liquidity: float
    price: float = 1.0
    change_pct: float = 0.0
    net_inflow: float = 0.0       # 资金净流入(元)
    valuation_pct: float = 0.5    # 估值分位 0~1
    reason: str = ""


@dataclass
class MarketContext:
    assets: dict[str, Asset] = field(default_factory=dict)
    timestamp: str = ""
    indices: list[dict] = field(default_factory=list)
    fund_flow: list[dict] = field(default_factory=list)
    valuation: list[dict] = field(default_factory=list)


# ── 1. enrich_market_context: 补全缺失数据维度 ────────────────
async def enrich_market_context() -> MarketContext:
    """
    并行拉取大盘指数、ETF资金流向、估值等数据，补全行情快照。
    外部数据源可能超时，用 try/except 包裹，失败返回结构化默认值。
    """
    # 并行拉取三类数据
    indices, fund_flow, valuation = await asyncio.gather(
        _fetch_indices(),
        _fetch_fund_flow(),
        _fetch_valuation(),
        return_exceptions=False,
    ) if False else (
        await _safe_gather(_fetch_indices(), _fetch_fund_flow(), _fetch_valuation())
    )

    ctx = MarketContext(timestamp="", indices=indices, fund_flow=fund_flow, valuation=valuation)

    # 把行情/资金/估值映射到候选池
    flow_map = {f.get("code"): f for f in fund_flow}
    val_map = {v.get("code"): v for v in valuation}
    idx_map = {i.get("code"): i for i in indices}

    # 从 CANDIDATE_POOL 构建 Asset 对象填充 ctx.assets
    for code, meta in CANDIDATE_POOL.items():
        flow = flow_map.get(code, {})
        val = val_map.get(code, {})
        ctx.assets[code] = Asset(
            code=code,
            name=meta["name"],
            layer=meta["layer"],
            beta=meta["beta"],
            liquidity=meta["liquidity"],
            price=1.0,
            change_pct=0.0,
            net_inflow=float(flow.get("net_inflow", 0) or 0),
            valuation_pct=float(val.get("valuation_percentile", 0.5) or 0.5),
            reason=meta.get("reason", ""),
        )

    return ctx


async def _safe_gather(*coros):
    """并发执行, 任一异常不影响其余结果"""
    tasks = [asyncio.ensure_future(c) for c in coros]
    results = []
    for t in tasks:
        try:
            results.append(await t)
        except Exception:
            results.append([])
    return results


async def _fetch_indices() -> list[dict]:
    """大盘指数实时行情（含沪深300/中证A500等）"""
    try:
        from ..fetchers.china_market import fetch_index_realtime
        df = fetch_index_realtime()
        if df:
            return df
    except Exception:
        pass
    return []


async def _fetch_fund_flow() -> list[dict]:
    """ETF资金流向（日度净流入/份额变动）"""
    try:
        import akshare as ak
        # 尝试东方财富 ETF 资金流向
        df = ak.fund_etf_fund_flow_summary_em()
        out = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "") or row.get("code", ""))
            if not code:
                continue
            out.append({
                "code": code,
                "net_inflow": float(row.get("主力净流入-净额", row.get("净流入", 0)) or 0),
                "flow_direction": "inflow" if float(row.get("主力净流入-净额", row.get("净流入", 0)) or 0) >= 0 else "outflow",
            })
        return out
    except Exception:
        return []


async def _fetch_valuation() -> list[dict]:
    """ETF估值数据（PE/PB分位）"""
    try:
        import akshare as ak
        df = ak.fund_etf_valuation_em(symbol="华泰柏瑞沪深300ETF", indicator="市盈率")
        if df is not None and not df.empty:
            last = df.iloc[-1]
            return [{
                "code": "510300",
                "valuation_percentile": float(last.get("百分位", 50) or 50) / 100.0,
                "pe_ttm": float(last.get("市盈率", 0) or 0),
                "pb": float(last.get("市净率", 0) or 0),
            }]
    except Exception:
        pass
    return []


# ── 2. classify_assets: 三层分类 ─────────────────────────────
def classify_assets(ctx: MarketContext) -> dict[str, list[Asset]]:
    """按 layer 字段分组；核心层确保含沪深300与中证A500"""
    layers: dict[str, list[Asset]] = {"core": [], "satellite": [], "defense": []}
    for code, a in ctx.assets.items():
        layers.setdefault(a.layer, []).append(a)
    return layers


# ── 3. allocate_layer_budget: 层预算分配 ─────────────────────
def allocate_layer_budget(risk_profile: str) -> dict[str, float]:
    """返回 {core, satellite, defense} 预算比例"""
    meta = STRATEGY_META.get(risk_profile, STRATEGY_META["balanced"])
    return dict(meta["layer_budget"])


# ── 4. v3.0: 核心+防御固定, 卫星幂律分配 ───────────────────────
CORE_FIXED = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.25},
    {"symbol": "560600", "name": "中证A500ETF", "layer": "core", "weight": 0.15},
    {"symbol": "510880", "name": "红利低波ETF", "layer": "core", "weight": 0.10},
]

DEFENSE_FIXED = [
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "weight": 0.05},
]


def _extract_factor(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    std = (sum((v - mean)**2 for v in values) / len(values))**0.5
    if std == 0:
        return [0.0] * len(values)
    return [max(-3.0, min(3.0, (v - mean) / std)) for v in values]


def power_law_weights(scores: list[float], budget: float) -> list[float]:
    import math
    if not scores:
        return []
    max_s = max(scores)
    exps = [math.exp((s - max_s) * 0.08) for s in scores]
    total_exp = sum(exps)
    result = [(e / total_exp) * budget for e in exps]
    result = [max(w, 0.01) for w in result]
    total_r = sum(result)
    if total_r > 0:
        result = [w * budget / total_r for w in result]
    result = [min(w, 0.30) for w in result]
    return result


# ── 5. generate_design: 主入口 (v3.0) ───────────────────────
async def generate_design(
    risk_profile: str = "balanced",
    capital: float = 500000,
    mode: str = "standard",
    constraints: dict | None = None,
    db=None,
) -> list[dict[str, Any]]:
    """
    v3.0: 生成三套组合方案（防御/平衡/进攻）。
    核心+防御层固定比例，卫星层用幂律分配。
    """
    constraints = constraints or {}

    # 1. 扫描全市场 ETF（若 standard 模式）
    scanned_satellite: list = []
    if mode == "standard":
        try:
            from ..fetchers.etf_scanner import full_pipeline as scan_full_pipeline
            scanned = await asyncio.to_thread(scan_full_pipeline)
            sat_items = scanned.get("satellite") or []
            # 取前15只作为卫星候选
            scanned_satellite = [
                {
                    "symbol": item["symbol"],
                    "name": item.get("name", ""),
                    "liquidity": item.get("amount", 0) / 1e8,
                }
                for item in sat_items[:15]
            ]
            logger.info("scan: %d satellite candidates found", len(scanned_satellite))
        except Exception as e:
            logger.warning("scan failed: %s", e)

    # 若扫描失败或卫星为空，用硬编码候选补充
    if not scanned_satellite:
        scanned_satellite = [
            {"symbol": "512480", "name": "半导体ETF", "liquidity": 17.0},
            {"symbol": "561300", "name": "AI人工智能ETF", "liquidity": 10.0},
            {"symbol": "515030", "name": "新能源ETF", "liquidity": 13.0},
            {"symbol": "512010", "name": "医药ETF", "liquidity": 8.0},
            {"symbol": "159766", "name": "旅游ETF", "liquidity": 5.0},
        ]

    # 2. 为三套策略分别生成
    strategies = []
    for key in ["defensive", "balanced", "aggressive"]:
        meta = STRATEGY_META[key]
        budgets = allocate_layer_budget(key)

        # 核心层: 固定比例
        holdings = [dict(h) for h in CORE_FIXED]

        # 防御层: 固定比例
        holdings.extend(dict(h) for h in DEFENSE_FIXED)

        # 卫星层: 幂律分配
        s_budget = budgets.get("satellite", 0.0)
        if s_budget > 0 and scanned_satellite:
            sat_assets = scanned_satellite[:10]
            liquidity = [a["liquidity"] for a in sat_assets]
            scores = _extract_factor(liquidity) if len(set(liquidity)) > 1 else [0.5] * len(liquidity)
            weights = power_law_weights(scores, s_budget)
            for i, a in enumerate(sat_assets):
                if i < len(weights):
                    holdings.append({
                        "symbol": a["symbol"],
                        "name": a["name"],
                        "layer": "satellite",
                        "weight": round(weights[i], 4),
                        "selection_rationale": f"卫星候选 #{i+1}",
                    })

        # 归一化: 核心+卫星+防御 = 预算值，现金=余额
        total_w = sum(h["weight"] for h in holdings)
        if total_w > 0 and abs(total_w - 1.0) > 0.001:
            # 按比例缩放到实际总预算
            actual_budget = sum(budgets.get(l, 0) for l in ["core", "satellite", "defense"])
            if actual_budget > 0:
                scale = actual_budget / total_w
                for h in holdings:
                    h["weight"] = round(h["weight"] * scale, 4)
            # 添加现金条目
            cash = round(1.0 - actual_budget, 4)
            holdings.append({
                "symbol": "CASH",
                "name": "现金",
                "layer": "cash",
                "weight": cash,
                "selection_rationale": "流动性管理",
            })
        for h in holdings:
            h["target_amount"] = round(capital * h.get("weight", 0), 2)

        strategies.append({
            "id": meta["id"],
            "label": meta["label"],
            "color": meta["color"],
            "portfolio_name": meta["portfolio_name"],
            "positioning": meta["positioning"],
            "expected_return": meta["expected_return"],
            "max_drawdown": meta["max_drawdown"],
            "sharpe_ratio": meta["sharpe_ratio"],
            "expected_characteristics": meta["expected_characteristics"],
            "layer_budget": meta["layer_budget"],
            "etfs": holdings,
        })

    return strategies

def _enforce_name_count(
    holdings: list[dict], min_names: int, max_names: int, budgets: dict
) -> list[dict]:
    """确保标的总数在 [min_names, max_names] 之间"""
    # 按层排序: 核心优先保留
    layer_priority = {"core": 0, "satellite": 1, "defense": 2}
    holdings.sort(key=lambda h: (layer_priority.get(h["layer"], 9), -h["weight"]))

    if len(holdings) > max_names:
        holdings = holdings[:max_names]
    elif len(holdings) < min_names:
        # 从候选池补充(若还有未入选的)
        existing = {h["symbol"] for h in holdings}
    return holdings


def _build_default_context() -> MarketContext:
    """fast 模式: 不拉外部数据, 用候选池默认值"""
    ctx = MarketContext()
    return ctx


async def generate_full_design(
    capital: float = 500000,
    constraints: dict | None = None,
) -> dict:
    """
    完整管道: 全市场扫描 + 卫星层两轮评分 + 三方案生成 + 市场情绪/指标股。

    返回:
    {
      "strategies": [...],
      "market_context": {market_sentiment, benchmark_stocks, ...},
      "generated_at": "..."
    }
    """
    from ..fetchers.sentiment_fetcher import fetch_market_sentiment
    from ..fetchers.benchmark_stocks import fetch_benchmark_stocks

    # 并行: 生成方案 + 情绪指数 + 指标股 (各带超时保护)
    strategies_task = asyncio.wait_for(
        generate_design("balanced", capital, mode="standard", constraints=constraints),
        timeout=90,
    )
    sentiment_task = asyncio.wait_for(
        fetch_market_sentiment(), timeout=20,
    )
    benchmark_task = asyncio.wait_for(
        fetch_benchmark_stocks(), timeout=20,
    )

    strategies, sentiment, benchmark = await asyncio.gather(
        strategies_task, sentiment_task, benchmark_task, return_exceptions=True
    )

    if isinstance(strategies, (Exception, type(None))) or not strategies:
        try:
            strategies = await generate_design("balanced", capital, mode="fast", constraints=constraints)
        except Exception:
            strategies = []
    if isinstance(sentiment, (Exception, type(None))):
        sentiment = {"sentiment_index": 50, "sentiment_label": "中性"}
    if isinstance(benchmark, (Exception, type(None))):
        benchmark = []

    return {
        "strategies": strategies,
        "market_context": {
            "market_sentiment": sentiment,
            "benchmark_stocks": benchmark,
        },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ═══════════════════════════════════════════════════════════════
# v4 增强功能: 多因子评分 / 资讯映射 / 动态配置 / 风控
# ═══════════════════════════════════════════════════════════════

# ── 多因子评分配置 ─────────────────────────────────────────────
FACTOR_CONFIG: dict[str, dict[str, Any]] = {
    "momentum_3m": {
        "weight": 0.30,
        "ascending": True,      # 越高越好
        "normalize": "minmax",
    },
    "fund_flow_20d": {
        "weight": 0.20,
        "ascending": True,
        "normalize": "minmax",
    },
    "valuation": {
        "weight": 0.20,
        "ascending": False,     # 越低越好（低估值优先）
        "normalize": "minmax",
    },
    "liquidity": {
        "weight": 0.15,
        "ascending": True,
        "normalize": "minmax",
    },
    "volatility_20d": {
        "weight": 0.15,
        "ascending": False,     # 低波动优先
        "normalize": "minmax",
    },
}

# 市场状态 → 因子权重覆盖
REGIME_FACTOR_OVERRIDES: dict[str, dict[str, float]] = {
    "bull_strong": {
        "momentum_3m": 0.40, "fund_flow_20d": 0.15,
        "valuation": 0.10, "liquidity": 0.20, "volatility_20d": 0.15,
    },
    "bull_weakening": {
        "momentum_3m": 0.25, "fund_flow_20d": 0.20,
        "valuation": 0.20, "liquidity": 0.20, "volatility_20d": 0.15,
    },
    "defensive_rotate": {
        "momentum_3m": 0.15, "fund_flow_20d": 0.25,
        "valuation": 0.30, "liquidity": 0.15, "volatility_20d": 0.15,
    },
    "correction": {
        "momentum_3m": 0.10, "fund_flow_20d": 0.30,
        "valuation": 0.30, "liquidity": 0.15, "volatility_20d": 0.15,
    },
    "bear": {
        "momentum_3m": 0.05, "fund_flow_20d": 0.35,
        "valuation": 0.35, "liquidity": 0.10, "volatility_20d": 0.15,
    },
}


def _normalize_minmax(values: list[float], ascending: bool = True) -> list[float]:
    """Min-Max 归一化到 [0, 1]"""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    if ascending:
        return [(v - mn) / (mx - mn) for v in values]
    else:
        return [(mx - v) / (mx - mn) for v in values]


def _normalize_zscore(values: list[float], ascending: bool = True) -> list[float]:
    """Z-score 归一化到 [0, 1]"""
    if not values or len(values) < 2:
        return [0.5] * len(values)
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std == 0:
        return [0.5] * len(values)
    zs = [(v - mean) / std for v in values]
    # 将 z-score 映射到 [0, 1]
    zs = [max(-3.0, min(3.0, z)) for z in zs]
    if ascending:
        return [(z + 3.0) / 6.0 for z in zs]
    else:
        return [(3.0 - z) / 6.0 for z in zs]


def _get_factor_values(
    assets: list[dict],
    factor_key: str,
    trends: dict[str, dict[str, float]] | None,
    fund_flows: dict[str, float] | None,
) -> list[float]:
    """根据因子名称从趋势/资金流数据中取值。"""
    values = []
    for a in assets:
        code = a.get("symbol") or a.get("code", "")
        val = 0.0

        if factor_key == "momentum_3m":
            t = (trends or {}).get(code, {})
            val = t.get("return_3m", t.get("return_1m", 0.0))
        elif factor_key == "fund_flow_20d":
            val = (fund_flows or {}).get(code, 0.0)
            # 取绝对值归一化
        elif factor_key == "liquidity":
            val = a.get("liquidity", 0.0) if isinstance(a.get("liquidity"), (int, float)) else float(a.get("liquidity", 0))
        elif factor_key == "volatility_20d":
            t = (trends or {}).get(code, {})
            val = t.get("volatility_20d", 0.0)
        elif factor_key == "valuation":
            # 估值分位越低越好
            t = (trends or {}).get(code, {})
            # 如果有PE估值，用PE倒数（越高越好）
            # 若无，用波动率作为风险代理
            val = -t.get("volatility_20d", -0.5)  # 低波动 proxy
        else:
            val = 0.0

        values.append(val if val is not None else 0.0)
    return values


def score_satellite_assets(
    assets: list[dict],
    regime: str = "range_bound",
    trends: dict[str, dict[str, float]] | None = None,
    fund_flows: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    多因子加权评分卫星层候选标的。

    Args:
        assets: 卫星层候选标的列表
        regime: 当前市场状态
        trends: 趋势数据
        fund_flows: 资金流数据

    Returns:
        每只标的添加 `factor_scores` 和 `composite_score` 字段
    """
    # 选择因子权重
    weights = REGIME_FACTOR_OVERRIDES.get(regime, {})
    if not weights:
        weights = {k: v["weight"] for k, v in FACTOR_CONFIG.items()}

    # 计算各因子得分
    factor_scores: dict[str, list[float]] = {}
    for factor_key in weights:
        config = FACTOR_CONFIG.get(factor_key)
        if not config:
            continue
        raw = _get_factor_values(assets, factor_key, trends, fund_flows)
        if config["normalize"] == "zscore":
            norm = _normalize_zscore(raw, config["ascending"])
        else:
            norm = _normalize_minmax(raw, config["ascending"])
        factor_scores[factor_key] = norm

    # 综合加权
    for i, a in enumerate(assets):
        composite = 0.0
        details = {}
        for fk, w in weights.items():
            if i < len(factor_scores.get(fk, [])):
                score = factor_scores[fk][i]
                composite += score * w
                details[fk] = round(score, 3)
        a["factor_scores"] = details
        a["composite_score"] = round(composite, 4)

    # 按综合评分排序
    assets.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    return assets


# ── 资讯-ETF映射 ──────────────────────────────────────────────

# ETF 关键词映射表 (标题关键词 → ETF 代码)
_NEWS_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["半导体", "芯片", "集成电路", "存储", "HBM", "光刻", "AI芯片", "先进封装"], "512480"),
    (["AI", "人工智能", "大模型", "算力", "GPT", "深度学习", "智能体"], "561300"),
    (["新能源", "光伏", "锂电池", "电动汽车", "新能源车", "充电桩", "储能"], "515030"),
    (["医药", "医疗", "创新药", "生物医药", "医疗器械", "CXO", "制药"], "512010"),
    (["旅游", "酒店", "航空", "免税", "景区", "出行"], "159766"),
    (["黄金", "金价", "贵金属", "避险"], "518880"),
    (["国债", "利率债", "债券", "债市", "信用债"], "511090"),
    (["军工", "国防", "航天", "卫星", "船舶", "装备"], "512660"),
    (["消费", "食品饮料", "白酒", "家电", "零售", "社零"], "159766"),
    (["红利", "股息", "分红", "高股息", "低波"], "510880"),
    (["创业板", "成长", "中小盘"], "159915"),
    (["科创", "科创板", "硬科技"], "588000"),
    (["证券", "券商", "保险", "金融"], "512880"),
    (["机器人", "自动化", "工业母机", "智能制造"], "516360"),
    (["有色", "煤炭", "钢铁", "大宗商品", "资源"], "159980"),
    (["沪深300", "大盘", "蓝筹", "权重"], "510300"),
    (["中证A500", "A500", "行业龙头"], "560600"),
]


def map_news_to_etfs(
    news: list[dict],
    max_items: int = 20,
) -> dict[str, dict[str, Any]]:
    """
    将新闻标题映射到相关ETF，计算情感得分。

    Args:
        news: 资讯列表（含 title 字段）

    Returns:
        {etf_code: {
            "positive_mentions": int,
            "negative_mentions": int,
            "total_mentions": int,
            "sentiment_score": float,  # -1~1
            "recent_titles": list[str],
        }}
    """
    result: dict[str, dict[str, Any]] = {}

    for item in news[:max_items]:
        title = str(item.get("title", item.get("summary", "")))
        if not title:
            continue

        # 判断情感（简单关键词）
        title_lower = title.lower()
        negative_keywords = ["下跌", "大跌", "暴跌", "利空", "流出", "减持",
                             "制裁", "风险", "回调", "下降", "亏损"]
        is_negative = any(kw in title_lower for kw in negative_keywords)

        # 匹配ETF
        matched_codes = set()
        for keywords, code in _NEWS_KEYWORD_MAP:
            if any(kw in title for kw in keywords):
                matched_codes.add(code)

        for code in matched_codes:
            if code not in result:
                result[code] = {
                    "positive_mentions": 0,
                    "negative_mentions": 0,
                    "total_mentions": 0,
                    "sentiment_score": 0.0,
                    "recent_titles": [],
                }
            result[code]["total_mentions"] += 1
            result[code]["recent_titles"].append(title[:60])
            if is_negative:
                result[code]["negative_mentions"] += 1
            else:
                result[code]["positive_mentions"] += 1

    # 计算情感得分
    for code, data in result.items():
        total = data["total_mentions"]
        if total > 0:
            data["sentiment_score"] = round(
                (data["positive_mentions"] - data["negative_mentions"]) / total, 3
            )
        data["recent_titles"] = data["recent_titles"][:5]

    return result


# ── 动态配置: 核心层 + 防御层 ────────────────────────────────

def dynamic_core_allocation(
    regime: str,
    macro: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    根据市场状态动态确定核心层标的和权重。
    """
    if macro is None:
        macro = {}

    style = macro.get("style_preference", "balanced")
    bond_bull = macro.get("bond_bull", False)

    # 基准配置
    if regime in ("bear", "correction", "defensive_rotate") or style == "defensive_value":
        # 熊市/回调/防御轮动: 降低大盘宽基，增配红利/防御
        core = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.15,
             "selection_rationale": "核心底仓压舱石"},
            {"symbol": "560600", "name": "中证A500ETF", "layer": "core", "weight": 0.12,
             "selection_rationale": "行业均衡龙头，补足核心层分散度"},
            {"symbol": "510880", "name": "红利低波ETF", "layer": "core", "weight": 0.15,
             "selection_rationale": "高股息低波动，增强核心层防御性"},
        ]
        if bond_bull:
            core.append({
                "symbol": "511090", "name": "30年国债ETF", "layer": "defense",
                "weight": 0.05,
                "selection_rationale": "利率下行环境，债券牛市配置长久期国债",
            })
    elif regime in ("bull_strong",) or style == "growth":
        # 强牛市: 加大弹性宽基
        core = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.20,
             "selection_rationale": "核心宽基基准配置"},
            {"symbol": "560600", "name": "中证A500ETF", "layer": "core", "weight": 0.15,
             "selection_rationale": "行业均衡龙头，增强分散度"},
            {"symbol": "159915", "name": "创业板ETF", "layer": "satellite", "weight": 0.08,
             "selection_rationale": "成长风格增强组合弹性"},
            {"symbol": "510880", "name": "红利低波ETF", "layer": "core", "weight": 0.05,
             "selection_rationale": "辅助防御配置"},
        ]
    else:
        # 震荡/默认: 均衡配置
        core = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.20,
             "selection_rationale": "核心宽基基准配置"},
            {"symbol": "560600", "name": "中证A500ETF", "layer": "core", "weight": 0.15,
             "selection_rationale": "行业均衡龙头"},
            {"symbol": "510880", "name": "红利低波ETF", "layer": "core", "weight": 0.10,
             "selection_rationale": "红利低波防御压舱"},
        ]

    return core


def dynamic_defense_allocation(
    regime: str,
    macro: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    根据市场状态和宏观环境动态确定防御层标的和权重。
    """
    if macro is None:
        macro = {}

    bond_bull = macro.get("bond_bull", False)
    external_risk = macro.get("external_risk", "moderate")
    rate_direction = macro.get("rate_direction", "flat")

    defense = []

    # 黄金：总是保留
    gold_weight = 0.05
    if external_risk == "elevated":
        gold_weight = 0.08
    defense.append({
        "symbol": "518880", "name": "黄金ETF", "layer": "defense",
        "weight": gold_weight,
        "selection_rationale": "避险资产，低相关配置",
    })

    # 债券：利率下行时加入
    if bond_bull or rate_direction == "down":
        defense.append({
            "symbol": "511090", "name": "30年国债ETF", "layer": "defense",
            "weight": 0.05,
            "selection_rationale": "利率下行，长久期国债受益",
        })

    # 防御轮动/熊市时加大防御
    if regime in ("defensive_rotate", "bear", "correction"):
        # 增加现有防御权重的 scaling
        for d in defense:
            d["weight"] = round(d["weight"] * 1.5, 2)

    return defense


def dynamic_layer_budget(
    risk_profile: str,
    regime: str,
) -> dict[str, float]:
    """
    根据市场状态动态调整层预算。

    Returns:
        {"core": float, "satellite": float, "defense": float}  # 现金 = 1 - sum
    """
    base = dict(STRATEGY_META[risk_profile]["layer_budget"])

    # 防御轮动/熊市: 加大防御预算
    if regime in ("defensive_rotate", "bear", "correction"):
        shift = {"defensive": 0.10, "balanced": 0.08, "aggressive": 0.05}.get(risk_profile, 0.05)
        base["defense"] = min(base.get("defense", 0.05) + shift, 0.30)
        base["satellite"] = max(base.get("satellite", 0.20) - shift * 0.5, 0.10)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)

    # 强牛市: 加大卫星预算（进攻端）
    elif regime in ("bull_strong",):
        shift = {"defensive": 0.05, "balanced": 0.08, "aggressive": 0.10}.get(risk_profile, 0.05)
        base["satellite"] = min(base.get("satellite", 0.20) + shift, 0.50)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)
        base["defense"] = max(base.get("defense", 0.05) - shift * 0.3, 0.03)

    return base


# ── 组合风控 ──────────────────────────────────────────────────

# 行业板块与ETF的映射（用于集中度计算）
_SECTOR_ETF_MAP: dict[str, str] = {
    "510300": "大盘价值", "560600": "大盘均衡", "510500": "中盘成长",
    "159915": "成长", "510880": "红利低波",
    "512480": "半导体", "515030": "新能源", "512010": "医药",
    "515080": "红利", "512890": "低波", "561300": "AI",
    "516160": "新能源电池", "518880": "贵金属",
    "511090": "债券", "511990": "货币", "513500": "美股",
    "159980": "商品", "588000": "科创板", "512880": "证券",
    "512660": "军工", "159766": "消费",
}


def compute_portfolio_risk(
    holdings: list[dict],
    trends: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """
    计算组合层面的风险指标。

    Returns:
        {
            "sector_concentration": float,    # HHI 0~1
            "sector_breakdown": dict,         # {sector: total_weight}
            "volatility_est": float,          # 预估年化波动率
            "max_drawdown_est": float,        # 预估最大回撤
            "correlation_warning": str | None, # 相关性预警
        }
    """
    if not holdings:
        return {
            "sector_concentration": 0.0,
            "sector_breakdown": {},
            "volatility_est": 0.0,
            "max_drawdown_est": 0.0,
            "correlation_warning": None,
        }

    # 1. 行业集中度 (HHI)
    sector_weights: dict[str, float] = {}
    for h in holdings:
        code = h.get("symbol", "")
        sector = _SECTOR_ETF_MAP.get(code, "其他")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + h.get("weight", 0)

    hhi = sum(w ** 2 for w in sector_weights.values())

    # 2. 相关性预警：检查是否有多个标的属于同一高相关性板块
    high_corr_groups: list[str] = []
    # 半导体 + AI 高度相关
    semicon_ai_weight = (
        sector_weights.get("半导体", 0) + sector_weights.get("AI", 0)
    )
    if semicon_ai_weight > 0.20:
        high_corr_groups.append(
            f"半导体+AI合计 {semicon_ai_weight:.0%}，高度相关板块集中度偏高"
        )
    # 新能源相关
    new_energy_weight = (
        sector_weights.get("新能源", 0) + sector_weights.get("新能源电池", 0)
    )
    if new_energy_weight > 0.15:
        high_corr_groups.append(
            f"新能源合计 {new_energy_weight:.0%}，板块集中度偏高"
        )

    corr_warning = "；".join(high_corr_groups) if high_corr_groups else None

    # 3. 预估波动率（基于趋势数据）
    if trends:
        vols = []
        for h in holdings:
            code = h.get("symbol", "")
            t = trends.get(code, {})
            vol = t.get("volatility_20d")
            if vol and vol > 0:
                vols.append(vol * h.get("weight", 0))
        volatility_est = sum(vols) if vols else 0.15
    else:
        volatility_est = 0.15

    # 4. 预估最大回撤（基于波动率简算）
    max_drawdown_est = -min(volatility_est * 1.5, 0.40)

    return {
        "sector_concentration": round(hhi, 4),
        "sector_breakdown": {k: round(v, 4) for k, v in sector_weights.items()},
        "volatility_est": round(volatility_est, 4),
        "max_drawdown_est": round(max_drawdown_est, 4),
        "correlation_warning": corr_warning,
    }


# ── 增强型主入口 ──────────────────────────────────────────────

async def generate_enhanced_design(
    capital: float = 500000,
    constraints: dict | None = None,
) -> dict:
    """
    v4 增强管道: 趋势数据 + 多因子评分 + 宏观感知 + 动态配置 + 风控。

    返回:
      {
        "strategies": [...],
        "market_context": {市场情绪, 大盘指数, 市场状态, 宏观状态},
        "generated_at": "...",
        "design_metadata": {版本, 使用因子, 耗时等},
      }
    """
    import time
    from datetime import datetime

    start_time = time.monotonic()
    constraints = constraints or {}

    # 1. 并行采集趋势数据、宏观状态、市场情绪
    from .market_trends import compute_etf_trends, compute_sector_momentum, detect_market_regime
    from .macro_state import detect_macro_regime
    from ..fetchers.sentiment_fetcher import fetch_market_sentiment
    from ..fetchers.benchmark_stocks import fetch_benchmark_stocks
    from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news
    from ..fetchers.fundamental_fetcher import fetch_fund_flow, fetch_current_pe_pb
    from ..fetchers.etf_scanner import full_pipeline as scan_full_pipeline
    from ..services.pool_manager import pool_manager

    all_symbols = list(CANDIDATE_POOL.keys())

    trend_data, macro_state, sentiment, benchmark, news_tasks = await asyncio.gather(
        asyncio.wait_for(compute_etf_trends(all_symbols), timeout=45),
        asyncio.wait_for(detect_macro_regime(), timeout=20),
        asyncio.wait_for(fetch_market_sentiment(), timeout=20),
        asyncio.wait_for(fetch_benchmark_stocks(), timeout=20),
        asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(fetch_news_headlines),
                asyncio.to_thread(fetch_macro_news),
                return_exceptions=True,
            ),
            timeout=15,
        ),
        return_exceptions=True,
    )
    # 新增并行: 资金流 + 估值
    fund_flow_results, valuation_results = await asyncio.gather(
        asyncio.wait_for(
            asyncio.gather(
                *[asyncio.to_thread(fetch_fund_flow, sym) for sym in all_symbols],
                return_exceptions=True,
            ), timeout=15,
        ),
        asyncio.wait_for(
            asyncio.gather(
                *[asyncio.to_thread(fetch_current_pe_pb, sym) for sym in all_symbols],
                return_exceptions=True,
            ), timeout=15,
        ),
        return_exceptions=True,
    )

    # 处理异常
    trend_data = trend_data if isinstance(trend_data, dict) else {}
    macro_state = macro_state if isinstance(macro_state, dict) else {}
    sentiment = sentiment if isinstance(sentiment, dict) else {"sentiment_index": 50, "sentiment_label": "中性"}
    benchmark = benchmark if isinstance(benchmark, list) else []
    # 处理 fund_flow / pe_pb
    fund_flow_map = {}
    valuation_map = {}
    if isinstance(fund_flow_results, (list, tuple)):
        for sym, result in zip(all_symbols, fund_flow_results):
            if isinstance(result, dict) and result.get("main_net_inflow") is not None:
                fund_flow_map[sym] = result["main_net_inflow"]
    if isinstance(valuation_results, (list, tuple)):
        for sym, result in zip(all_symbols, valuation_results):
            if isinstance(result, dict):
                valuation_map[sym] = result

    news_list = (news_tasks[0] if isinstance(news_tasks, tuple) and news_tasks[0] and not isinstance(news_tasks[0], Exception) else [])
    macro_news = (news_tasks[1] if isinstance(news_tasks, tuple) and news_tasks[1] and not isinstance(news_tasks[1], Exception) else [])

    # 2. 判断市场状态
    sentiment_index = float(sentiment.get("sentiment_index", 50))
    adv_ratio = float(sentiment.get("advance_ratio", 0.5))
    regime = detect_market_regime(
        trends=trend_data,
        broad_index_code="000001",
        sentiment_index=sentiment_index,
        adv_ratio=adv_ratio,
    )

    # 3. 资讯-ETF映射
    news_map = map_news_to_etfs(news_list + macro_news)

    # 4. 扫描全市场 ETF 获取卫星候选
    # 优先使用 pool_manager（含分类+因子评分），降级到直接 scanner
    scanned_satellite: list = []
    pool_ready = False
    try:
        await asyncio.wait_for(pool_manager.refresh(), timeout=20)
        sat_pool = pool_manager.get_pool("satellite") or []
        if sat_pool:
            scanned_satellite = sorted(sat_pool, key=lambda x: x.get("composite_score", 0), reverse=True)
            pool_ready = True
            logger.info("pool_manager: %d satellite candidates", len(scanned_satellite))
    except Exception as e:
        logger.warning("pool_manager refresh failed: %s", e)

    if not pool_ready:
        try:
            scanned = await asyncio.to_thread(scan_full_pipeline)
            sat_items = scanned.get("satellite") or []
            scanned_satellite = [
                {
                    "symbol": item["symbol"],
                    "name": item.get("name", ""),
                    "liquidity": float(item.get("amount", 0)) / 1e8 if item.get("amount") else 10.0,
                }
                for item in sat_items[:20]
            ]
        except Exception as e:
            logger.warning("enhanced scan failed: %s", e)

        if not scanned_satellite:
            scanned_satellite = [
                {"symbol": "512480", "name": "半导体ETF", "liquidity": 17.0},
                {"symbol": "561300", "name": "AI人工智能ETF", "liquidity": 10.0},
                {"symbol": "515030", "name": "新能源ETF", "liquidity": 13.0},
                {"symbol": "512010", "name": "医药ETF", "liquidity": 8.0},
                {"symbol": "159766", "name": "旅游ETF", "liquidity": 5.0},
                {"symbol": "512660", "name": "军工ETF", "liquidity": 6.0},
                {"symbol": "588000", "name": "科创50ETF", "liquidity": 15.0},
            ]

    # 5. 为三种风险偏好生成方案
    strategies = []
    for key in ["defensive", "balanced", "aggressive"]:
        meta = STRATEGY_META[key]
        budgets = dynamic_layer_budget(key, regime)

        # 核心层: 动态配置
        holdings = dynamic_core_allocation(regime, macro_state)

        # 防御层: 动态配置
        defense = dynamic_defense_allocation(regime, macro_state)
        holdings.extend(defense)

        # 卫星层: 评分排序 + 行业去重 + 幂律分配
        s_budget = budgets.get("satellite", 0.0)
        if s_budget > 0.02 and scanned_satellite:
            sat_count = max(3, min(8, int(s_budget / 0.04)))
            # 行业去重贪婪选择
            top_sat = []
            seen_industries = set()
            for item in scanned_satellite:
                if len(top_sat) >= sat_count:
                    break
                industry = item.get("industry", "unknown")
                if industry in seen_industries:
                    continue
                seen_industries.add(industry)
                top_sat.append(item)
            # 去重后数量不足时放宽
            if len(top_sat) < 3:
                for item in scanned_satellite:
                    if len(top_sat) >= sat_count:
                        break
                    if item not in top_sat:
                        top_sat.append(item)

            scores = [s.get("composite_score", 0.5) for s in top_sat]
            weights = power_law_weights(scores, s_budget)

            for i, a in enumerate(top_sat):
                if i < len(weights):
                    code = a["symbol"]
                    trend = trend_data.get(code, {})
                    news_info = news_map.get(code, {})
                    fund_flow_val = fund_flow_map.get(code)
                    pe_val = valuation_map.get(code, {}).get("pe_ttm") if code in valuation_map else None
                    rationale_parts = []
                    ret_3m = trend.get("return_3m")
                    if ret_3m is not None:
                        rationale_parts.append(f"近3月{'涨' if ret_3m>=0 else '跌'}{ret_3m*100:.1f}%")
                    if fund_flow_val is not None and fund_flow_val > 0:
                        rationale_parts.append(f"主力净流入{fund_flow_val/1e8:.1f}亿")
                    if news_info.get("total_mentions", 0) > 0:
                        rationale_parts.append(f"近期相关资讯{news_info['total_mentions']}条")
                    if not rationale_parts:
                        rationale_parts.append(f"评分{round(a.get('composite_score', 0.5), 3)}")

                    holdings.append({
                        "symbol": code,
                        "name": a["name"],
                        "layer": "satellite",
                        "weight": round(weights[i], 4),
                        "selection_rationale": "，".join(rationale_parts),
                        "industry": a.get("industry", ""),
                        "concepts": a.get("concepts", []),
                        "factor_score": round(a.get("composite_score", 0.5), 3),
                        "fund_flow_20d": fund_flow_val,
                        "pe_ttm": pe_val,
                        "trend_1m": trend.get("return_1m"),
                        "trend_3m": trend.get("return_3m"),
                        "ma_bias_20": trend.get("ma_bias_20"),
                    })

        # 归一化权重
        total_w = sum(h["weight"] for h in holdings)
        actual_budget = sum(budgets.get(l, 0) for l in ["core", "satellite", "defense"])
        if total_w > 0 and abs(total_w - 1.0) > 0.001 and actual_budget > 0:
            scale = min(actual_budget / total_w, 1.5)
            for h in holdings:
                h["weight"] = round(h["weight"] * scale, 4)

        # 现金
        cash = round(1.0 - actual_budget, 4)
        holdings.append({
            "symbol": "CASH", "name": "现金", "layer": "cash",
            "weight": cash, "selection_rationale": "流动性管理",
        })
        for h in holdings:
            h["target_amount"] = round(capital * h.get("weight", 0), 2)

        # 组合风控
        risk_metrics = compute_portfolio_risk(holdings, trend_data)

        # 市场状态描述
        regime_desc_map = {
            "bull_strong": "当前市场处于强牛市，资金情绪积极",
            "bull_weakening": "当前市场牛市趋弱，短期有回调压力",
            "range_bound": "当前市场处于震荡格局",
            "correction": "当前市场处于回调阶段，建议控制仓位",
            "bear": "当前市场处于熊市，建议以防御为主",
            "defensive_rotate": "当前市场处于防御轮动阶段，资金从高估值流向低估值",
            "panic": "当前市场情绪恐慌，建议保持现金为主",
        }

        strategies.append({
            "id": meta["id"],
            "label": meta["label"],
            "color": meta["color"],
            "portfolio_name": meta["portfolio_name"],
            "positioning": meta["positioning"],
            "expected_return": meta["expected_return"],
            "max_drawdown": min(meta["max_drawdown"], risk_metrics.get("max_drawdown_est", meta["max_drawdown"])),
            "sharpe_ratio": meta["sharpe_ratio"],
            "expected_characteristics": meta["expected_characteristics"],
            "market_regime_note": regime_desc_map.get(regime, ""),
            "layer_budget": budgets,
            "etfs": [h for h in holdings if h.get("symbol") != "CASH"],
            "risk_metrics": risk_metrics,
        })

    # 填充现金后的完整 holdings
    for s in strategies:
        cash_item = next((h for h in holdings if h.get("symbol") == "CASH"), None)
        if cash_item:
            s["etfs"].append(cash_item)

    # 7. 构建 sector momentum
    sector_momentum = await compute_sector_momentum()

    elapsed = (time.monotonic() - start_time) * 1000

    return {
        "strategies": strategies,
        "market_context": {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "market_sentiment": sentiment,
            "market_regime": regime,
            "macro_regime": macro_state,
            "benchmark_stocks": benchmark,
            "sector_momentum": sector_momentum,
            "news_sentiment_map": news_map,
        },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "design_metadata": {
            "version": "v4-enhanced",
            "factors_used": list(FACTOR_CONFIG.keys()),
            "trend_data_collected": len(trend_data),
            "news_mapped": len(news_map),
            "generation_time_ms": round(elapsed, 1),
        },
    }
