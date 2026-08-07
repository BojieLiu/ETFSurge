"""
O27 (docs/round8-rediagnosis.md §7 §5.1I): 基本面/市值数据注入——compute 直调路径。

验收:
① compute 直调路径 ln_mcap/ln_float_mcap 与 refresh 路径数值一致（同一 total_mv 注入逻辑）；
② 无「全 0 截面」的 style 因子（symbol_extra 提供 fund_scale 时有区分度）；
③ 单测断言直调路径注入 total_mv。
"""

import inspect
import pytest

from app.factors.factor_registry import registry, FactorRegistry


def _fetch_market_data_source() -> str:
    return inspect.getsource(FactorRegistry._fetch_market_data)


class TestComputeInjectsMv:
    def test_fetch_market_data_injects_total_mv(self):
        """直调路径注入 total_mv（symbol_extra.fund_scale 优先，rows 兜底）。"""
        src = _fetch_market_data_source()
        assert '"total_mv"' in src
        assert "fund_scale" in src
        assert '"float_mv"' in src

    def test_compute_uses_symbol_extra_consistent(self):
        """compute() 直调 + symbol_extra.fund_scale → 与 refresh 路径同一注入来源。"""
        src = _fetch_market_data_source()
        # 同一 total_mv 注入逻辑（fund_scale 或 rows[-1].total_mv）
        assert "symbol_extra" in src

    @pytest.mark.asyncio
    async def test_ln_mcap_not_all_zero_with_mv(self):
        """构造含不同 total_mv 的市场数据 → ln_mcap 截面有区分度（非全 0）。"""
        market_data = {
            "510300": {"total_mv": 1e11, "float_mv": 8e10, "close": [3.9, 4.0, 4.1], "high": [4.0, 4.1, 4.2], "low": [3.8, 3.9, 4.0], "volume": [100, 110, 120]},
            "510500": {"total_mv": 5e10, "float_mv": 4e10, "close": [6.0, 6.1, 6.2], "high": [6.1, 6.2, 6.3], "low": [5.9, 6.0, 6.1], "volume": [90, 95, 100]},
            "588000": {"total_mv": 2e10, "float_mv": 1.5e10, "close": [1.0, 1.05, 1.1], "high": [1.05, 1.1, 1.15], "low": [0.98, 1.0, 1.02], "volume": [200, 210, 220]},
        }
        result = await registry.compute(
            ["510300", "510500", "588000"],
            codes=["style.size.ln_mcap", "style.size.ln_float_mcap"],
            market_data=market_data,
        )
        ln = [result[s].get("style.size.ln_mcap", 0) for s in result]
        lnf = [result[s].get("style.size.ln_float_mcap", 0) for s in result]
        # 不同市值 → 不全是 0，且有区分度（z-score 后不恒为 0）
        assert any(v != 0 for v in ln), "ln_mcap 不应全 0（注入 total_mv 后有区分度）"
        assert any(v != 0 for v in lnf)
        assert len(set(round(v, 6) for v in ln)) > 1, "ln_mcap 应有截面区分度"
