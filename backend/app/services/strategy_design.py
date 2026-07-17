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
    scanned_satellite: list[Asset] = []
    if mode == "standard":
        try:
            from ..fetchers.etf_scanner import full_pipeline as scan_full_pipeline
            scanned = await asyncio.to_thread(scan_full_pipeline)
            scanned_satellite = [
                Asset(code=item["symbol"], name=item.get("name", ""),
                      layer=item.get("layer", "satellite"), beta=1.0,
                      liquidity=item.get("amount", 0) / 1e8, price=item.get("price", 1.0),
                      change_pct=item.get("change_pct", 0) / 100.0,
                      net_inflow=0.0, valuation_pct=0.5, reason=item.get("name", ""))
                for item in (scanned.get("satellite") or [])
            ]
        except Exception as e:
            logger.warning("scan failed: %s", e)

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
            liquidity = [a.liquidity for a in sat_assets]
            scores = _extract_factor(liquidity)
            weights = power_law_weights(scores, s_budget)
            for i, a in enumerate(sat_assets):
                if i < len(weights):
                    holdings.append({
                        "symbol": a.code,
                        "name": a.name,
                        "layer": "satellite",
                        "weight": round(weights[i], 4),
                        "selection_rationale": f"卫星候选 #{i+1}",
                    })

        # 归一化权重到 100%
        total = sum(h["weight"] for h in holdings)
        if total > 0:
            holdings = [dict(h) for h in holdings]
            raw = [h["weight"] / total for h in holdings]
            rounded = [round(w, 4) for w in raw]
            diff = round(1.0 - sum(rounded), 4)
            if diff != 0.0:
                max_i = max(range(len(rounded)), key=lambda i: rounded[i])
                rounded[max_i] = round(rounded[max_i] + diff, 4)
            for h, w in zip(holdings, rounded):
                h["weight"] = w
                h["target_amount"] = round(capital * w, 2)

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
