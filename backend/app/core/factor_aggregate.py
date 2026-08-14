"""factor_aggregate — 因子分类聚合纯函数（round23 §10 A1 提取）。

origin: app.factors.factor_registry.FactorRegistry.aggregate_factor_scores 静态方法
+ 其依赖常量（CATEGORY_AGG / IC_* / _ic_decay_mean）。

动机（round23 §10.1 P1-A）：allocation_engine（纯函数层）旧实现循环内
`import factor_registry` 读私有全局态，engine 纯度/可重放性失效。A1 参数化后
engine 仍需要 aggregate_factor_scores 的静态逻辑——将其下沉到 core 层（engine
可依赖 core），factor_registry 从本模块 re-export（单一真相源，无复制漂移）。

纯函数：无 I/O、无全局可变态（definitions/ic_series 由调用方传入）。
"""
from __future__ import annotations

import math
from typing import Any

# 顶层分类到点分前缀映射 + 方向规则（原 factor_registry.CATEGORY_AGG）
CATEGORY_AGG: dict[str, list[tuple[str, int, str | None]]] = {
    "technical": [
        ("technical.ma.", +1, None),
        ("technical.macd.", +1, None),
        ("technical.rsi.", -1, "symmetric50"),
        ("technical.kdj.", -1, "negate"),
        ("technical.signal.", +1, None),
        ("technical.bollinger.", +1, None),
        ("technical.volume.", +1, None),
        ("technical.atr.", +1, None),
    ],
}

# round15 方案三阶段一: IC 加权聚合参数（docs §5.3）
IC_MIN_BATCHES = 5        # IC 样本 < 5 批 = 冷启动 → 回退等权（保持现有行为）
IC_FLIP_THRESHOLD = 0.03  # mean_ic < 0 且 |mean_ic| > 阈值 → 因子值翻转后按 |mean_ic| 加权
IC_HALF_LIFE = 20         # IC 半衰期（批数），λ = ln2/IC_HALF_LIFE


def _ic_decay_mean(series: list[float], lam: float) -> float:
    """近 N 批 IC 的衰减加权均值（最新批权重 1，越旧按 exp(-λ·age) 衰减）。"""
    n = len(series)
    if n == 0:
        return 0.0
    weights = [math.exp(-lam * (n - 1 - i)) for i in range(n)]
    total = sum(weights)
    if total <= 0:
        return float(sum(series)) / n
    return sum(w * v for w, v in zip(weights, series)) / total


def aggregate_factor_scores(
    factor_scores: dict[str, float],
    definitions: dict[str, Any] | None = None,
    ic_series: dict[str, list[float]] | None = None,
) -> dict[str, float]:
    """将点分键聚合为顶层分类键（原 FactorRegistry.aggregate_factor_scores）。

    FactorRegistry.compute() 返回的键名是点分式如 `technical.ma.sma_5`，
    但 allocation_engine 使用顶层键 `technical`、`momentum`、`valuation`、`sentiment`。

    聚合策略：对每个顶层分类，取下属所有因子值的均值。
    无下属因子的顶层键保持原值（如已存在则直接保留）。

    round15 方案一/方案三（docs §5.1/§5.3）：
    - 聚合前先「方向化」——按 FactorDefinition.direction/neutral_value（yaml 单一来源）
      将语义统一为「越高越好」：raw 区间因子（RSI）→ (neutral-val)/neutral；
      zscore 均值回归因子（KDJ）→ 取负。变换作用于副本，不写回 factor_scores
      原始裸键（_raw 保留链路 / _normalize_matrix 的真实值展示不受污染）。
    - 顶层键内按因子 IC 衰减加权聚合（近 N 批 IC），负 IC 翻转方向；冷启动
      （IC 样本 < IC_MIN_BATCHES）回退等权，保持现有行为。
    """
    if not factor_scores:
        return factor_scores

    # 定义顶层分类到点分前缀的映射
    # 注意：etf.return_1m/return_3m/change_pct 等回报类因子由 etf. 前缀捕获到 momentum
    # F1-5/§9.7 R1: 纯价格键 etf.price 不再是 valuation 分量——价格≠估值，
    # 否则黄金/债券等无估值概念的资产也会产生「估值分」（字段错位假信号 +3.9）。
    # 但 etf.price.* 子键（如 etf.price.dividend_yield 股息率）是真实估值维度，保留。
    CATEGORY_PREFIXES = {
        "technical": ["technical."],
        "momentum": ["etf.return_", "etf.change_pct", "china.policy.", "technical.signal."],
        "valuation": ["style.", "etf.price."],
        "sentiment": ["sentiment."],
    }

    # 排除 ln_mcap/ln_float_mcap 从 valuation 聚合：市值维度不等于估值维度
    _EXCLUDE_FROM_VALUATION = {"ln_mcap", "ln_float_mcap"}

    def _direction_rule(key: str) -> tuple[int, str | None, float | None]:
        """返回 (direction, transform_mode, neutral_value)。

        definitions（FactorDefinition）优先——yaml 是方向/中性点的单一来源；
        未提供 definitions 时回退 CATEGORY_AGG 内置默认（rsi→symmetric50、
        kdj→negate、其余 +1），保证静态调用/旧测试行为一致。
        """
        if definitions:
            d = definitions.get(key)
            if d is not None:
                if d.standardization == "raw" and d.neutral_value is not None:
                    return (d.direction, "symmetric50", float(d.neutral_value))
                return (d.direction, "negate" if d.direction == -1 else None, None)
        for _prefix, _direction, _mode in CATEGORY_AGG.get("technical", []):
            if key.startswith(_prefix):
                return (_direction, _mode, 50.0 if _mode == "symmetric50" else None)
        return (1, None, None)

    def _directional(key: str, val: float) -> float:
        """方向化（作用于副本）：raw 区间 (neutral-val)/neutral；-1 取负；+1 保持。"""
        _direction, _mode, _neutral = _direction_rule(key)
        if _mode == "symmetric50" and _neutral:
            return (_neutral - val) / _neutral
        if _direction == -1:
            return -val
        return val

    result = dict(factor_scores)  # 保留所有原始键

    for top_key, prefixes in CATEGORY_PREFIXES.items():
        values: list[tuple[str, float]] = []  # (原始键, 方向化后值)
        for key, val in factor_scores.items():
            if isinstance(val, (int, float)) and abs(val) > 0.001:
                # R6-F4: 排除 _raw 保留键（原始 RSI/MACD）——避免真实值污染分类均值
                if key.endswith("_raw"):
                    continue
                # F1-5: 纯价格键（etf.price）不算估值——它只是最新价本身
                if top_key == "valuation" and key == "etf.price":
                    continue
                if top_key == "valuation":
                    _short_key = key.split(".")[-1]
                    if _short_key in _EXCLUDE_FROM_VALUATION:
                        continue
                for prefix in prefixes:
                    if key.startswith(prefix):
                        values.append((key, _directional(key, float(val))))
                        break
        if not values:
            # 如果没有任何非零匹配子因子，不设置顶层键（让消费方 fallback 到 0.0）
            continue
        # round15 方案三阶段一: IC 衰减加权聚合（冷启动回退等权）
        _lam = math.log(2) / IC_HALF_LIFE
        weights: list[float] = []
        directed: list[float] = []
        for key, v in values:
            series = (ic_series or {}).get(key)
            if series and len(series) >= IC_MIN_BATCHES:
                mean_ic = _ic_decay_mean(series, _lam)
                if mean_ic < 0 and abs(mean_ic) > IC_FLIP_THRESHOLD:
                    directed.append(-v)
                    weights.append(abs(mean_ic))
                else:
                    directed.append(v)
                    weights.append(max(mean_ic, 0.0))
            else:
                directed.append(v)
                weights.append(1.0)
        total_w = sum(weights)
        if total_w > 1e-12:
            result[top_key] = sum(w * v for w, v in zip(weights, directed)) / total_w
        else:  # Σw == 0（全部 IC≈0）→ 回退等权
            result[top_key] = sum(directed) / len(directed)

    return result
