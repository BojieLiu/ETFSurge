# -*- coding: utf-8 -*-
"""round31 R94: 策略检查动量跨路径不一致。

根因（§4.2）：`_COMPOSITE_FACTOR_MAP["momentum"]` 判定的键
（momentum/momentum.recent_return/momentum.vol_ratio）在真实因子分中不存在——
真实动量键是 `etf.return_1m` / `etf.return_3m` / `technical.volume.vol_ratio`，
导致策略检查 composite momentum 恒 0、13/13 全 degraded，而设计 rationale 有真实
动量。`_collect_strategy_data`（strategy_check.py:108）因子计算也未喂 hub kline
缓存（设计路径 `_refresh_impl:330-342` 喂 `_kline_cache` 列式），数据源不一致。

修复：
  ① `_collect_strategy_data` 因子计算喂 `market_data_hub._kline_cache`（与设计同源）；
  ② `_COMPOSITE_FACTOR_MAP["momentum"]` 补真实键（保留旧键兼容既有 mock 用例）。

无网络：纯函数 / monkeypatch 断言。
"""
import pytest


def _fb(return_1m=None, return_3m=None, vol_ratio=None, tech_score=0.5,
        signal="buy", rsi=55.0):
    fs = {}
    if return_1m is not None:
        fs["etf.return_1m"] = return_1m
    if return_3m is not None:
        fs["etf.return_3m"] = return_3m
    if vol_ratio is not None:
        fs["technical.volume.vol_ratio"] = vol_ratio
    fs["technical.rsi.rsi_14"] = rsi
    return {
        "factor_scores": fs,
        "technical_signal": {"score": tech_score, "signal": signal},
        "technical_indicators": {"rsi": rsi, "kdj": {"k": 50, "d": 50, "j": 60}},
    }


class TestMomentumCompositeRealKeys:
    def test_composite_momentum_nonzero_with_real_keys(self):
        """真实动量键存在 → composite_decision.components.momentum != 0（R94 ①）。"""
        from app.services.portfolio.strategy_check import _attach_composite_decisions
        fbs = {"512890": _fb(return_1m=0.14, return_3m=0.514)}
        _attach_composite_decisions(fbs)
        cd = fbs["512890"]["composite_decision"]
        assert cd["components"]["momentum"] != 0, f"momentum 应为非 0，实际 {cd['components']}"
        # 正收益 → 正动量（与设计同向，R94 ③）
        assert cd["components"]["momentum"] > 0

    def test_coverage_stats_momentum_true_with_real_keys(self):
        """`etf.return_1m/return_3m` 存在 → 分项覆盖 momentum=True。"""
        from app.services.portfolio.strategy_check import (
            _component_coverage_stats,
        )
        fbs = {"512890": _fb(return_1m=0.14, return_3m=0.514)}
        ph = _component_coverage_stats(fbs)["per_holding"]["512890"]
        assert ph["components"]["momentum"] is True, f"momentum 组件应已覆盖: {ph}"
        assert ph["filled"] >= 2  # technical + momentum

    def test_negative_return_gives_negative_momentum(self):
        """负收益 → 负动量（方向与设计一致，R94 ③）。"""
        from app.services.portfolio.strategy_check import _attach_composite_decisions
        fbs = {"159338": _fb(return_1m=-2.1, return_3m=-1.5)}
        _attach_composite_decisions(fbs)
        cd = fbs["159338"]["composite_decision"]
        assert cd["components"]["momentum"] < 0

    def test_old_mock_keys_still_detected(self):
        """向后兼容：旧 mock 键 momentum.recent_return 仍被识别（存量测试不破）。"""
        from app.services.portfolio.strategy_check import (
            _component_coverage_stats,
        )
        fbs = {"A": _fb()}
        fbs["A"]["factor_scores"]["momentum.recent_return"] = 1.0
        ph = _component_coverage_stats(fbs)["per_holding"]["A"]
        assert ph["components"]["momentum"] is True


class TestCollectStrategyDataFeedsMarketData:
    @pytest.mark.asyncio
    async def test_compute_receives_hub_kline_cache(self, monkeypatch):
        """`_collect_strategy_data` 因子计算喂 hub kline 缓存（与设计同源，R94 ①）。"""
        import importlib
        sc_mod = importlib.import_module("app.services.portfolio.strategy_check")
        from app.services.market_data_hub import market_data_hub

        # 模拟 hub kline 列式缓存有真实数据
        kline = {"512890": {"close": [1.0, 1.01, 1.02], "high": [1.1] * 3,
                            "low": [0.9] * 3, "volume": [1e7] * 3,
                            "change_pct": [0.1] * 3}}
        monkeypatch.setattr(market_data_hub, "_kline_cache", kline)
        monkeypatch.setattr(market_data_hub, "_kline_cache_ts", 100.0)

        captured = {}

        async def _fake_compute(symbols, codes=None, market_data=None, symbol_extra=None):
            captured["market_data"] = market_data
            return {s: {"etf.return_1m": 0.14} for s in symbols}

        monkeypatch.setattr(sc_mod._facade(), "_compute_indicators",
                            lambda symbols: {})
        # factor_registry.compute 在函数内晚绑定 import → patch 模块属性
        import app.factors.factor_registry as freg
        monkeypatch.setattr(freg.registry, "compute", _fake_compute)

        indicators, factor_scores = await sc_mod._collect_strategy_data(["512890"])
        assert captured.get("market_data") is kline, \
            f"应喂 hub._kline_cache，实际 {captured.get('market_data')}"
        assert factor_scores["512890"]["etf.return_1m"] == 0.14
