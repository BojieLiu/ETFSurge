"""round22 E5 (docs/archived/engine-refactor-spec-round22.md §1 E5): 设计路径相关性约束
在非交易窗口 / K 线相关性矩阵缺失时**不得静默跳过**——降级标注
risk_metrics.correlation_unchecked=True，供前端提示「关联度未校验」。

TDD 负向断言（先写、先于实现、当前应 FAIL）：
- 非交易窗口（_CORR_CLOSES_CACHE 为空 → _correlation_matrix_for 返回 {}）→ 三方案
  correlation_unchecked 均为 True。旧实现 `if corr_matrix:` 静默跳过、无任何标注 → FAIL。
- 交易窗口（_CORR_CLOSES_CACHE 含标的收盘 → 相关性矩阵非空）→ correlation_unchecked 不置
  （缺省/false），不误标。

驱动主链路（非静态池兜底分支）：mock get_pool 非空 + stub engine_allocate 返回 3 方案，
使逐方案循环真正到达相关性分支；相关性矩阵由真实 _correlation_matrix_for 依据缓存自然产出。
"""

import pytest
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
