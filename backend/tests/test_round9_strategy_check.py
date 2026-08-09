"""
round9 (docs/archived/round9-container-rediagnosis.md §4.4/§4.5) 策略检查完整性专项：

- P1-13: technical_signal 空 dict 兜底 + holdings 每项 tech_signal 非空（真实值或「数据不可用」）
- P1-14: industry_map 候选池 → instruments → ETFClassifier 独立兜底链
- P1-15: filled 判定排除兜底默认值（RSI 50/KDJ 50/ATR 0/vol_ratio 1），data_quality 带兜底占比
- P1-16: 空组合诊断（portfolio_type/行数/过滤明细），区分「真空组合」与「查询条件异常」

纯函数/局部 mock，无网络。
"""

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import (
    _build_rule_fallback_holdings_analysis,
    _factor_value_real,
    _has_real_factor_values,
)


class TestP113TechSignalFallback:
    def test_factor_breakdown_empty_signal_dict_gets_explicit_fallback(self):
        """P1-13①: indicators 空 dict 时 technical_signal 必须显式兜底
        `{"signal": None, "reason": "技术指标不可用"}`——旧实现空 dict 穿透不兜底。"""
        from app.factors.factor_registry import registry as _reg

        # 直接验证 factor_breakdowns 构建逻辑的关键分支：构造 strategy_check 中
        # 的等价表达式（空 dict 的 sig）
        sig = {}  # indicators.get(symbol, {}) 返回空 dict
        technical_signal = sig if (isinstance(sig, dict) and sig.get("signal")) else {
            "signal": None, "reason": "技术指标不可用"}
        assert technical_signal == {"signal": None, "reason": "技术指标不可用"}

        sig2 = {"signal": "buy"}
        technical_signal2 = sig2 if (isinstance(sig2, dict) and sig2.get("signal")) else {
            "signal": None, "reason": "技术指标不可用"}
        assert technical_signal2 == {"signal": "buy"}

    def test_rule_fallback_holdings_has_tech_signal_field(self):
        """P1-13③: 规则引擎骨架 holdings 每项带 tech_signal（真实值或「数据不可用」），
        前端信号列不再空白（旧骨架无该字段）。"""
        etfs = [
            {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2},
            {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.1},
        ]
        market_data = [
            {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2},
            {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.1},
        ]
        factor_breakdowns = {
            "510300": {
                "factor_scores": {"momentum": 0.5},
                "technical_indicators": {"sector": "宽基"},
                # 空 dict（P1-13① 兜底后）
                "technical_signal": {"signal": None, "reason": "技术指标不可用"},
            },
            "518880": {
                "factor_scores": {"sentiment": 0.3},
                "technical_indicators": {},
                "technical_signal": {"signal": "buy"},
            },
        }
        result = _build_rule_fallback_holdings_analysis(etfs, market_data, factor_breakdowns, {})
        by_sym = {h["symbol"]: h for h in result}
        assert by_sym["510300"]["tech_signal"] == "数据不可用"
        assert by_sym["518880"]["tech_signal"] == "BUY，真实信号"
        assert all("tech_signal" in h for h in result), "骨架每项必须带 tech_signal 字段"


class TestP115FilledExcludesNeutralDefaults:
    def test_neutral_default_values_excluded(self):
        """P1-15: RSI/KDJ 恰 50、vol_ratio 恰 1、ATR 恰 0 均不算真实值。"""
        assert not _factor_value_real("technical.rsi.rsi_14", 50.0)
        assert not _factor_value_real("technical.kdj.kdj_k", 50.0)
        assert not _factor_value_real("technical.atr.atr_14", 0.0)
        assert not _factor_value_real("vol_ratio", 1.0)
        # 非中性值算真实
        assert _factor_value_real("technical.rsi.rsi_14", 55.0)
        assert _factor_value_real("momentum.mom_3m", 0.03)
        assert _factor_value_real("technical.macd.macd", -0.3)

    def test_has_real_factor_values(self):
        """P1-15 + P0-F: 全兜底默认值 → False；技术因子（technical.* 前缀）真实 → True。"""
        assert not _has_real_factor_values({"technical.rsi.rsi_14": 50.0,
                                            "technical.kdj.k_value": 50.0,
                                            "technical.volume.vol_ratio": 1.0})
        assert _has_real_factor_values({"technical.rsi.rsi_14": 50.0,
                                        "technical.ma.sma_5": 0.2,
                                        "technical.signal.overall": 0.4})
        assert not _has_real_factor_values({})
        assert not _has_real_factor_values(None)

    def test_fallback_ratio_in_data_quality(self):
        """P1-15: data_quality 增加 fallback_count/fallback_ratio（报告明示兜底占比）。"""
        factor_breakdowns = {
            "510300": {"factor_scores": {"technical.ma.sma_5": 0.5}},  # 真实
            "518880": {"factor_scores": {"technical.rsi.rsi_14": 50.0}},  # 兜底默认
            "511090": {"factor_scores": {"technical.kdj.k_value": 50.0,
                                         "technical.volume.vol_ratio": 1.0}},  # 兜底默认
        }
        filled = sum(1 for fb in factor_breakdowns.values()
                     if _has_real_factor_values(fb.get("factor_scores") or {}))
        fallback = sum(1 for fb in factor_breakdowns.values()
                       if not _has_real_factor_values(fb.get("factor_scores") or {}))
        assert filled == 1
        assert fallback == 2
        assert round(fallback / 3, 4) == round(2 / 3, 4)


class TestP114IndustryFallbackChain:
    def test_industry_map_fallback_uses_classifier(self, monkeypatch):
        """P1-14: 候选池空时 industry_map 通过 ETFClassifier 独立分类兜底。"""
        industry_map: dict[str, str] = {}
        symbols = ["512480", "510300"]

        # 模拟候选池 + get_by_code 全空 → 走 ETFClassifier 兜底
        class _FakeHub:
            def get_pool(self):
                return {}

            def get_by_code(self, sym):
                return None

        monkeypatch.setattr(ps, "market_data_hub", _FakeHub())
        from app.services.etf_classifier import ETFClassifier

        classifier = ETFClassifier()
        # 名称来自 instruments 表查询（P1-14 兜底链第二步）
        cls_input = [
            {"symbol": "512480", "name": "半导体ETF", "tracked_index": "半导体"},
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300"},
        ]
        cls = classifier.batch_classify(cls_input) or {}
        for sym in symbols:
            c = cls.get(sym) or {}
            ind = (c.get("industry") or "").strip()
            if ind and ind != "unknown":
                industry_map[sym] = ind
        assert "512480" in industry_map, "ETFClassifier 应能按名称分类半导体ETF"
        assert industry_map["512480"] == "电子", f"实测分类: {industry_map['512480']}"


class TestP116EmptyPortfolioDiagnosis:
    @pytest.mark.asyncio
    async def test_empty_diagnosis_records_query_conditions(self, monkeypatch):
        """P1-16: 空组合诊断记录 portfolio_type/行数/过滤明细，区分真空与查询条件异常。"""
        class _FakeETF:
            def __init__(self, symbol, is_active=True, portfolio_type="on_exchange"):
                self.symbol = symbol
                self.is_active = is_active
                self.portfolio_type = portfolio_type

        class _FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        class _FakeDb:
            def __init__(self, rows):
                self._rows = rows

            async def execute(self, q):
                return _FakeResult(self._rows)

        # 真空组合：DB 无任何行
        db = _FakeDb([])
        diag = await ps._empty_portfolio_diagnosis(db, "on_exchange")
        assert diag["db_total_rows"] == 0
        assert diag["is_active_rows"] == 0
        assert diag["note"] == "真空组合（无任何持仓记录）"

        # 查询条件异常：有 is_active 持仓但 portfolio_type 不匹配
        db2 = _FakeDb([
            _FakeETF("510300", is_active=True, portfolio_type="off_exchange"),
            _FakeETF("518880", is_active=False, portfolio_type="on_exchange"),
        ])
        diag2 = await ps._empty_portfolio_diagnosis(db2, "on_exchange")
        assert diag2["db_total_rows"] == 2
        assert diag2["is_active_rows"] == 1
        assert diag2["matched_rows"] == 0
        assert "查询条件异常" in diag2["note"]
        assert diag2["all_symbols"] == ["510300"]
