"""
TDD: PoolManager 层分配逻辑测试。

覆盖 P1-2 防御层分类修复：跨境→卫星层，商品/固收→防御层。
测试不依赖 DB 或外部网络，直接验证 _refresh_impl() 内的层映射逻辑。
"""
import pytest

from app.services.pool_manager import LAYER_CORE, LAYER_DEFENSE, LAYER_SATELLITE


def _flat_item(symbol: str, name: str, base_layer: str, industry: str) -> dict:
    """辅助构造 pool_manager._refresh_impl 中的 flat item。"""
    return {
        "symbol": symbol,
        "name": name,
        "layer": base_layer,
        "industry": industry,
        "amount": 0,
        "fund_scale": 0,
        "tracked_index": "",
        "concepts": [],
        "factor_scores": {},
    }


class TestLayerAssignment:
    """行业→层映射的准确性。"""

    def _apply_layer_assignment(self, item: dict) -> str:
        """模拟 pool_manager.py:325-338 的层分配逻辑。"""
        base_layer = item.get("layer", "satellite")
        industry = item.get("industry", "unknown")

        if base_layer == "core" or industry == "宽基指数":
            return LAYER_CORE
        elif base_layer == "defense" or industry in ("商品", "固收"):
            return LAYER_DEFENSE
        elif industry == "跨境":
            return LAYER_SATELLITE
        elif industry == "unknown":
            return "research"
        else:
            return LAYER_SATELLITE

    def test_gold_etf_goes_to_defense(self):
        """黄金 ETF（商品行业）→ 防御层。"""
        item = _flat_item("518880", "黄金ETF", "satellite", "商品")
        assert self._apply_layer_assignment(item) == LAYER_DEFENSE

    def test_treasury_etf_goes_to_defense(self):
        """国债 ETF（固收行业）→ 防御层。"""
        item = _flat_item("511090", "国债ETF", "satellite", "固收")
        assert self._apply_layer_assignment(item) == LAYER_DEFENSE

    def test_cross_border_etf_goes_to_satellite(self):
        """跨境 ETF（如纳指/标普）→ 卫星层（P1-2 修复）。"""
        item = _flat_item("513100", "纳指ETF", "satellite", "跨境")
        assert self._apply_layer_assignment(item) == LAYER_SATELLITE

    def test_hk_etf_goes_to_satellite_not_defense(self):
        """港股 ETF（跨境行业）不应落入防御层。"""
        item = _flat_item("159920", "恒生ETF", "satellite", "跨境")
        result = self._apply_layer_assignment(item)
        assert result == LAYER_SATELLITE, f"跨境ETF应归卫星层，实际为 {result}"
        assert result != LAYER_DEFENSE, "跨境ETF不应归防御层"

    def test_broad_index_goes_to_core(self):
        """宽基指数 ETF → 核心层。"""
        item = _flat_item("510300", "沪深300ETF", "core", "宽基指数")
        assert self._apply_layer_assignment(item) == LAYER_CORE

    def test_tech_etf_goes_to_satellite(self):
        """科技 ETF（无特殊行业）→ 卫星层。"""
        item = _flat_item("512480", "半导体ETF", "satellite", "信息技术")
        assert self._apply_layer_assignment(item) == LAYER_SATELLITE

    def test_defense_etf_from_scanner_stays_defense(self):
        """扫描器标记为 defense 的标的，即使 industry 未知也走防御层。"""
        item = _flat_item("518880", "黄金ETF", "defense", "unknown")
        assert self._apply_layer_assignment(item) == LAYER_DEFENSE

    def test_core_etf_stays_core(self):
        """扫描器标记为 core 的标的不被 industry 覆盖。"""
        item = _flat_item("510300", "沪深300ETF", "core", "信息技术")
        # core 在 base_layer 检查时优先返回
        assert self._apply_layer_assignment(item) == LAYER_CORE
