from __future__ import annotations
"""R6-F5 (round6 §十 R6-06): 信号口径统一——策略检查 tech_signal 与 /market/signal 同源。

背景：_compute_indicators 给 compute_all_indicators 传 factor_scores（factor_matrix
的 zscore MACD 等值），而 /market/signal 用纯 K 线计算 → 同一标的两个信号分歧
（518880 策略检查 BUY vs /market/signal hold）。
修复：策略检查与 /market/signal 同输入同算法（均不传 factor_scores）。
"""
import pytest

from app.analysis.signal import generate_signal


def _make_hist(closes):
    """构造 K 线记录（60 根，中文列名——与 fetch 真实输出对齐）。"""
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "日期": f"2026-06-{i % 28 + 1:02d}",
            "开盘": c - 0.1, "收盘": c, "最高": c + 0.2, "最低": c - 0.2,
            "成交量": 1_000_000 + i * 1000, "成交额": 1e9 + i * 1e6,
        })
    return rows


@pytest.mark.asyncio
async def test_strategy_check_indicators_same_source_as_market_signal(monkeypatch):
    """策略检查 tech_signal 与 /market/signal 对同一 K 线输入给出同一信号。"""
    import app.services.portfolio_service as ps
    from app.services import market_data_hub as mdh
    from app.analysis.indicators import compute_all_indicators

    closes = [10.0 + 0.05 * i for i in range(60)]  # 温和上行
    hist = _make_hist(closes)

    async def _fake_history(sym, market="A", period="daily"):
        return hist

    monkeypatch.setattr(mdh.market_data_hub, "get_market_history", _fake_history)
    monkeypatch.setattr(mdh.market_data_hub, "get_factor_matrix", lambda: {})

    # /market/signal 路径：纯 K 线
    ind_route = compute_all_indicators(hist)
    sig_route = generate_signal(ind_route)

    # 策略检查路径：_compute_indicators
    inds = await ps._compute_indicators(["510300"])
    sig_check = inds["510300"]["signal"]

    assert sig_check["signal"] == sig_route["signal"], (
        f"策略检查 {sig_check['signal']} ≠ /market/signal {sig_route['signal']}"
    )


@pytest.mark.asyncio
async def test_compute_indicators_does_not_pass_factor_scores(monkeypatch):
    """策略检查不再向 compute_all_indicators 传 factor_scores（zscore 值污染信号）。"""
    import app.services.portfolio_service as ps
    from app.services import market_data_hub as mdh

    hist = _make_hist([10.0 + 0.05 * i for i in range(60)])

    async def _fake_history(sym, market="A", period="daily"):
        return hist

    monkeypatch.setattr(mdh.market_data_hub, "get_market_history", _fake_history)
    monkeypatch.setattr(mdh.market_data_hub, "get_factor_matrix",
                        lambda: {"510300": {"technical.macd.macd": 0.07}})

    calls = {}

    def fake_cai(df, factor_scores=None):
        calls["factor_scores"] = factor_scores
        return {"rsi": 42.5}

    # _compute_indicators 内部 `from ..analysis.indicators import compute_all_indicators`
    monkeypatch.setattr("app.analysis.indicators.compute_all_indicators", fake_cai)
    monkeypatch.setattr("app.analysis.signal.generate_signal", lambda ind: {"signal": "hold", "score": 0})

    await ps._compute_indicators(["510300"])
    assert calls["factor_scores"] is None, (
        "compute_all_indicators 不应收到 factor_scores——zscore 值污染信号是 R6-06 根因"
    )


@pytest.mark.parametrize("j, expected", [
    # round23 F10: KDJ 超买区（J>=80）不得给 BUY 信号
    (85.7, "hold"),   # 159338 实锤：J=85.7 超买 → 不得 BUY
    (98.7, "hold"),   # 159516 实锤：J=98.7 极端超买 + RSI 弱 → 不得 BUY/increase
    (50.0, "buy"),    # 非超买（其它指标偏多）→ 正常 BUY
])
def test_kdj_overbought_not_buy(j, expected):
    """round23 F10: 其它指标偏多时，KDJ 超买区 J>=80 必须把 BUY 降级为 HOLD。

    背景：旧逻辑仅判 J>100，J∈[80,100] 超买区仍判 BUY（159338/159516 实锤误判）。
    """
    indicators = {
        "kdj": {"k": 90.0, "d": 80.0, "j": j},
        "ma5": 11.0, "ma20": 10.0,            # MA5>MA20 多头 (+1)
        "macd": {"dif": 1.0, "dea": 0.0},     # 金叉 (+1)
        "bollinger": {"bandwidth": 3.0},       # 带宽窄 (+0.5)
    }
    sig = generate_signal(indicators)
    assert sig["signal"] == expected, (
        f"KDJ J={j}: 期望 {expected}，实际 {sig['signal']}（score={sig['score']}）"
    )


# ===== folded from test_round20_engine_fixes.py =====
from app.engine.allocation_engine import (
    allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
)
from app.engine.rationale import build_rationale
class TestP1_3OverboughtGuard:
    def test_kdj_j_over_100_no_buy(self):
        """D-B1: KDJ.J=101.67 超买钝化 → 不得给 BUY。"""
        res = generate_signal({
            "rsi": 60,
            "macd": {"dif": 0.5, "dea": 0.3},
            "kdj": {"k": 80, "d": 70, "j": 101.67},
            "ma": {"ma5": 10, "ma20": 9.5},
        })
        assert res["signal"] != "buy", f"J>100 超买钝化不得 BUY，实际 {res}"
        assert any("超买" in r for r in res["reasons"])

    def test_rsi_over_80_no_buy(self):
        """RSI>80 极端超买 → 不得给 BUY。"""
        res = generate_signal({
            "rsi": 85,
            "macd": {"dif": 0.8, "dea": 0.5},
            "kdj": {"k": 60, "d": 55, "j": 70},
            "ma": {"ma5": 10, "ma20": 9.0},
        })
        assert res["signal"] != "buy", f"RSI>80 不得 BUY，实际 {res}"

    def test_oversold_rsi_not_blind_decrease(self):
        """P1-6: RSI<30 超卖 + 技术面偏多 → 不得盲目给 decrease（方向一致才降）。"""
        res = generate_signal({
            "rsi": 25,
            "macd": {"dif": 0.2, "dea": 0.1},   # 多头
            "kdj": {"k": 20, "d": 25, "j": 18},  # 超卖区
            "ma": {"ma5": 10, "ma20": 9.8},     # 多头排列
        })
        assert res["signal"] != "sell", f"超卖+多头不应判 sell，实际 {res}"
