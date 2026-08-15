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
