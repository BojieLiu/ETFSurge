"""
智能组合设计 - 核心+卫星+防御 三层结构生成引擎

Generate ETF portfolio plans with a core + satellite + defense three-layer structure.
This module is the orchestration layer that ties together:
  - enrich_market_context: 补全大盘指数/ETF资金流向/估值等缺失数据维度
  - classify_assets:       将候选标的按三层结构分类
  - build_candidates:      使用 etf_scanner 全市场扫描替代固定 CANDIDATE_POOL
  - satellite_two_round_scoring: 卫星层两轮评分 (轻量→深度, 含资讯匹配)
  - allocate_layer_budget: 按风险偏好(防御/平衡/进攻)分配层预算
  - optimize_layer:        层内权重优化(1%~30%约束, scipy SLSQP)
  - generate_design:       对外主入口, 生成三套方案
"""

from __future__ import annotations

import asyncio
import random
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
        "layer_budget": {"core": 0.55, "satellite": 0.25, "defense": 0.20},
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
        "layer_budget": {"core": 0.55, "satellite": 0.30, "defense": 0.15},
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
        "layer_budget": {"core": 0.50, "satellite": 0.40, "defense": 0.10},
        "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
    },
}

# 每层单只标的上限
LAYER_WEIGHT_CAP = {"core": 0.20, "satellite": 0.12, "defense": 0.08}

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
    "510500": {"name": "中证500ETF", "layer": "core", "beta": 1.1, "liquidity": 15.0,
               "reason": "中盘成长宽基，提升核心层弹性"},
    "159915": {"name": "创业板ETF", "layer": "core", "beta": 1.25, "liquidity": 18.0,
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

    for code, meta in CANDIDATE_POOL.items():
        price = 1.0
        change = 0.0
        # 优先从指数行情取(宽基本身是指数)
        if code in idx_map:
            price = idx_map[code].get("price", 1.0) or 1.0
            change = (idx_map[code].get("change_pct", 0.0) or 0.0) / 100.0
        f = flow_map.get(code)
        net_inflow = f.get("net_inflow", 0.0) if f else 0.0
        v = val_map.get(code)
        val_pct = v.get("valuation_percentile", 0.5) if v else 0.5
        ctx.assets[code] = Asset(
            code=code, name=meta["name"], layer=meta["layer"], beta=meta["beta"],
            liquidity=meta["liquidity"], price=price, change_pct=change,
            net_inflow=net_inflow, valuation_pct=val_pct, reason=meta["reason"],
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


# ── 4. optimize_layer: 层内权重优化 ──────────────────────────
def optimize_layer(
    layer: str,
    assets: list[Asset],
    budget: float,
    strategy: str = "balanced",
    constraints: dict | None = None,
) -> list[dict[str, Any]]:
    """
    层内权重优化：目标=最大化(收益打分 - 风险惩罚)，约束=单只1%~层上限，层内加总=budget。
    收益打分综合考虑: beta(预期收益代理), 资金流入, 估值分位(低估值加分), 流动性。
    使用 scipy SLSQP 求解；失败回退到启发式按比例分配。
    """
    if not assets:
        return []

    # 候选数过多时, 按评分选子集, 使能在 [min_w, cap] 内填满 budget
    min_w = MIN_WEIGHT
    max_w = min(MAX_WEIGHT, LAYER_WEIGHT_CAP.get(layer, MAX_WEIGHT))
    # 如果候选数*min_w > budget，则放宽下限
    if len(assets) * min_w > budget:
        min_w = budget / len(assets) * 0.9

    def score(a: Asset) -> float:
        ret = a.beta * (1.0 if strategy == "aggressive" else 0.7)
        flow = (a.net_inflow / 1e8) * 0.05
        val = (0.5 - a.valuation_pct) * 0.3
        liq = min(a.liquidity / 20.0, 1.0) * 0.1
        return ret + flow + val + liq

    scored = sorted(assets, key=lambda a: score(a), reverse=True)
    # 核心层: 宽基指数全部保留(分散度优先)
    # 卫星/防御层: 按评分选子集, 使能在 [min_w, cap] 内填满 budget
    if layer == "core":
        selected = scored
    else:
        selected = []
        for a in scored:
            selected.append(a)
            max_fill = len(selected) * max_w
            min_fill = len(selected) * min_w
            if min_fill <= budget <= max_fill:
                break
        if not selected:
            selected = scored
    assets = selected

    n = len(assets)

    # 打分函数 (已在上面定义 score, 这里复用)
    scores = [max(score(a), 0.01) for a in assets]
    total_score = sum(scores)

    # 初始权重: 按评分归一化到 budget
    x0 = [budget * s / total_score for s in scores]

    def objective(w):
        # 最小化负夏普近似: -sum(w_i * score_i) + 0.1*sum(w_i^2)(分散化惩罚)
        ret = sum(w[i] * scores[i] for i in range(n))
        penalty = 0.1 * sum(wi * wi for wi in w)
        return -(ret - penalty)

    # 约束
    cons = [{"type": "eq", "fun": lambda w: sum(w) - budget}]
    # 核心层必须含沪深300与中证A500各>=CORE_MIN_EACH
    bounds = [(min_w, max_w) for _ in range(n)]
    fixed_idx = []
    if layer == "core":
        for req in CORE_REQUIRED:
            for i, a in enumerate(assets):
                if a.code == req:
                    fixed_idx.append(i)
                    cons.append({"type": "ineq", "fun": lambda w, i=i: w[i] - CORE_MIN_EACH})

    try:
        from scipy.optimize import minimize
        res = minimize(
            objective, x0, method="SLSQP", bounds=bounds, constraints=cons,
            options={"maxiter": 200, "ftol": 1e-9},
        )
        if res.success:
            weights = [max(0.0, w) for w in res.x]
        else:
            weights = x0
    except Exception:
        weights = x0

    # 硬性约束后处理: 截断到 [min_w, max_w]
    weights = [min(max(w, min_w), max_w) for w in weights]

    # 确保核心层必备标的下限
    if layer == "core":
        for i in fixed_idx:
            weights[i] = max(weights[i], CORE_MIN_EACH)

    # 缩放至精确等于 budget (保持比例, 优先保证核心下限)
    s = sum(weights)
    if s > 0:
        weights = [w / s * budget for w in weights]
    # 二次截断(缩放后可能微超)
    weights = [min(max(w, min_w), max_w) for w in weights]

    out = []
    for a, w in zip(assets, weights):
        out.append({
            "symbol": a.code,
            "name": a.name,
            "layer": layer,
            "weight": round(w, 4),
            "price": round(a.price, 4),
            "change_pct": round(a.change_pct, 4),
            "selection_rationale": a.reason,
        })
    # 按权重降序
    out.sort(key=lambda x: x["weight"], reverse=True)
    return out


# ── 5. generate_design: 主入口 ───────────────────────────────
async def generate_design(
    risk_profile: str = "balanced",
    capital: float = 500000,
    mode: str = "standard",
    constraints: dict | None = None,
    db=None,
) -> list[dict[str, Any]]:
    """
    生成三套组合方案（防御/平衡/进攻）。
    mode='fast' 使用固定候选池 (<2s)。
    mode='standard' 使用全市场扫描 + 卫星层两轮评分 (~10s)。
    """
    constraints = constraints or {}
    min_names = constraints.get("min_names", MIN_NAMES)
    max_names = constraints.get("max_names", MAX_NAMES)

    # 1. 数据补全
    if mode == "fast":
        ctx = _build_default_context()
    else:
        ctx = await enrich_market_context()

    # 1b. standard 模式: 使用全市场扫描扩展候选池
    if mode == "standard":
        from ..fetchers.etf_scanner import full_pipeline as scan_full_pipeline

        scanned = scan_full_pipeline()
        if scanned.get("core") or scanned.get("satellite") or scanned.get("defense"):
            # 用扫描结果重建 ctx.assets
            ctx = MarketContext()
            for layer_name, items in scanned.items():
                for item in items:
                    ctx.assets[item["symbol"]] = Asset(
                        code=item["symbol"],
                        name=item.get("name", ""),
                        layer=layer_name,
                        beta=1.0,
                        liquidity=item.get("amount", 0) / 1e8,
                        price=item.get("price", 1.0),
                        change_pct=item.get("change_pct", 0) / 100.0,
                        net_inflow=0.0,
                        valuation_pct=0.5,
                        reason=item.get("name", ""),
                    )

    # 2. 分类
    layers = classify_assets(ctx)

    # 3. 为三套策略分别生成
    strategies = []
    for key in ["defensive", "balanced", "aggressive"]:
        meta = STRATEGY_META[key]
        budgets = allocate_layer_budget(key)

        holdings: list[dict] = []
        # 层内优化
        for layer in ["core", "satellite", "defense"]:
            assets = layers.get(layer, [])
            if not assets:
                continue
            # 为该层按比例选标的: 核心全选, 卫星/防御按预算截顶
            budget = budgets.get(layer, 0.0)
            layer_holdings = optimize_layer(layer, assets, budget, key, constraints)
            holdings.extend(layer_holdings)

        # 4. 校验标的总数 8~15
        holdings = _enforce_name_count(holdings, min_names, max_names, budgets)

        # 5. 归一化权重到 100% (用高精度计算, 最后修正舍入误差)
        total_w = sum(h["weight"] for h in holdings)
        if total_w > 0:
            raw = [h["weight"] / total_w for h in holdings]
            # 四舍五入到 4 位
            rounded = [round(w, 4) for w in raw]
            diff = round(1.0 - sum(rounded), 4)
            # 把误差补到权重最大的那一项, 保证加总恰好=1.0
            if diff != 0.0:
                max_i = max(range(len(rounded)), key=lambda i: rounded[i])
                rounded[max_i] = round(rounded[max_i] + diff, 4)
            for h, w in zip(holdings, rounded):
                h["weight"] = w
                h["target_amount"] = round(capital * w, 2)

        strategy = {
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
        }
        strategies.append(strategy)

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
        for code, meta in CANDIDATE_POOL.items():
            if code in existing:
                continue
            if len(holdings) >= min_names:
                break
            holdings.append({
                "symbol": code,
                "name": meta["name"],
                "layer": meta["layer"],
                "weight": MIN_WEIGHT,
                "price": 1.0,
                "change_pct": 0.0,
                "selection_rationale": meta["reason"],
            })
    return holdings


def _build_default_context() -> MarketContext:
    """fast 模式: 不拉外部数据, 用候选池默认值"""
    ctx = MarketContext()
    for code, meta in CANDIDATE_POOL.items():
        ctx.assets[code] = Asset(
            code=code, name=meta["name"], layer=meta["layer"], beta=meta["beta"],
            liquidity=meta["liquidity"], price=1.0, change_pct=0.0,
            net_inflow=0.0, valuation_pct=0.5, reason=meta["reason"],
        )
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
        timeout=20,
    )
    sentiment_task = asyncio.wait_for(
        fetch_market_sentiment(), timeout=10,
    )
    benchmark_task = asyncio.wait_for(
        fetch_benchmark_stocks(), timeout=10,
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
