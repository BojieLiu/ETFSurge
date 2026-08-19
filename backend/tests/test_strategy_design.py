from __future__ import annotations
"""Phase 2.8 G2/G4: strategy_design + database tests."""

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_empty_candidate_pool_returns_error():
    """候选池为空时，编排器返回 error 而非空策略。"""
    from app.services.strategy_design import generate_enhanced_design

    # get_pool() is called with layer argument, return empty list for each
    async def mock_refresh(*args, **kwargs):
        pass

    with patch("app.services.market_data_hub.market_data_hub.refresh",
               side_effect=mock_refresh):
        with patch("app.services.market_data_hub.market_data_hub.get_pool",
                   side_effect=lambda layer=None: {"core": [], "satellite": [], "defense": []} if layer is None else []):
            with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
                       return_value={}):
                with patch("app.services.market_data_hub.market_data_hub.get_market_regime",
                           return_value="range_bound"):
                    with patch("app.services.market_data_hub.market_data_hub.get_market_sentiment",
                               return_value={"sentiment_index": 50, "sentiment_label": "中性"}):
                        with patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
                                   return_value=[]):
                            with patch("app.services.market_data_hub.market_data_hub.get_sector_momentum",
                                       return_value=[]):
                                result = await generate_enhanced_design(capital=500000)

    # When pool is empty, the code falls back to static pool — it should
    # still produce valid strategies (defensive/balanced/aggressive)
    assert "strategies" in result, f"Expected strategies, got: {result}"
    assert len(result["strategies"]) == 3, f"Expected 3 strategies, got {len(result.get('strategies', []))}"


@pytest.mark.asyncio
async def test_inner_empty_factor_matrix_triggers_static_pool_fallback():
    """R77 (round29): factor_matrix 外层非空、内层全空（{"510300":{}}）应视为因子数据
    不可用，触发静态池兜底（degradation.mode='static_pool'），而非产出 100% 现金。"""
    from app.services.strategy_design import generate_enhanced_design

    async def mock_refresh(*args, **kwargs):
        pass

    with patch("app.services.market_data_hub.market_data_hub.refresh",
               side_effect=mock_refresh):
        with patch("app.services.market_data_hub.market_data_hub.get_pool",
                   side_effect=lambda layer=None: {"core": [{"symbol": "510300", "name": "300ETF", "layer": "core"}],
                                                    "satellite": [], "defense": []} if layer is None else [{"symbol": "510300", "name": "300ETF", "layer": "core"}]):
            with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
                       return_value={"510300": {}, "518880": {}}):
                with patch("app.services.market_data_hub.market_data_hub.get_market_regime",
                           return_value="range_bound"):
                    with patch("app.services.market_data_hub.market_data_hub.get_market_sentiment",
                               return_value={"sentiment_index": 50, "sentiment_label": "中性"}):
                        with patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
                                   return_value=[]):
                            with patch("app.services.market_data_hub.market_data_hub.get_sector_momentum",
                                       return_value=[]):
                                result = await generate_enhanced_design(capital=500000)

    # R77: 内层全空矩阵应被判为 factor_matrix_empty（触发静态池兜底，而非产出 100% 现金失败）
    assert result.get("degradation", {}).get("factor_matrix_empty") is True, (
        f"Expected factor_matrix_empty=True for inner-empty matrix, got: {result.get('degradation')}"
    )
    # 兜底应产出有效方案（非 error/空），杜绝「所有方案均为100%现金」假失败
    assert "error" not in result, f"Inner-empty factor matrix must not fail design: {result.get('error')}"
    assert len(result["strategies"]) == 3, f"Expected 3 strategies, got {len(result.get('strategies', []))}"
    # 兜底路径的降级标记应暴露因子矩阵不可用
    assert result.get("degradation", {}).get("factor_matrix_empty") is True


# ===== folded from test_round22_e5_correlation_unchecked.py =====
from unittest.mock import patch
from contextlib import ExitStack
def _fake_strategies():
    """3 套方案，每套含 2 只非 CASH 持仓——足以触发相关性分支。"""
    def _mk(sid, syms):
        return {
            "id": sid,
            "name": sid,
            "layer_budget": {"core": 0.5, "satellite": 0.2, "defense": 0.15},
            "allocations": [
                {"symbol": s[0], "name": s[0], "layer": s[1], "weight": 0.3, "factor_score": 0.6}
                for s in syms
            ],
        }
    return [
        _mk("defensive", [("510300", "core"), ("518880", "defense")]),
        _mk("balanced", [("510300", "core"), ("159338", "core")]),
        _mk("aggressive", [("159338", "core"), ("512480", "satellite")]),
    ]
def _mock_design_path(corr_closes=None):
    """进入后 design 主链路全部依赖被 mock。
    corr_closes 非空 → _correlation_medians_for 被 stub 直接填充 _CORR_CLOSES_CACHE
    （模拟交易窗口，矩阵非空）；留空 → 缓存空（模拟非交易窗口，矩阵缺失）。"""
    stack = ExitStack()

    async def mock_refresh(*_a, **_k):
        return None

    # 候选池非空 → 不走静态池兜底分支（否则相关性循环被早返回跳过）
    _pool = {
        "core": [{"symbol": "510300", "name": "沪深300", "layer": "core", "factor_score": 0.6}],
        "satellite": [{"symbol": "512480", "name": "医药", "layer": "satellite", "factor_score": 0.5}],
        "defense": [{"symbol": "518880", "name": "黄金", "layer": "defense", "factor_score": 0.4}],
    }

    def _fake_get_pool(layer=None):
        # get_pool 按层返回（与真实 market_data_hub.get_pool 签名一致），
        # 否则 candidates["core"] 收到整字典 → _find_candidate_meta 遍历字符串键报错
        if layer is None:
            return _pool
        return _pool.get(layer, [])

    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.refresh", side_effect=mock_refresh)
    )
    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.get_pool", side_effect=_fake_get_pool)
    )
    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.get_factor_matrix", return_value={})
    )
    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound")
    )
    stack.enter_context(
        patch(
            "app.services.market_data_hub.market_data_hub.get_market_sentiment",
            return_value={"sentiment_index": 50, "sentiment_label": "中性"},
        )
    )
    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.get_index_realtime", return_value=[])
    )
    stack.enter_context(
        patch("app.services.market_data_hub.market_data_hub.get_sector_momentum", return_value=[])
    )
    # stub 引擎分配（避免重型真实 allocate），保留逐方案相关性循环
    stack.enter_context(
        patch("app.services.strategy_design.engine_allocate", side_effect=lambda **_k: _fake_strategies())
    )
    # stub 风控（保留真实 allocs 符号/权重，便于相关性分支消费）
    stack.enter_context(
        patch(
            "app.services.strategy_design.apply_risk_controls",
            side_effect=lambda plans, *_a, **_k: plans,
        )
    )
    # 始终 stub _correlation_medians_for（真实函数依赖 run_in_thread 线程池拉 K 线，
    # 测试环境不执行/会阻塞）→ 避免网络；交易窗口顺带把收盘序列写进 _CORR_CLOSES_CACHE，
    # 使 _correlation_matrix_for 自然返回非空矩阵；非交易窗口不写缓存 → 矩阵缺失
    def _fake_medians(allocs, candidates):
        if corr_closes is not None:
            import app.services.strategy_design as _sd
            _sd._CORR_CLOSES_CACHE.update(corr_closes)
        return {}
    stack.enter_context(
        patch("app.services.strategy_design._correlation_medians_for", side_effect=_fake_medians)
    )
    return stack
@pytest.mark.asyncio
async def test_nontrading_window_sets_correlation_unchecked():
    """非交易窗口（相关性矩阵缺失）→ 三方案均标注 correlation_unchecked=True。"""
    from app.services.strategy_design import generate_enhanced_design

    with _mock_design_path():
        result = await generate_enhanced_design(capital=500000)

    strategies = result["strategies"]
    assert len(strategies) == 3, f"期望 3 方案，实得 {len(strategies)}"
    for s in strategies:
        rm = s.get("risk_metrics") or {}
        assert rm.get("correlation_unchecked") is True, (
            f"方案 {s.get('id')} 非交易窗口未标注 correlation_unchecked——"
            f"相关性约束被静默跳过（E5 回归）"
        )
@pytest.mark.asyncio
async def test_trading_window_does_not_set_correlation_unchecked():
    """交易窗口（相关性矩阵可用）→ 不置 correlation_unchecked（不误标、不静默跳过）。"""
    from app.services.strategy_design import generate_enhanced_design

    # 注入收盘序列（≥2 只、≥20 根）→ _correlation_matrix_for 自然返回非空矩阵
    _closes = {c: [float(i) for i in range(60)] for c in ("510300", "159338", "512480", "518880")}
    with _mock_design_path(corr_closes=_closes):
        result = await generate_enhanced_design(capital=500000)

    for s in result["strategies"]:
        rm = s.get("risk_metrics") or {}
        assert not rm.get("correlation_unchecked"), (
            f"方案 {s.get('id')} 交易窗口不应置 correlation_unchecked"
        )


# ===== folded from test_z11_degradation.py =====
from unittest.mock import patch, AsyncMock, MagicMock
def _make_hub(**overrides):
    """Build a fake market_data_hub with overridable methods."""
    hub = MagicMock()
    hub.refresh = AsyncMock()
    hub.get_market_regime.return_value = "range_bound"
    hub.get_factor_matrix.return_value = {}
    hub.get_pool.side_effect = lambda layer=None: ([] if layer is None else [])
    hub.get_by_code.return_value = None
    hub.etf_pool = None
    for k, v in overrides.items():
        setattr(hub, k, v)
    return hub
class TestDesignDegradation:
    """Z11: generate_enhanced_design degradation modes."""

    @pytest.mark.asyncio
    async def test_empty_pool_static_mode_three_strategies(self):
        """Empty pool -> static_pool degradation, exactly 3 strategies, layer weights from STRATEGY_META."""
        from app.services.strategy_design import generate_enhanced_design

        hub = _make_hub()
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        strategies = result["strategies"]
        assert len(strategies) == 3, f"expected 3 strategies, got {len(strategies)}"
        profiles = {s["id"] for s in strategies}
        assert profiles == {"defensive", "balanced", "aggressive"}

        degradation = result["degradation"]
        assert degradation["mode"] == "static_pool"
        assert degradation["factor_matrix_empty"] is True
        assert degradation["pool_empty"] is True
        assert len(degradation["static_pool_used"]) == 6

        # Layer weights must derive from STRATEGY_META.layer_budget (equal-weight within layer)
        from app.engine.budgets import STRATEGY_META
        balanced = next(s for s in strategies if s["id"] == "balanced")
        budget = STRATEGY_META["balanced"]["layer_budget"]
        etfs = balanced["etfs"]
        non_cash = [e for e in etfs if e["symbol"] != "CASH"]
        core_etfs = [e for e in non_cash if e["layer"] == "core"]
        assert len(core_etfs) == 2  # 510300 + 510050
        expected_per = round(budget["core"] / len(core_etfs), 4)
        assert core_etfs[0]["weight"] == pytest.approx(expected_per)
        # Weights sum to layer budget
        core_sum = sum(e["weight"] for e in core_etfs)
        assert core_sum == pytest.approx(budget["core"])

    @pytest.mark.asyncio
    async def test_normal_path_degradation_normal(self):
        """Healthy pipeline -> degradation.mode='normal'."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"},
                     {"symbol": "510050", "name": "上证50ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        factor_matrix = {
            "510300": {"trend_1m": 0.5, "momentum_20d": 0.4},
            "510050": {"trend_1m": 0.3},
            "159915": {"trend_1m": -0.2},
            "511090": {"trend_1m": 0.1},
        }
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value=factor_matrix),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        assert result["degradation"]["mode"] == "normal"
        assert len(result["strategies"]) == 3

    @pytest.mark.asyncio
    async def test_partial_factor_matrix_partial_data(self):
        """Some symbols missing from factor matrix -> partial_data mode, still 3 strategies."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        # 510300 has factor data; others missing
        factor_matrix = {"510300": {"trend_1m": 0.5}}
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value=factor_matrix),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            result = await generate_enhanced_design(capital=500000)

        assert result["degradation"]["mode"] == "partial_data"
        assert result["degradation"]["factor_matrix_empty"] is False
        assert len(result["strategies"]) == 3

    @pytest.mark.asyncio
    async def test_pipeline_exception_fallback_three_strategies(self):
        """allocate() raises -> fallback 3 strategies + degradation static_pool."""
        from app.services.strategy_design import generate_enhanced_design

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511090", "name": "国开债ETF", "layer": "defense"}],
        }
        hub = _make_hub(
            get_factor_matrix=MagicMock(return_value={"510300": {"trend_1m": 0.5}}),
            get_pool=MagicMock(side_effect=lambda layer=None: (pool if layer is None else pool.get(layer, []))),
        )
        with patch("app.services.market_data_hub.market_data_hub", hub):
            with patch("app.services.strategy_design.engine_allocate",
                       side_effect=RuntimeError("engine exploded")):
                result = await generate_enhanced_design(capital=500000)

        assert len(result["strategies"]) == 3
        assert result["degradation"]["mode"] == "static_pool"


# ===================================================================
# merged from test_round24_data_precision.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round24 R3: 降级态「精确数字」治理——data_precision 精度标识。

问题（round24 §2.1 实证）：design 570 `factor_data_quality.valid_rate=0.0%` +
「方案仅供参考」横幅，但 UI 仍呈现 5%/15%/21% 精确权重与 -0.99/-0.96 精确因子分
→ 降级诚实了、数字没诚实，专业投资者无法分辨可信边界。

契约：`api-contracts/portfolio/design-precision.md`。
本测试锁定 `_data_precision_report` 纯函数：降级→coarse（权重 5% 档位 + 因子分分档
+ 缺失百分比），正常→exact，输入缺失→exact（不误报降级）。
"""

from app.services.strategy_design import _data_precision_report


def test_degraded_gives_coarse_mode():
    """valid_rate=0 + degraded=True → coarse：权重档位 5%、因子分分档、缺失 100%。"""
    p = _data_precision_report({"valid_rate": 0.0, "degraded": True})
    assert p["mode"] == "coarse"
    assert p["weight_display"] == "coarse"
    assert p["weight_step_pct"] == 5.0
    assert p["factor_score_display"] == "bucket"
    assert p["factor_missing_pct"] == 100.0
    assert "100%" in p["note"]


def test_healthy_gives_exact_mode():
    """valid 率 82% 且未降级 → exact：呈现精确权重/因子分（现状不变）。"""
    p = _data_precision_report({"valid_rate": 0.82, "degraded": False})
    assert p["mode"] == "exact"
    assert p["weight_display"] == "exact"
    assert p["weight_step_pct"] is None
    assert p["factor_score_display"] == "exact"
    assert p["factor_missing_pct"] == 18.0


def test_missing_input_defaults_to_exact():
    """统计不可用（空 dict / None）→ exact，不得误报降级（负向断言）。"""
    for bad in (None, {}, {"note": "因子数据质量统计不可用"}):
        p = _data_precision_report(bad)
        assert p["mode"] == "exact", f"输入 {bad!r} 误报降级"


def test_partial_valid_rate_below_threshold_is_coarse():
    """valid 率 40% < 60% 阈值 → coarse（即使调用方未显式传 degraded）。"""
    p = _data_precision_report({"valid_rate": 0.40})
    assert p["mode"] == "coarse"
    assert p["factor_missing_pct"] == 60.0


def test_precision_never_mutates_weights():
    """data_precision 只影响呈现——函数为纯计算，不含任何 allocations 字段。"""
    p = _data_precision_report({"valid_rate": 0.0, "degraded": True})
    assert "allocations" not in p and "target_weight" not in p
    assert set(p) == {
        "mode", "factor_valid_rate", "factor_missing_pct",
        "weight_display", "weight_step_pct", "factor_score_display", "note",
    }


# ===================================================================
# merged from test_round28_fixes.py::TestR59DesignDegradeRetry (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR59DesignDegradeRetry:
    """round28 §14.4.2 ②: 数据采集超时后以 skip_refresh=True 重试（缓存快照兜底），
    产出降级方案（degradation.mode=degraded）而非「方案生成超时」失败。"""

    @staticmethod
    def _apply_engine_path_mocks(monkeypatch):
        """打桩 generate_enhanced_design 引擎路径所需全部依赖（池非空 → 走 engine 分支）。"""
        from app.services.market_data_hub import market_data_hub as hub
        from app.services import strategy_design as sd

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511010", "name": "国债ETF", "layer": "defense"}],
        }

        def _fake_get_pool(layer=None):
            return pool.get(layer, []) if layer else pool

        monkeypatch.setattr(hub, "get_factor_matrix", lambda: {
            "510300": {"technical.ma.sma_5": 0.5},
            "159915": {"momentum.20d": 0.4},
            "511010": {"valuation.pe": -0.3},
        })
        monkeypatch.setattr(hub, "get_pool", _fake_get_pool)
        monkeypatch.setattr(hub, "get_market_regime", lambda: "range_bound")
        monkeypatch.setattr(hub, "get_sector_momentum", lambda: [])
        monkeypatch.setattr(hub, "get_by_code", lambda *a: {})
        monkeypatch.setattr(hub, "get_asset_realtime",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(sd, "_build_market_context", AsyncMock(return_value={}))
        monkeypatch.setattr(sd, "_market_data_fetched_at", lambda *a: "2026-08-18T00:00:00Z")
        monkeypatch.setattr(sd, "engine_allocate", lambda **kw: [{
            "id": "balanced", "label": "平衡型", "layer_budget": {},
            "allocations": [
                {"symbol": "510300", "name": "沪深300ETF", "weight": 0.3, "layer": "core"},
                {"symbol": "159915", "name": "创业板ETF", "weight": 0.2, "layer": "satellite"},
            ],
        }])
        monkeypatch.setattr(sd, "apply_risk_controls",
                            lambda allocs, fm, **kw: allocs)
        monkeypatch.setattr(sd, "_correlation_medians_for", lambda *a: {})
        monkeypatch.setattr(sd, "_correlation_matrix_for", lambda *a: {})
        monkeypatch.setattr(sd, "build_rationale", lambda **kw: "理由")
        monkeypatch.setattr(sd, "_find_candidate_meta", lambda *a: {})
        monkeypatch.setattr(sd, "_kline_change_pct", lambda *a: None)
        monkeypatch.setattr(sd, "_snapshot_change_pct", lambda *a: None)
        monkeypatch.setattr(sd, "_validate_target_amount_consistency", lambda *a: None)

    @pytest.mark.asyncio
    async def test_skip_refresh_skips_refresh_and_marks_degraded(self, monkeypatch):
        """skip_refresh=True → refresh() 不调用、hub._degraded=True、degradation.mode='degraded'。"""
        from app.services.market_data_hub import market_data_hub as hub
        self._apply_engine_path_mocks(monkeypatch)

        refresh_calls = []

        async def _no_refresh():
            refresh_calls.append(1)
        monkeypatch.setattr(hub, "refresh", _no_refresh)

        try:
            from app.services.strategy_design import generate_enhanced_design
            result = await generate_enhanced_design(capital=500000, skip_refresh=True)
        finally:
            hub._degraded = False  # 重置单例状态防串扰

        assert refresh_calls == [], f"skip_refresh 时不得调用 refresh()，实际 {len(refresh_calls)} 次"
        assert result["degradation"]["mode"] == "degraded", \
            f"skip_refresh 降级重试应标注 degradation.mode=degraded，实际 {result['degradation']['mode']}"
        assert "降级" in result["degradation"]["reason"]
        assert result["degradation"]["pool_degraded"] is True
        assert len(result["strategies"]) >= 1, "降级重试仍应产出可用方案（非失败）"

    @pytest.mark.asyncio
    async def test_off_hours_with_pool_skips_realtime_refresh(self, monkeypatch):
        """R59⑤: 非交易时段 + last-good 池 → 主动走快照（不调 refresh 干等实时源）。"""
        from app.services.market_data_hub import market_data_hub as hub
        self._apply_engine_path_mocks(monkeypatch)

        refresh_calls = []

        async def _no_refresh():
            refresh_calls.append(1)
        monkeypatch.setattr(hub, "refresh", _no_refresh)
        monkeypatch.setattr(hub, "_is_market_hours", lambda: False)
        # R59⑤ 判定依赖 _pool 非空（last-good 池存在）——注入假池（monkeypatch 自动还原）
        monkeypatch.setattr(hub, "_pool", {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511010", "name": "国债ETF", "layer": "defense"}],
        })

        try:
            from app.services.strategy_design import generate_enhanced_design
            result = await generate_enhanced_design(capital=500000)
        finally:
            hub._degraded = False

        assert refresh_calls == [], f"盘后 + 池非空时应跳过 refresh，实际 {len(refresh_calls)} 次"
        assert result["degradation"]["pool_degraded"] is True
        assert len(result["strategies"]) >= 1
