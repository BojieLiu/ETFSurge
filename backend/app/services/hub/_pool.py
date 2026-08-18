"""Candidate-pool mixin — split from market_data_hub (Batch 3)."""

import logging
import statistics
from typing import Any

from app.factors.factor_registry import registry as factor_registry
from app.services.hub._common import PoolDiff

logger = logging.getLogger(__name__)

class PoolMixin:
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
        # Check if main pool is empty → try emergency fallback
        if layer:
            pool = self._pool.get(layer, [])
            if not pool:
                logger.warning("[market_data_hub] get_pool('%s') returned empty — main pool may be stale", layer)
            return pool

        total = sum(len(v) for v in self._pool.values())
        if total == 0:
            logger.warning("[market_data_hub] get_pool() called but main pool is empty — data source unavailable")
        return self._pool


    def get_by_code(self, symbol: str) -> dict[str, Any] | None:
        """按代码查询单个 ETF。"""
        return self._by_code.get(symbol)


    @staticmethod
    def _normalize_matrix(
        matrix: dict[str, dict[str, float]],
        raw_codes: set[str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """对因子矩阵做截面 z-score 归一化，消除量纲差异。

        排除 ln_mcap/ln_float_mcap（截面内无意义，所有大盘 ETF 都 ~25），
        排除仅有一两个非零值的因子（归一化会放大噪声）。
        O4 (round7 §7 P6): `standardization=raw` 的因子（rsi_14/rsi_24 等，
        factor_definitions.yaml 声明）跳过截面 z-score，保留真实 0-100 值——
        rationale「RSI<30 超卖」等判断需要真实值而非相对分。
        """
        import statistics
        symbols = list(matrix.keys())
        if not symbols:
            return matrix

        raw = raw_codes or set()

        # 收集所有因子键
        factor_keys: set[str] = set()
        for scores in matrix.values():
            factor_keys.update(k for k, v in scores.items())

        EXCLUDE = {"style.size.ln_mcap", "style.size.ln_float_mcap"}

        for key in factor_keys:
            if key in EXCLUDE:
                # Z09: size 因子做 min-max 归一化（保留截面相对排序、消除量纲），
                # 而非完全跳过——否则原始 ln(mcap)≈25 会作为“25σ”离群值进入 factor_breakdown
                values = [matrix[s].get(key, 0.0) for s in symbols]
                vmin, vmax = min(values), max(values)
                if vmax - vmin < 1e-10:
                    # 截面无区分度（如 total_mv 未注入导致全同）时置中性 0，不泄漏原始量纲值
                    for s in symbols:
                        matrix[s][key] = 0.0
                    continue
                for s in symbols:
                    matrix[s][key] = (matrix[s].get(key, 0.0) - vmin) / (vmax - vmin) * 2.0 - 1.0
                continue
            if key in raw:
                # O4: raw 因子（RSI 0-100 等）跳过截面 z-score——保留真实量纲
                continue
            values = [matrix[s].get(key, 0.0) for s in symbols]
            # 跳过所有值相同的因子（无截面区分度）
            if max(values) - min(values) < 0.001:
                continue
            # 跳过只有一两个非零值的因子（归一化后噪声膨胀）
            non_zero = sum(1 for v in values if abs(v) > 0.001)
            if non_zero < 3:
                continue
            mean = statistics.mean(values)
            std = statistics.stdev(values) or 1.0
            for s in symbols:
                matrix[s][key] = (matrix[s].get(key, 0.0) - mean) / std

        return matrix


    def _raw_factor_codes(self) -> set[str]:
        """O4: factor_definitions.yaml 中 standardization=raw 的因子 code 集合。"""
        raw = set()
        try:
            for code, definition in factor_registry._factors.items():
                if definition.standardization == "raw":
                    raw.add(code)
        except Exception:
            pass
        return raw


    def get_factor_matrix(self) -> dict[str, dict[str, float]]:
        """从候选池提取因子分矩阵，并做 z-score 归一化（raw 因子除外）。"""
        result: dict[str, dict[str, float]] = {}
        for layer_items in self._pool.values():
            for item in layer_items:
                sym = item.get("symbol", "")
                if not sym:
                    continue
                fs = item.get("factor_scores", {})
                result[sym] = {k: v for k, v in fs.items() if isinstance(v, (int, float))}
        if not result:
            logger.warning("[market_data_hub] get_factor_matrix() returned empty — pool may be empty or missing factor_scores")
            return result
        return self._normalize_matrix(result, raw_codes=self._raw_factor_codes())


    def get_akshare_pool_stats(self) -> dict:
        """akshare 池统计（直接委托）。"""
        try:
            from ...fetchers.news_fetcher import get_akshare_pool_stats
            return get_akshare_pool_stats()
        except Exception as e:
            logger.warning("[hub] get_akshare_pool_stats failed: %s", e)
            return {}
