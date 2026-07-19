"""
智能组合设计 - 核心+卫星+防御 三层结构生成引擎 (v3.0)

Generate ETF portfolio plans with a core + satellite + defense three-layer structure.
Core and defense layers are fixed-weight. Satellite uses dual-pool matching,
z-score multi-factor scoring, tilt ratios, and power-law weight distribution.
This module is the orchestration layer that ties together:
  - allocate_layer_budget: 按风险偏好(防御/平衡/进攻)分配层预算
  - generate_full_design:  对外主入口, 生成三套方案 (delegates to generate_enhanced_design)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


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
        "max_drawdown": -0.35,
        "sharpe_ratio": 0.8,
        "layer_budget": {"core": 0.50, "satellite": 0.35, "defense": 0.05}, # cash=10%,

        "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
    },
}


# 全局单只约束
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.30


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
    "511880": {"name": "银华日利ETF", "layer": "defense", "beta": 0.0, "liquidity": 50.0,
               "reason": "货币基金，现金管理工具"},
    "511990": {"name": "华宝添益ETF", "layer": "defense", "beta": 0.0, "liquidity": 50.0,
               "reason": "货币基金，现金管理工具"},
    "513500": {"name": "标普500ETF", "layer": "defense", "beta": 0.6, "liquidity": 14.0,
               "reason": "美股宽基，跨市场分散"},
    "159980": {"name": "有色ETF", "layer": "defense", "beta": 0.5, "liquidity": 3.0,
               "reason": "商品资产，通胀对冲"},
}



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


# ── 5. generate_full_design: 对外主入口 (v4) ─────────────────
# 委托给 generate_enhanced_design 生成三套方案，并补全 sentiment/benchmark。
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
        generate_enhanced_design(capital=capital, constraints=constraints),
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
            strategies = await generate_enhanced_design(capital=capital, constraints=constraints)
        except Exception as e:
            logger.error("[generate_full_design] generate_enhanced_design failed: %s", e)
            strategies = []
    if isinstance(sentiment, (Exception, type(None))):
        sentiment = {"sentiment_index": 50, "sentiment_label": "中性"}
    if isinstance(benchmark, (Exception, type(None))):
        benchmark = []

    # P2 修复: 合并 enhanced 引擎返回的完整 market_context（含 market_regime /
    # macro_regime / index_realtime / sector_momentum 等），而不是用简版覆盖。
    enhanced_ctx = {}
    if isinstance(strategies, dict) and isinstance(strategies.get("market_context"), dict):
        enhanced_ctx = strategies.get("market_context") or {}

    merged_context = {
        **enhanced_ctx,
        "market_sentiment": enhanced_ctx.get("market_sentiment") or (sentiment if sentiment else {"sentiment_index": 50, "sentiment_label": "中性"}),
        "benchmark_stocks": benchmark if benchmark else enhanced_ctx.get("benchmark_stocks"),
    }

    return {
        "strategies": strategies.get("strategies", strategies) if isinstance(strategies, dict) else strategies,
        "market_context": merged_context,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ═══════════════════════════════════════════════════════════════
# v4 增强功能: 多因子评分 / 资讯映射 / 动态配置 / 风控
# ═══════════════════════════════════════════════════════════════

# ── 多因子评分配置 ─────────────────────────────────────────────

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
            {"symbol": "510500", "name": "中证500ETF", "layer": "core", "weight": 0.10,
             "selection_rationale": "中盘成长宽基，补足核心层分散度"},
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
            {"symbol": "510500", "name": "中证500ETF", "layer": "core", "weight": 0.10,
             "selection_rationale": "中盘成长宽基，增强分散度"},
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
            {"symbol": "510500", "name": "中证500ETF", "layer": "core", "weight": 0.10,
             "selection_rationale": "中盘成长宽基"},
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

    # 债券：利率下行时加入，或 correction/bear 时也加入作为安全资产
    if bond_bull or rate_direction == "down" or regime in ("correction", "bear"):
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
        # correction/bear: extra satellite reduction (cash rises naturally)
        if regime in ("correction", "bear"):
            sat_reduce = {"defensive": 0.00, "balanced": 0.03, "aggressive": 0.08}.get(risk_profile, 0.00)
            if sat_reduce > 0:
                base["satellite"] = max(base["satellite"] - sat_reduce, 0.08)
                base["core"] = min(base["core"] + sat_reduce * 0.4, 0.60)

        # bear: extra cash protection
        if regime == "bear":
            cash_boost = {"defensive": 0.05, "balanced": 0.05, "aggressive": 0.10}.get(risk_profile, 0.05)
            base["core"] = max(base["core"] - cash_boost * 0.3, 0.30)
            base["satellite"] = max(base["satellite"] - cash_boost * 0.3, 0.05)


    # 强牛市: 加大卫星预算（进攻端）
    elif regime in ("bull_strong",):
        shift = {"defensive": 0.05, "balanced": 0.08, "aggressive": 0.10}.get(risk_profile, 0.05)
        base["satellite"] = min(base.get("satellite", 0.20) + shift, 0.50)
        base["core"] = max(base.get("core", 0.50) - shift * 0.5, 0.35)
        base["defense"] = max(base.get("defense", 0.05) - shift * 0.3, 0.03)

    return base


# ── 组合风控 ──────────────────────────────────────────────────



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
        sector = h.get("industry", "") or h.get("layer", "其他")
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

def build_rationale(
    code: str,
    layer: str,
    strategy: str,
    meta: dict | None = None,
    trend: dict | None = None,
    macro_state: dict | None = None,
    regime: str | None = None,
    sentiment: dict | None = None,
    news_info: dict | None = None,
    fund_flow: float | None = None,
    valuation: dict | None = None,
    sector_momentum: list | None = None,
    industry: str | None = None,
) -> str:
    """为指定层级的 ETF 生成数据驱动的入选理由。数据维度为 None 时自动跳过。"""
    parts = []
    meta = meta or {}
    trend = trend or {}
    macro_state = macro_state or {}
    sentiment = sentiment or {}
    news_info = news_info or {}
    asset_name = meta.get("name", code)

    # 0. 当日涨跌（若有）— 置于理由最前，直观展示今日表现
    chg = trend.get("change_pct")
    if chg is not None:
        d = "涨" if chg >= 0 else "跌"
        parts.append("今日" + d + str(round(abs(chg) * 100, 1)) + "%")

    # 1. 资产定位
    if layer == "core":
        if "沪深300" in asset_name:
            parts.append(asset_name + " — A股核心宽基，覆盖沪深两市龙头")
        elif "中证A" in asset_name:
            parts.append(asset_name + " — 行业均衡宽基，分散度优于沪深300")
        elif "红利" in asset_name:
            parts.append(asset_name + " — 高股息低波动，适合防御底仓")
        else:
            parts.append(asset_name + " — 核心层宽基配置")
    elif layer == "satellite":
        ind = industry or meta.get("reason", "行业主题")
        parts.append(asset_name + " — " + ind + "方向，高弹性卫星品种")
    elif layer == "defense":
        if "黄金" in asset_name:
            parts.append(asset_name + " — 贵金属避险资产，与权益低相关。短期金价波动不影响避险属性，用于对冲权益极端系统性风险和地缘政治风险")
        elif "国债" in asset_name:
            parts.append(asset_name + " — 利率债，货币宽松周期受益")
        else:
            parts.append(asset_name + " — 防御层避险配置")

    # 2. 走势
    ret_3m = trend.get("return_3m")
    if ret_3m is not None:
        d = "涨" if ret_3m >= 0 else "跌"
        parts.append("近3月" + d + str(round(abs(ret_3m) * 100, 1)) + "%")
    ret_1m = trend.get("return_1m")
    if ret_1m is not None:
        d = "涨" if ret_1m >= 0 else "跌"
        parts.append("近1月" + d + str(round(abs(ret_1m) * 100, 1)) + "%")
    ma_bias = trend.get("ma_bias_20")
    if ma_bias is not None:
        pos = "上方" if ma_bias >= 0 else "下方"
        sig = "+" if ma_bias >= 0 else ""
        parts.append("20日均线" + pos + "(乖离率" + sig + str(round(ma_bias * 100, 1)) + "%)")

    # 3. 资金流向(卫星)
    if layer == "satellite" and fund_flow is not None and abs(fund_flow) > 0:
        d = "净流入" if fund_flow > 0 else "净流出"
        parts.append("主力资金" + d + str(round(abs(fund_flow) / 1e8, 1)) + "亿")

    # 4. 估值
    pe = (valuation or {}).get("pe_ttm")
    if pe is not None:
        s = "PE " + str(round(pe, 1)) + "x"
        pb = (valuation or {}).get("pb", 0)
        if pb:
            s += " PB " + str(round(pb, 1)) + "x"
        parts.append(s)

    # 5. 市场状态
    regime_desc = {
        "bull_strong": "当前市场强势",
        "bull_weakening": "牛市趋弱",
        "range_bound": "市场震荡",
        "correction": "市场回调中",
        "bear": "熊市环境",
        "defensive_rotate": "防御轮动阶段",
        "panic": "市场恐慌",
    }
    if regime and regime in regime_desc:
        parts.append(regime_desc[regime])

    # 6. 宏观环境
    economic = macro_state.get("economic_phase")
    monetary = macro_state.get("monetary_stance")
    if economic:
        parts.append("宏观" + economic + ("·" + monetary if monetary else ""))

    # 7. 市场情绪
    si = sentiment.get("sentiment_index")
    if si is not None:
        if si >= 60:
            parts.append("市场情绪偏积极")
        elif si <= 40:
            parts.append("市场情绪偏谨慎")
        else:
            parts.append("市场情绪中性")

    # 8. 资讯
    mentions = news_info.get("total_mentions", 0)
    if mentions > 0:
        ns = news_info.get("sentiment_score", 0)
        st = "偏正面" if ns > 0.3 else ("偏负面" if ns < -0.3 else "中性")
        parts.append("相关资讯" + str(mentions) + "条·" + st)

    # 9. 行业动量(卫星)
    if layer == "satellite" and industry and sector_momentum:
        for item in sector_momentum:
            if industry in item.get("sector_name", ""):
                rk = item.get("rank", 0)
                tl = max(item.get("total", 1), 1)
                if 0 < rk <= tl:
                    parts.append("行业动量排名" + str(rk) + "/" + str(tl))
                break

    # 10. 层角色
    sl = {"defensive": "防御型", "balanced": "平衡型", "aggressive": "进攻型"}
    label = sl.get(strategy, strategy)
    if layer == "core":
        parts.append("在" + label + "方案中作为核心底仓")
    elif layer == "satellite":
        if strategy == "aggressive":
            parts.append("在" + label + "方案中高权重配置提供弹性")
        elif strategy == "defensive":
            parts.append("在" + label + "方案中低权重参与控制回护")
        else:
            parts.append("在" + label + "方案中适度配置增强收益")
    elif layer == "defense":
        parts.append("在" + label + "方案中提供下行保护")

    return "；".join(parts)



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
    from ..fetchers.china_market import fetch_index_realtime
    from ..services.pool_manager import pool_manager

    all_symbols = list(CANDIDATE_POOL.keys())

    trend_data, macro_state, sentiment, benchmark, news_tasks, index_realtime = await asyncio.gather(
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
        asyncio.wait_for(asyncio.to_thread(fetch_index_realtime), timeout=15),
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
    index_realtime = index_realtime if isinstance(index_realtime, list) else []
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
        broad_index_code="510300",  # 沪深300ETF — 在 trend_data 中存在（P0 修复）
        sentiment_index=sentiment_index,
        adv_ratio=adv_ratio,
        index_realtime=index_realtime,  # P0.5: 趋势数据为空时降级使用
    )

    # P6: 当情绪数据源全部失效(sentiment_index=50)时，用 regime 覆盖
    if sentiment.get("sentiment_index") == 50 and regime:
        from ..fetchers.sentiment_fetcher import sentiment_label as _sl
        regime_scores = {"bull_strong": 70, "bull_weakening": 55,
                         "range_bound": 50, "slow_rise": 55,
                         "correction": 30, "bear": 20,
                         "defensive_rotate": 35, "panic": 10}
        bias = regime_scores.get(regime, 50)
        sentiment["sentiment_index"] = bias
        sentiment["sentiment_label"] = _sl(bias)
        logger.info("Sentiment override: regime=%s -> index=%d label=%s", regime, bias, sentiment["sentiment_label"])

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
            # 排除货币ETF（现金管理工具，非弹性资产）
            _monetary = {"511880", "511990"}
            scanned_satellite = [s for s in scanned_satellite if s.get("symbol") not in _monetary]
            pool_ready = True
            logger.info("pool_manager: %d satellite candidates", len(scanned_satellite))
    except Exception as e:
        logger.error("pool_manager refresh failed: %s (will fallback to hardcoded pool)", e)

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
            _monetary = {"511880", "511990"}
            scanned_satellite = [s for s in scanned_satellite if s.get("symbol") not in _monetary]
        except Exception as e:
            logger.error("enhanced scan failed: %s (will fallback to hardcoded satellite pool)", e)

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

        # 核心/防御层: 用 build_rationale 替换硬编码理由
        for h in holdings:
            code = h["symbol"]
            h["selection_rationale"] = build_rationale(
                code=code, layer=h.get("layer", "core"), strategy=key,
                meta=CANDIDATE_POOL.get(code, {}),
                trend=trend_data.get(code, {}),
                macro_state=macro_state, regime=regime,
                sentiment=sentiment, news_info=news_map.get(code, {}),
                fund_flow=fund_flow_map.get(code),
                valuation=valuation_map.get(code),
            )

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
                    holdings.append({
                        "symbol": code,
                        "name": a["name"],
                        "layer": "satellite",
                        "weight": round(weights[i], 4),
                        "selection_rationale": build_rationale(
                            code=code, layer="satellite", strategy=key,
                            meta=a,
                            trend=trend_data.get(code, {}),
                            macro_state=macro_state, regime=regime,
                            sentiment=sentiment, news_info=news_map.get(code, {}),
                            fund_flow=fund_flow_map.get(code),
                            valuation=valuation_map.get(code),
                            industry=a.get("industry", ""),
                        ),
                        "industry": a.get("industry", ""),
                        "concepts": a.get("concepts", []),
                        "factor_score": round(a.get("composite_score", 0.5), 3),
                        "fund_flow_20d": fund_flow_val,
                        "pe_ttm": pe_val,
                        "trend_1m": trend.get("return_1m"),
                        "trend_3m": trend.get("return_3m"),
                        "ma_bias_20": trend.get("ma_bias_20"),
                    })

        # 卫星层行业集中度检查：单行业不超过 satellite_budget 的 40%
        if s_budget > 0:
            sector_weights_in_sat = {}
            for h in holdings:
                if h.get("layer") == "satellite":
                    ind = h.get("industry", "")
                    sector_weights_in_sat[ind] = sector_weights_in_sat.get(ind, 0) + h.get("weight", 0)
            max_sat_sector_pct = max(sector_weights_in_sat.values()) / s_budget if s_budget > 0 and sector_weights_in_sat else 0
            if max_sat_sector_pct > 0.40:
                logger.warning("Satellite sector concentration %.0f%% > 40%% limit, capping", max_sat_sector_pct * 100)
                for industry, total_w in sector_weights_in_sat.items():
                    max_allowed = s_budget * 0.40
                    if total_w > max_allowed:
                        excess_ratio = max_allowed / total_w
                        for h in holdings:
                            if h.get("layer") == "satellite" and h.get("industry", "") == industry:
                                h["weight"] = round(h["weight"] * excess_ratio, 4)

        # 归一化权重
        total_w = sum(h["weight"] for h in holdings)
        actual_budget = sum(budgets.get(l, 0) for l in ["core", "satellite", "defense"])
        if total_w > 0 and abs(total_w - 1.0) > 0.001 and actual_budget > 0:
            scale = min(actual_budget / total_w, 1.5)
            for h in holdings:
                h["weight"] = round(h["weight"] * scale, 4)

        # factor_score 覆盖：确保核心/防御层也有评分
        _pool_by_sym = {p.get("symbol"): p for p in (sat_pool or [])}
        for h in holdings:
            if h.get("factor_score") is None and h.get("symbol") in _pool_by_sym:
                h["factor_score"] = round(_pool_by_sym[h["symbol"]].get("composite_score", 0.5), 3)

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

    # 现金追加：按各自 layer_budget 独立计算
    for s in strategies:
        lb = s.get("layer_budget", {})
        implied_cash = round(1.0 - sum(lb.get(k, 0) for k in ("core", "satellite", "defense")), 4)
        s["etfs"].append({"symbol": "CASH", "name": "现金", "layer": "cash", "weight": max(implied_cash, 0.05), "selection_rationale": "流动性管理"})

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
                "index_realtime": index_realtime,
                "sector_momentum": sector_momentum,
                "news_sentiment_map": news_map,
            },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "design_metadata": {
            "version": "v4-enhanced",
            "factors_used": ["momentum", "fund_flow", "valuation", "liquidity", "volatility"],
            "trend_data_collected": len(trend_data),
            "news_mapped": len(news_map),
            "generation_time_ms": round(elapsed, 1),
        },
    }
