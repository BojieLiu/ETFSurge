"""
rationale.py — 基于因子分的入选理由生成（纯函数，P2 改进 #5：模板多样化）
"""
from __future__ import annotations

import hashlib
from typing import Any

# ── 层角色短语池（P2 改进 #5：模板多样化） ────────────────────────────
_CORE_PHRASES = [
    lambda n: f"在方案中作为核心底仓配置，跟踪{n}",
    lambda n: f"核心层选择——{n}，兼具流动性与分散性",
    lambda n: f"作为核心宽基{n}，提供市场β收益",
    lambda n: f"{n}核心层配置，大盘价值代表性",
    lambda n: f"以{n}作为组合压舱石，低波动宽基",
]

_SATELLITE_PHRASES = [
    lambda n: f"卫星层配置{n}，增强组合弹性",
    lambda n: f"行业{n}作为弹性卫星，博取超额收益",
    lambda n: f"{n}卫星仓位，参与赛道轮动机会",
    lambda n: f"主题{n}卫星配置，高弹性品种",
    lambda n: f"{n}作为卫星增强，聚焦高景气方向",
]

_DEFENSE_PHRASES = [
    lambda n: f"防御层{n}提供下行保护",
    lambda n: f"{n}与权益低相关，分散尾部风险",
    lambda n: f"避险资产{n}，降低组合波动",
    lambda n: f"{n}防御配置，对冲市场下行风险",
    lambda n: f"低相关性{n}，有效平衡组合波动",
]


def _layer_phrase(layer: str, asset_name: str, sym: str = "") -> str:
    """从短语池中选择一条层角色描述，用 symbol hash 保证稳定性。"""
    pool = {
        "core": _CORE_PHRASES,
        "satellite": _SATELLITE_PHRASES,
        "defense": _DEFENSE_PHRASES,
    }
    phrasers = pool.get(layer, _CORE_PHRASES)
    # Deterministic choice: seed from symbol hash so the same symbol gets the same phrase
    idx = int(hashlib.md5(sym.encode()).hexdigest(), 16) % len(phrasers) if sym else 0
    return phrasers[idx](asset_name)


def build_rationale(
    code: str,
    layer: str,
    strategy: str,
    meta: dict | None = None,
    factor_scores: dict[str, float] | None = None,
    regime: str | None = None,
    industry: str | None = None,
) -> str:
    """
    为指定层级的 ETF 生成数据驱动的入选理由。

    Args:
        code: ETF 代码
        layer: core / satellite / defense
        strategy: defensive / balanced / aggressive
        meta: ETF 元数据（name, reason, industry 等）
        factor_scores: {factor_name: score} 因子分
        regime: 市场状态
        industry: 行业分类

    Returns:
        str: 中文入选理由
    """
    parts: list[str] = []
    meta = meta or {}
    factor_scores = factor_scores or {}
    asset_name = meta.get("name", code)

    # 1. 资产介绍
    if "沪深300" in asset_name:
        parts.append(f"今日{factor_scores.get('change_pct', '')}%；{asset_name} — A股核心宽基，覆盖沪深两市龙头")
    elif "红利" in asset_name:
        parts.append(f"今日{factor_scores.get('change_pct', '')}%；{asset_name} — 高股息低波动，适合底仓配置")
    elif "黄金" in asset_name:
        parts.append(f"今日{factor_scores.get('change_pct', '')}%；{asset_name} — 贵金属避险资产，与权益低相关")
    elif "国债" in asset_name:
        parts.append(f"今日{factor_scores.get('change_pct', '')}%；{asset_name} — 利率债，货币宽松周期受益")
    else:
        ind = industry or meta.get("industry") or "行业"
        parts.append(f"今日{factor_scores.get('change_pct', '')}%；{asset_name} — {ind}方向")

    # 2. 趋势数据（如果存在）
    ret_3m = factor_scores.get("return_3m")
    ret_1m = factor_scores.get("return_1m")
    if ret_3m is not None:
        parts.append(f"近3月{ret_3m * 100:+.1f}%")
    if ret_1m is not None:
        parts.append(f"近1月{ret_1m * 100:+.1f}%")

    # 3. 技术面
    ma_bias = factor_scores.get("ma_bias_20")
    if ma_bias is not None:
        if ma_bias < 0:
            parts.append(f"20日均线下方{abs(ma_bias)*100:.1f}%")
        else:
            parts.append(f"20日均线上方{ma_bias*100:.1f}%")

    # 4. 市场状态
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

    # 5. 层角色（模板多样化）
    sl = {"defensive": "防御型", "balanced": "平衡型", "aggressive": "进攻型"}
    label = sl.get(strategy, strategy)
    layer_desc = _layer_phrase(layer, asset_name, code)
    parts.append(f"在{label}方案中{layer_desc}")

    return "；".join(parts) if parts else f"{asset_name} — 基于因子评分入选"
