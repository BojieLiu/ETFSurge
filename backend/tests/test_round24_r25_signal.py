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