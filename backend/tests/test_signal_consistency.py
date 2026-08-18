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


# ===================================================================
# merged from test_round24_r25_signal.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round24 R25: 信号口径三面一致——综合信号降级门禁 + 策略检查结构化决策。

问题（round24 §12.1 R25 实证）：
- 持仓技术面板（SignalPanel）纯技术，策略检查/标的分析已把因子+基本面纳入展示列+LLM
  叙述，但未聚合进结构化 buy/sell/hold 决策——三面口径不一致；
- calm 市下 generate_signal reason 只 emit MACD/MA（RSI/KDJ 仅极端区），caption 却承诺
  RSI/KDJ（Q1 误导）；
- 若把因子+基本面聚合成综合信号，盘后 valid_rate=0% 会复现 R3 假精确。

修复：
- `composite_signal_with_gate`：0.4技术+0.4估值+0.2动量 聚合，但 valid_rate < 0.6 时
  拒绝合成结论（degraded=true, signal=None），避免假精确；
- strategy-check 每个持仓的 factor_breakdowns 增加 `composite_decision`（结构化决策信号），
  与展示的因子/基本面数据一致；
- 前端 SignalPanel：中性区补 info reason；degraded 综合信号显示降级徽标。
"""

import pytest

from app.analysis.signal import composite_signal_with_gate


class TestCompositeSignalWithGate:
    """R25: 综合信号降级门禁（纯函数）。"""

    def test_healthy_factors_produce_composite(self):
        """valid_rate=0.9 → 正常综合信号（技术弱 + 估值强 → 有结论）。"""
        out = composite_signal_with_gate(
            technical=-0.2, valuation=0.9, momentum=0.3, factor_valid_rate=0.9,
        )
        assert out["degraded"] is False
        assert out["signal"] in ("buy", "hold", "sell")
        assert out["score"] is not None

    def test_degraded_factors_refuse_composite(self):
        """valid_rate=0.0（盘后/熔断）→ 拒绝合成结论：signal=None + degraded（负向：仍报
        buy/hold/sell → FAIL）。"""
        out = composite_signal_with_gate(
            technical=0.8, valuation=0.9, momentum=0.8, factor_valid_rate=0.0,
        )
        assert out["degraded"] is True
        assert out["signal"] is None
        assert "因子数据缺失" in out["reason"]

    def test_below_threshold_refuse_composite(self):
        """valid_rate=0.4 < 0.6 → degraded。"""
        out = composite_signal_with_gate(
            technical=0.5, valuation=0.5, momentum=0.5, factor_valid_rate=0.4,
        )
        assert out["degraded"] is True
        assert out["signal"] is None

    def test_gate_none_defaults_healthy(self):
        """valid_rate=None（未提供）→ 不做降级门禁（保持 composite_signal 原语义）。"""
        out = composite_signal_with_gate(technical=0.6, valuation=0.6, momentum=0.6)
        assert out["degraded"] is False
        assert out["signal"] == "buy"

    def test_edge_threshold_0_6_healthy(self):
        """valid_rate=0.6 恰好等于阈值 → 健康（>= 阈值不降级）。"""
        out = composite_signal_with_gate(
            technical=-0.1, valuation=0.2, momentum=0.1, factor_valid_rate=0.6,
        )
        assert out["degraded"] is False


class TestStrategyCheckCompositeDecision:
    """R25: strategy-check 持仓 factor_breakdowns 带结构化 composite_decision。"""

    def test_breakdown_has_composite_decision(self, monkeypatch):
        """factor_breakdowns[symbol] 含 composite_decision，且与 technical_signal 一致。"""
        import app.services.portfolio_service as ps

        # 构造一个最小 strategy_check 路径：直接调用组装 factor_breakdowns 的辅助逻辑
        # （若拆出纯函数则直测；否则模拟 strategy_check 的 factor_breakdowns 构建）
        from app.services.portfolio_service import _attach_composite_decisions

        fbs = {
            "510300": {
                "factor_scores": {"momentum": 0.5, "valuation": 0.3, "technical": 0.2},
                "technical_signal": {"signal": "hold", "score": 0.0, "reasons": []},
            },
            "518880": {
                "factor_scores": {},
                "technical_signal": {"signal": "hold", "score": 0.0, "reasons": []},
            },
        }
        data_quality = {"filled_count": 14, "total_count": 20}  # 70% ≥ 60% 门禁 → 健康
        _attach_composite_decisions(fbs, data_quality)

        cd = fbs["510300"].get("composite_decision")
        assert cd is not None
        assert "signal" in cd and "score" in cd
        assert cd["degraded"] is False

        cd2 = fbs["518880"].get("composite_decision")
        assert cd2 is not None
        # 因子全空 → filled 少 → 降级门禁可能触发；但必须有字段且诚实
        assert "degraded" in cd2

    def test_low_component_coverage_gates_composite(self):
        """R52: 分项覆盖率 <60% → composite_decision.degraded=true（不报合成结论）。

        round27 R52 把门禁口径从「持仓级填充率」改为「技术/估值/动量分项覆盖率」：
        仅技术信号有值、估值/动量因子键缺失 → 覆盖 1/3 < 0.6 → 诚实降级。
        """
        from app.services.portfolio_service import _attach_composite_decisions

        fbs = {
            "159338": {
                "factor_scores": {"technical.momentum": 0.9},  # 仅技术类因子键
                "technical_signal": {"signal": "buy", "score": 2.0, "reasons": ["MA5>MA20"]},
            },
        }
        _attach_composite_decisions(fbs)
        cd = fbs["159338"]["composite_decision"]
        assert cd["degraded"] is True
        assert cd["signal"] is None
        assert "因子数据缺失" in cd["reason"]


class TestSignalPanelNeutralZoneInfo:
    """R25 前端: 中性区 reason 补 info（SignalPanel spec 覆盖渲染，此处锁纯逻辑映射）。"""

    def test_neutral_reason_supplement(self):
        """calm 市下 reasons 为空 → 补充「RSI 中性」info（Q1 误导消除）。"""
        from app.analysis.signal import neutral_zone_info

        r = neutral_zone_info({"rsi": 52, "kdj": {"k": 50, "d": 49}}, reasons=[])
        assert r is not None
        assert "52" in r
        assert "中性" in r or "无极端" in r

    def test_extreme_reason_no_supplement(self):
        """已有极端 reason（RSI 超买）→ 不补中性 info。"""
        from app.analysis.signal import neutral_zone_info

        r = neutral_zone_info(
            {"rsi": 75, "kdj": {"k": 80, "d": 70}},
            reasons=["RSI=75.0 超买"],
        )
        assert r is None

    def test_missing_indicators_no_supplement(self):
        from app.analysis.signal import neutral_zone_info

        assert neutral_zone_info({}, reasons=[]) is None
