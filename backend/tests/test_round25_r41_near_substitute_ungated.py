"""round25 R41: 近替代品冗余控制盘后绕过 + 告警前端不呈现。

问题（round25 §2.4 实证）：`near_substitute_pairs` 调用点嵌套在 `enforce_max_correlation`
内部，而该函数只在 `if corr_matrix:` 时调用（strategy_design）→ 盘后/非交易窗口
corr_matrix 为空 → 近替代品检测整体跳过（「芯片+半导体设备」「港股创新药+港股通创新药」
同主题双入选无告警）。设计意图「独立于 K 线相关系数、降级盲（r=None）也能识别」与实现
「门控在 corr_matrix」矛盾。

修复（round25 R41-a）：
- 新增 `apply_near_substitute_warnings` 独立冗余控制层（无条件执行）；
- `enforce_max_correlation` 不再包裹 near_substitute_pairs；
- strategy_design risk-control 段始终调用新函数（corr_matrix 空也跑）。
"""

import pytest

from app.engine.allocation_engine import (
    apply_near_substitute_warnings,
    enforce_max_correlation,
    near_substitute_pairs,
)


def _chip_pair_allocs():
    """芯片 + 半导体设备（同族）+ 无关标的。"""
    return [
        {"symbol": "588200", "name": "科创芯片ETF", "weight": 0.10},
        {"symbol": "588170", "name": "科创半导体设备ETF", "weight": 0.08},
        {"symbol": "510300", "name": "沪深300ETF", "weight": 0.5},
    ]


def _hk_pharma_allocs():
    """港股创新药 + 港股通创新药（同族）。"""
    return [
        {"symbol": "513120", "name": "港股创新药ETF", "weight": 0.07},
        {"symbol": "159570", "name": "港股通创新药ETF", "weight": 0.06},
        {"symbol": "518880", "name": "黄金ETF", "weight": 0.3},
    ]


class TestApplyNearSubstituteWarnings:
    """R41-a: 独立冗余控制层（无条件执行，不依赖 corr_matrix）。"""

    def test_empty_corr_matrix_still_detects_chip_pair(self):
        """mock corr_matrix={}（盘后）→ 芯片+半导体设备 对仍被识别（负向：漏报 → FAIL）。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        out = apply_near_substitute_warnings(strategies, {})
        warnings = out[0]["risk_metrics"]["correlation_warnings"]
        pairs = {(w["pair"][0], w["pair"][1]) for w in warnings}
        assert ("588200", "588170") in pairs or ("588170", "588200") in pairs, (
            "盘后 corr_matrix 空也必须识别芯片+半导体设备近替代品（R41-a）"
        )
        # r 缺失 → unevaluated
        entry = next(w for w in warnings if "588200" in w["pair"] and "588170" in w["pair"])
        assert entry["type"] in ("near_substitute", "unevaluated")
        assert entry["correlation"] is None

    def test_hk_pharma_pair_detected_without_corr(self):
        """港股创新药+港股通创新药 对在 corr_matrix 空时同样识别。"""
        strategies = [{"id": "balanced", "allocations": _hk_pharma_allocs()}]
        out = apply_near_substitute_warnings(strategies, {})
        warnings = out[0]["risk_metrics"]["correlation_warnings"]
        pairs = {(w["pair"][0], w["pair"][1]) for w in warnings}
        assert ("513120", "159570") in pairs or ("159570", "513120") in pairs, (
            "港股创新药+港股通创新药 近替代品必须被识别"
        )

    def test_r_present_keeps_near_substitute_type(self):
        """r 可算（如 0.35）→ type=near_substitute + correlation 透传。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        corr = {("588170", "588200"): 0.35}
        out = apply_near_substitute_warnings(strategies, corr)
        entry = next(w for w in out[0]["risk_metrics"]["correlation_warnings"]
                     if "588200" in w["pair"] and "588170" in w["pair"])
        assert entry["type"] == "near_substitute"
        assert entry["correlation"] == pytest.approx(0.35, abs=1e-3)

    def test_enforce_max_correlation_no_longer_calls_near_substitute(self):
        """R41-a 验收③: enforce_max_correlation 调用点不再包裹 near_substitute_pairs。"""
        import inspect
        import re
        import app.engine.allocation_engine as ae

        src = inspect.getsource(ae.enforce_max_correlation)
        assert "near_substitute_pairs(" not in src, (
            "enforce_max_correlation 内不得再调用 near_substitute_pairs（已解耦为独立层）"
        )
        # 独立层存在且是调用方
        assert "apply_near_substitute_warnings" in dir(ae)

    def test_enforce_max_correlation_still_does_high_corr_reduction(self):
        """enforce_max_correlation 的高相关削减行为保持（回归保护）。"""
        strategies = [{"id": "balanced", "allocations": _chip_pair_allocs()}]
        corr = {("588170", "588200"): 0.95}
        out = enforce_max_correlation(strategies, corr, threshold=0.9, max_combined_weight=0.1)
        # 高相关对合计 0.18 > 0.1 → 削减低因子分一方
        allocs = {a["symbol"]: a for a in out[0]["allocations"]}
        assert allocs["588170"]["weight"] + allocs["588200"]["weight"] <= 0.1 + 1e-6


class TestStrategyDesignIntegration:
    """R41-a 集成：strategy_design risk-control 段无条件调用独立冗余控制层。"""

    def test_apply_near_substitute_warnings_called_unconditionally(self, monkeypatch):
        """corr_matrix 空（盘后）→ apply_near_substitute_warnings 仍被调用（R41 验收：
        近替代品检测不依赖 corr_matrix，最该在盘后工作的控制不在盘后被关掉）。"""
        import asyncio
        from app.services import strategy_design as sd

        candidates = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
                 "factor_score": 0.2, "price": 3.8, "industry": "宽基"},
            ],
            "satellite": [
                {"symbol": "588200", "name": "科创芯片ETF", "layer": "satellite",
                 "factor_score": 0.5, "price": 1.1, "industry": "半导体"},
                {"symbol": "588170", "name": "科创半导体设备ETF", "layer": "satellite",
                 "factor_score": 0.4, "price": 1.2, "industry": "半导体设备"},
                {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
                 "factor_score": 0.3, "price": 0.9, "industry": "医药"},
            ],
            "defense": [
                {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                 "factor_score": 0.3, "price": 8.3, "industry": "黄金"},
            ],
        }

        class _FakeHub:
            def __init__(self):
                self._by_code = {}
            async def refresh(self): pass
            def get_pool(self, layer=None):
                if layer is None:
                    return candidates
                return candidates.get(layer, [])
            def get_factor_matrix(self): return {}
            def get_market_regime(self): return "range_bound"
            def get_market_sentiment(self): return {"sentiment_index": 50, "sentiment_label": "中性"}
            def get_index_realtime(self): return []
            async def get_global_indices(self): return {}
            def get_sector_momentum(self): return []
            def get_sector_stocks(self, code): return []
            def get_by_code(self, code):
                for layer in candidates.values():
                    for it in layer:
                        if it["symbol"] == code:
                            return it
                return None

        # 关键断言：corr_matrix 空时独立冗余控制层必须被调用（且收到 corr={}）
        calls = []
        orig = sd.apply_near_substitute_warnings
        def _spy(strategies, corr_matrix):
            calls.append(dict(corr=corr_matrix, n=len(strategies)))
            return orig(strategies, corr_matrix)
        monkeypatch.setattr(sd, "apply_near_substitute_warnings", _spy)
        monkeypatch.setattr(sd, "_correlation_matrix_for", lambda allocs, cands: {})
        monkeypatch.setattr(sd, "_correlation_medians_for", lambda allocs, cands: {})
        monkeypatch.setattr(sd, "_factor_data_quality_report", lambda: {"valid_rate": 1.0})
        monkeypatch.setattr(sd, "_data_precision_report", lambda fq: {"mode": "full"})
        import app.services.market_data_hub as mh_mod
        monkeypatch.setattr(mh_mod, "market_data_hub", _FakeHub())

        asyncio.run(sd.generate_enhanced_design(capital=100000))
        assert calls, "apply_near_substitute_warnings 必须在 risk-control 段被调用（R41-a）"
        assert all(c["corr"] == {} for c in calls), (
            "corr_matrix 为空（盘后）也必须调用近替代品控制层（不门控）"
        )

    def test_source_wires_near_substitute_independent_of_corr_gate(self):
        """源码级断言：strategy_design 中 apply_near_substitute_warnings 不在
        `if corr_matrix:` 分支内（独立调用）。"""
        import inspect
        import re
        import app.services.strategy_design as sd

        src = inspect.getsource(sd.generate_enhanced_design)
        # 独立调用点存在（不在 enforce 分支内）
        assert "apply_near_substitute_warnings" in src
        # enforce_max_correlation 的调用仍在 if corr_matrix 分支内（高相关约束保持门控）
        # 而 apply 调用在分支外（无条件）——通过源码顺序粗验：enforce 调用后紧跟 apply
        idx_enforce = src.find("enforce_max_correlation([_strat_proxy]")
        idx_apply = src.find("apply_near_substitute_warnings([_strat_proxy]")
        assert idx_enforce != -1 and idx_apply != -1
        assert idx_apply > idx_enforce, "apply 调用应在 enforce 之后（独立层，不嵌套）"