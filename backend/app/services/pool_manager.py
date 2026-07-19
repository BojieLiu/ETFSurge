"""
PoolManager: unified candidate pool management for the ETF Surge system.

Replaces the hardcoded CANDIDATE_POOL with a dynamic, 5-layer pool
backed by etf_scanner, ETFClassifier, and FactorRegistry.

Lifecycle:
  1. refresh() called daily (or on-demand)
  2. Scanner fetches all ETFs → filters → ranks into 3 base layers
  3. ETFClassifier adds industry/concept metadata
  4. PoolManager assigns 5 layers (core/satellite/defense/opportunistic/research)
  5. MANDATORY_CODES enforced
  6. PoolDiff generated for audit trail
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from ..fetchers import etf_scanner
from ..factors.factor_registry import registry as factor_registry
from .etf_classifier import classifier as etf_classifier
from .pool_audit import pool_audit

logger = logging.getLogger(__name__)

# 强制保留标的（池刷新时永不出池）
MANDATORY_CODES = {"510300", "560600", "518880", "511090"}

# 层名
LAYER_CORE = "core"
LAYER_SATELLITE = "satellite"
LAYER_DEFENSE = "defense"
LAYER_OPPORTUNISTIC = "opportunistic"
LAYER_RESEARCH = "research"
ALL_LAYERS = [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE, LAYER_OPPORTUNISTIC, LAYER_RESEARCH]

# Regime-based weights for each layer
_LAYER_WEIGHTS = {
    "satellite": {
        "bull":       {"factor": 0.55, "liquidity": 0.10, "scale": 0.05, "opp": 0.30},
        "bear":       {"factor": 0.25, "liquidity": 0.10, "scale": 0.05, "opp": 0.60},
        "correction": {"factor": 0.35, "liquidity": 0.15, "scale": 0.10, "opp": 0.40},
        "neutral":    {"factor": 0.40, "liquidity": 0.15, "scale": 0.10, "opp": 0.35},
    },
    "core": {
        "bull":       {"factor": 0.55, "liquidity": 0.20, "scale": 0.25},
        "bear":       {"factor": 0.40, "liquidity": 0.30, "scale": 0.30},
        "correction": {"factor": 0.45, "liquidity": 0.25, "scale": 0.30},
        "neutral":    {"factor": 0.50, "liquidity": 0.25, "scale": 0.25},
    },
    "defense": {
        "bull":       {"factor": 0.35, "liquidity": 0.25, "scale": 0.15, "opp": 0.25},
        "bear":       {"factor": 0.25, "liquidity": 0.20, "scale": 0.15, "opp": 0.40},
        "correction": {"factor": 0.30, "liquidity": 0.25, "scale": 0.20, "opp": 0.25},
        "neutral":    {"factor": 0.30, "liquidity": 0.20, "scale": 0.20, "opp": 0.30},
    },
}
_BASE_WEIGHTS = {"factor": 0.40, "liquidity": 0.15, "scale": 0.10, "opp": 0.35}

# 层内最大数量
MAX_PER_LAYER = {
    LAYER_CORE: 8,
    LAYER_SATELLITE: 20,
    LAYER_DEFENSE: 10,
    LAYER_OPPORTUNISTIC: 8,
    LAYER_RESEARCH: 10,
}


@dataclass
class PoolDiff:
    """差异报告：跟踪两次 refresh 之间的变化。"""

    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    timestamp: str = ""


class PoolManager:
    """候选池管理器。

    Usage:
        pm = PoolManager()
        await pm.refresh()           # 日频刷新
        pool = pm.get_pool()         # 获取全池
        entry = pm.get_by_code("510300")  # 按 code 查询
    """

    def __init__(self):
        self._pool: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}
        self._by_code: dict[str, dict[str, Any]] = {}
        self._version: int = 0
        self.scanner = etf_scanner
        self.classifier = etf_classifier
        self.factor_registry = factor_registry
        self._opportunistic_signals: dict[str, dict] = {}
        self.current_regime: str = "neutral"

    async def refresh(self) -> PoolDiff:
        """全量刷新候选池。

        Returns:
            PoolDiff 差异报告。
        """
        old_by_code = dict(self._by_code)

        # 1. 扫描全市场 → 3 层基础池
        raw_layers = self.scanner.full_pipeline()
        raw_count = sum(len(v) for v in raw_layers.values())
        logger.info("PoolManager: scanned %d ETFs (%d core, %d sat, %d def)",
                     raw_count,
                     len(raw_layers.get("core", [])),
                     len(raw_layers.get("satellite", [])),
                     len(raw_layers.get("defense", [])))

        # 2. 展平为列表做分类
        flat = []
        for layer_name, items in raw_layers.items():
            for item in items:
                flat.append({
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "amount": item.get("amount", 0),
                    "fund_scale": item.get("fund_scale", 0),
                    "layer": layer_name,
                })

        # 3. ETFClassifier 添加行业/概念
        if flat:
            class_results = self.classifier.batch_classify(flat)
            for item in flat:
                sym = item["symbol"]
                info = class_results.get(sym, {})
                item["industry"] = info.get("industry", "unknown")
                item["concepts"] = info.get("concepts", [])
                item["classify_confidence"] = info.get("confidence", 0.0)

        # 3b. FactorRegistry 计算因子得分
        if flat:
            symbols = [e["symbol"] for e in flat if e.get("symbol")]
            try:
                factor_scores = await self.factor_registry.compute(symbols)
                for item in flat:
                    sym = item["symbol"]
                    item["factor_scores"] = factor_scores.get(sym, {})
            except Exception as e:
                logger.warning("FactorRegistry compute failed: %s", e)
                for item in flat:
                    item["factor_scores"] = {}

        # 4. 分配到 5 层（含 opportunistic 信号注入）
        new_pool: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}

        # 4a. 注入 opportunistic 信号
        if self._opportunistic_signals:
            for sym, signal in self._opportunistic_signals.items():
                new_pool[LAYER_OPPORTUNISTIC].append({
                    "symbol": sym,
                    "name": signal.get("name", sym),
                    "layer": LAYER_OPPORTUNISTIC,
                    "industry": signal.get("industry", "unknown"),
                    "concepts": signal.get("concepts", []),
                    "factor_scores": {},
                    "composite_score": signal.get("heat_score", 0.5),
                    "opp_signal": signal.get("signal", ""),
                    "opp_reason": signal.get("reason", ""),
                })

        for item in flat:
            base_layer = item.get("layer", LAYER_SATELLITE)
            industry = item.get("industry", "unknown")

            # Core: 宽基指数
            if base_layer == "core" or industry == "宽基指数":
                target = LAYER_CORE
            # Defense: 商品/固收/跨境
            elif base_layer == "defense" or industry in ("商品", "固收", "跨境"):
                target = LAYER_DEFENSE
            # Research: unknown industry
            elif industry == "unknown":
                target = LAYER_RESEARCH
            else:
                target = LAYER_SATELLITE

            item["layer"] = target
            item["composite_score"] = 0.0
            new_pool[target].append(item)

        # 5. 强制保底
        self._ensure_mandatory(new_pool, flat)

        # 6. 层内复合评分 + 截断
        for layer in ALL_LAYERS:
            for item in new_pool[layer]:
                item["composite_score"] = self._compute_composite(item, layer, regime=self.current_regime)
            max_n = MAX_PER_LAYER.get(layer, 10)
            scored = sorted(new_pool[layer], key=lambda x: x.get("composite_score", 0), reverse=True)
            new_pool[layer] = scored[:max_n]

        # 7. 重建索引
        self._pool = new_pool
        self._rebuild_index()
        self._version += 1

        # 8. 计算 diff
        diff = self._compute_diff(old_by_code)
        diff.version = self._version
        diff.timestamp = datetime.now().isoformat()

        # 9. 审计日志
        pool_audit.log_refresh(diff)

        logger.info("PoolManager: refresh complete (v%d, %d total)",
                     self._version,
                     sum(len(v) for v in self._pool.values()))
        return diff

    def _ensure_mandatory(
        self,
        pool: dict[str, list[dict[str, Any]]],
        flat: list[dict[str, Any]],
    ) -> None:
        """确保 MANDATORY_CODES 在池中（如果全市场扫描有结果）。"""
        if not flat:
            return  # 扫描失败，不强行注入（直接报错）
        for code in MANDATORY_CODES:
            in_pool = any(
                e["symbol"] == code for layer in pool.values() for e in layer
            )
            if not in_pool:
                # 从 flat 中找回
                found = next((e for e in flat if e["symbol"] == code), None)
                if found:
                    # 按代码推断层
                    if code in ("510300", "560600"):
                        target = LAYER_CORE
                    elif code in ("518880",):
                        target = LAYER_DEFENSE
                    elif code == "511090":
                        target = LAYER_DEFENSE
                    else:
                        target = LAYER_SATELLITE
                    found["layer"] = target
                    pool[target].append(found)
                    logger.info("PoolManager: enforced mandatory %s -> %s", code, target)

    def _compute_composite(self, item: dict[str, Any], layer: str, regime: str = "neutral") -> float:
        """按层+市况计算综合得分。"""
        factor_scores = item.get("factor_scores", {})
        factor_sum = sum(factor_scores.values()) if factor_scores else 0
        amount = float(item.get("amount", 0) or 0)
        scale = float(item.get("fund_scale", 0) or 0)
        opp_score = float(item.get("composite_score", 0.5))

        layer_weights = _LAYER_WEIGHTS.get(layer, {})
        w = layer_weights.get(regime, layer_weights.get("neutral", _BASE_WEIGHTS))

        if layer in ("core", "satellite", "defense", "opportunistic"):
            score = w["factor"] * factor_sum
            score += w.get("liquidity", 0) * amount * 1e-9
            score += w.get("scale", 0) * scale * 1e-9
            if layer != "core":
                score += w.get("opp", 0) * opp_score
        else:
            score = amount * 1e-9  # research: liquidity only

        return score

    def set_opportunistic_signals(self, signals: dict[str, dict]) -> None:
        """设置外部机会信号（用于 Layer 4）。

        Args:
            signals: {symbol: {"signal": str, "heat_score": float, ...}}
        """
        self._opportunistic_signals = signals
        logger.info("PoolManager: set %d opportunistic signals", len(signals))

    def _rebuild_index(self) -> None:
        """重建 symbol → entry 索引。"""
        self._by_code = {}
        for layer_items in self._pool.values():
            for item in layer_items:
                sym = item.get("symbol", "")
                if sym:
                    self._by_code[sym] = item

    def _compute_diff(
        self,
        old_by_code: dict[str, dict[str, Any]],
    ) -> PoolDiff:
        """计算新旧池之间的差异。"""
        new_by_code = self._by_code
        added = []
        removed = []
        changed = []

        for sym, entry in new_by_code.items():
            if sym not in old_by_code:
                added.append(entry)
            elif entry.get("layer") != old_by_code[sym].get("layer"):
                changed.append(entry)

        for sym, entry in old_by_code.items():
            if sym not in new_by_code:
                removed.append(entry)

        return PoolDiff(added=added, removed=removed, changed=changed)

    def get_pool(self, layer: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
        """获取候选池。

        Args:
            layer: 指定层名。None 返回全池。
        """
        if layer:
            return self._pool.get(layer, [])
        return self._pool

    def get_by_code(self, symbol: str) -> dict[str, Any] | None:
        """按代码查询单个 ETF。"""
        return self._by_code.get(symbol)


# Global singleton
pool_manager = PoolManager()
