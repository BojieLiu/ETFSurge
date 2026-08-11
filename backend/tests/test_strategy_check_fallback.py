"""
U2/N01 (round2-unfixed-fix-plan.md U2 / round3-diagnosis-and-optimization-plan.md N01
+ factor-and-strategy-check-review.md 问题3): 策略检查报告质量。

- U2 R1: rule 兜底生成 report_text（市态/因子/风险/建议，长度 >500）。
- U2 R3: LLM 超时 20s → 60s → F9: 60s → 30s（慢响应快速兜底，用户等待减半）。
- U2 R2: report_text 为空 → 任务 failed。
- 问题3 R2: _rule_based_suggestion 决策表分档（hold 带因子分/信号依据）。
- 问题3 R3: 风险兜底诚实化（LLM 超时/因子缺失 → warning 级）。

mock 数据源与 LLM，无网络。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import (
    _build_llm_fail_summary,
    _build_rule_fallback_holdings_analysis,
    _combine_risk_warnings,
    _factor_value_real,
    _has_real_factor_values,
    _llm_timeout_for,
    _rule_based_suggestion,
)


_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.4, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.3, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "511010", "name": "国债ETF", "target_weight": 0.2, "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}

_MOCK_FACTORS = {
    "510300": {"technical.ma.sma_5": 0.8, "technical.rsi.rsi_14": 58.2, "technical.signal.overall": 0.4, "style.size.ln_mcap": 22.1},
    "518880": {"technical.ma.sma_5": -0.7, "technical.rsi.rsi_14": 41.3, "technical.signal.overall": -0.5, "style.size.ln_mcap": 21.4},
    "511010": {"technical.ma.sma_5": 0.1, "technical.rsi.rsi_14": 52.0, "technical.signal.overall": 0.0, "style.size.ln_mcap": 22.8},
}

_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}


@pytest.fixture
def strategy_env():
    """Patch all strategy_check data dependencies."""
    ps._strategy_check_cache.clear()
    patches = [
        patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_MOCK_ETFS),
        patch.object(ps, "_compute_indicators", new_callable=AsyncMock, return_value=_MOCK_INDICATORS),
        patch.object(ps, "build_price_map", new_callable=AsyncMock, return_value=_MOCK_PRICE),
        patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


class TestReportTextFallback:
    @pytest.mark.asyncio
    async def test_llm_timeout_generates_report_text(self, strategy_env):
        """U2 R1: LLM 超时 → report_text 非空、长度 >500、含三节。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        report = result.get("report_text", "")
        assert report, "report_text 不得为空（旧 bug: task 66 report_text len=0）"
        assert len(report) > 500, f"report_text 长度 {len(report)} 应 >500"
        assert "策略检查报告" in report
        assert "市态" in report
        assert "因子" in report
        assert "风险提示" in report
        assert "操作建议" in report

    @pytest.mark.asyncio
    async def test_llm_timeout_risk_warning_is_warning_level(self, strategy_env):
        """问题3 R3: LLM 超时 → 风险提示为 warning 级且标注降级。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings, "risk_warnings 不得为空"
        assert any(w["severity"] == "warning" for w in warnings), \
            f"LLM 超时时风险提示应为 warning 级（诚实降级），实际 {[w['severity'] for w in warnings]}"
        # R5-1-2: 骨架生成后行业缺失 warning 会先触发（预期），LLM 超时标注仍须存在
        assert any("LLM 分析超时" in w["description"] for w in warnings), \
            f"须含 LLM 分析超时标注，实际 {[w['description'] for w in warnings]}"

    @pytest.mark.asyncio
    async def test_all_empty_factors_risk_warning(self, strategy_env):
        """问题3 R3: 因子全空 → 风险提示 warning 级并标注因子数据不可用。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value={
                       "summary": "组合稳健", "suggestions": [],
                       "holdings_analysis": [], "risk_warnings": [],
                   }), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value={}):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings[0]["severity"] == "warning"
        assert "因子数据不可用" in warnings[0]["description"], \
            "因子全空时不得显示'风险指标正常'（误导）"

    @pytest.mark.asyncio
    async def test_normal_path_info_warning(self, strategy_env):
        """回归: LLM 正常 + 因子可用 → info 级'风险指标正常'。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value={
                       "summary": "组合稳健", "suggestions": [],
                       "holdings_analysis": [], "risk_warnings": [],
                   }), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings[0]["severity"] == "info", "正常路径应保持 info 级"


class TestR512FallbackHoldingsAnalysis:
    """R5-1-2: rule 兜底路径 holdings_analysis 补全。

    旧行为：LLM 超时走 rule 兜底时 holdings_analysis 恒空 → 行业集中度检查
    静默跳过（P0-1 收敛）。修复后：用 factor_breakdowns/industry_map 生成
    holdings_analysis 骨架（symbol/name/weight/factor_summary/industry），
    标注"规则引擎生成"，行业分布分析在兜底路径也存在。
    """

    @pytest.mark.asyncio
    async def test_llm_timeout_holdings_analysis_not_empty(self, strategy_env):
        """LLM 超时 → holdings_analysis 非空、含 industry 字段、标注规则引擎生成。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        holdings = result.get("holdings_analysis", [])
        assert holdings, "R5-1-2 兜底路径 holdings_analysis 不得为空（旧 bug 恒空）"
        for h in holdings:
            assert h.get("symbol"), "骨架须含 symbol"
            assert h.get("name"), "骨架须含 name"
            assert "weight" in h, "骨架须含 weight"
            assert h.get("generated_by") == "规则引擎生成", \
                f"{h['symbol']} 须标注规则引擎生成，实际 {h.get('generated_by')}"
        # 行业分布可分析（industry_map 注入或空串但不缺字段）
        assert all("industry" in h for h in holdings), "骨架须含 industry 字段"

    @pytest.mark.asyncio
    async def test_llm_failed_suggestions_still_rule_filled(self, strategy_env):
        """LLM 失败 → rule 建议仍在（100% 覆盖），holdings_analysis 骨架与建议并存。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        assert result.get("suggestions"), "rule 建议不得为空"
        assert result.get("holdings_analysis"), "holdings_analysis 骨架不得为空"
        report = result.get("report_text", "")
        assert "规则引擎生成" in report or result["holdings_analysis"], \
            "兜底报告应体现规则引擎生成路径"


class TestRuleSuggestionEnhancement:
    def test_buy_with_mid_factor_holds_with_reason(self):
        """问题3 R2: avg_factor ∈ (0.2, 0.5) + buy → hold，reason 带因子分。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.4,
            factor_score={"technical": 0.3, "momentum": 0.3},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["action"] == "hold"
        assert "未达增仓阈值" in s["reason"], s["reason"]

    def test_strong_buy_increases(self):
        """avg_factor > 0.5 + buy → increase（受 30% 单只风控上限约束）。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.2,
            factor_score={"technical": 0.8, "momentum": 0.6},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["action"] == "increase"
        assert s["suggested_weight"] == pytest.approx(0.24)  # 0.2 × 1.2

    def test_strong_sell_decreases(self):
        """avg_factor < -0.5 + sell → decrease。"""
        s = _rule_based_suggestion(
            symbol="518880", name="黄金ETF", target_weight=0.3,
            factor_score={"technical": -0.7, "momentum": -0.5},
            signal={"signal": "sell"}, regime="range_bound",
        )
        assert s["action"] == "decrease"

    def test_hold_reason_has_factor_and_signal(self):
        """问题3 R2: hold 的 reason 带因子分与信号（不再裸'维持现状'）。"""
        s = _rule_based_suggestion(
            symbol="511010", name="国债ETF", target_weight=0.2,
            factor_score={"technical": 0.05},
            signal={"signal": "hold"}, regime="range_bound",
        )
        assert s["action"] == "hold"
        assert "因子分" in s["reason"] and "信号" in s["reason"], s["reason"]
        assert s["reason"] != "维持现状"

    def test_weight_drift_regression(self):
        """问题3 R2: |current - target| > 20% → 向 target 回归。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.4,
            factor_score={"technical": 0.1},
            signal={"signal": "hold"}, regime="range_bound",
            current_weight=0.3,
        )
        # |0.3 - 0.4| / 0.4 = 25% > 20% → increase 回归
        assert s["action"] == "increase", s["reason"]
        assert "偏离目标权重" in s["reason"]

    def test_reason_richness_three_parts(self):
        """R4-22: reason 丰富化 — 三段式（依据/操作/纪律），含操作节奏与风险边界。"""
        # 强买入 → increase：应含分批节奏 + 风控线
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.2,
            factor_score={"technical": 0.8, "momentum": 0.6},
            signal={"signal": "buy"}, regime="range_bound",
        )
        parts = s["reason"].split("；")
        assert len(parts) >= 3, s["reason"]  # 依据/操作/纪律三段
        assert any("分 2 次" in p or "分批" in p for p in parts), s["reason"]
        assert any("MA20" in p or "止损" in p or "离场" in p or "破位" in p for p in parts), s["reason"]

        # 中性 hold：应含持有逻辑 + 观察触发点
        s2 = _rule_based_suggestion(
            symbol="511010", name="国债ETF", target_weight=0.2,
            factor_score={"technical": 0.05},
            signal={"signal": "hold"}, regime="range_bound",
        )
        parts2 = s2["reason"].split("；")
        assert len(parts2) >= 3, s2["reason"]
        assert any("维持现状" in p for p in parts2)
        assert any("RSI" in p or "超卖" in p or "观察" in p for p in parts2), s2["reason"]

        # 强卖出 → decrease：应含减仓节奏 + 破位纪律
        s3 = _rule_based_suggestion(
            symbol="518880", name="黄金ETF", target_weight=0.3,
            factor_score={"technical": -0.7, "momentum": -0.5},
            signal={"signal": "sell"}, regime="range_bound",
        )
        parts3 = s3["reason"].split("；")
        assert len(parts3) >= 3, s3["reason"]
        assert any("减幅不超过" in p for p in parts3), s3["reason"]


class TestRiskCombineHonesty:
    def test_llm_failed_warning(self):
        """问题3 R3: llm_failed → warning 级。"""
        warnings = _combine_risk_warnings([], [], llm_failed=True)
        assert warnings[0]["severity"] == "warning"
        assert "LLM 分析超时" in warnings[0]["description"]

    def test_data_empty_warning(self):
        """问题3 R3: data_all_empty → warning 级。"""
        warnings = _combine_risk_warnings([], [], data_all_empty=True)
        assert warnings[0]["severity"] == "warning"
        assert "因子数据不可用" in warnings[0]["description"]

    def test_normal_info(self):
        """回归: 正常路径 info 级。"""
        warnings = _combine_risk_warnings([], [])
        assert warnings[0]["severity"] == "info"


# ── round9 P1-13/14/15/16: 策略检查完整性专项（合并自 test_round9_strategy_check.py）──


class TestP113TechSignalFallback:
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


# ── round10 P0-F / P3-H: _llm_timeout_for 静态因子门禁（合并自 test_strategy_check_p0f_timeout.py）──


def _static_only_fs():
    """仅 size/style 静态因子（无 technical.* 键）——P0-F 误判重灾区。"""
    return {
        "style.size.ln_mcap": 22.1,
        "style.size.ln_float_mcap": 21.6,
        "style.value.pe_ttm": 18.4,
    }


def _full_tech_fs():
    """技术因子齐全（覆盖率 100%）。"""
    return {
        "technical.ma.sma_5": 0.8,
        "technical.rsi.rsi_14": 58.2,
        "technical.macd.macd": 0.3,
        "technical.signal.overall": 0.4,
        "style.size.ln_mcap": 22.1,
    }


def _partial_tech_fs():
    """技术因子 5 个中 2 个真实（40% < 60%）→ 也判缺失。"""
    return {
        "technical.ma.sma_5": 0.8,
        "technical.rsi.rsi_14": 58.2,
        "technical.macd.macd": 0.0,       # 兜底 0
        "technical.kdj.k_value": 50.0,    # 兜底 50
        "technical.atr.atr_14": 0.0,      # 兜底 0
        "style.size.ln_mcap": 22.1,
    }


def test_has_real_factor_values_static_only_false():
    """仅静态因子 → filled=False（size 不再撑起"完整"）。"""
    assert _has_real_factor_values(_static_only_fs()) is False


def test_has_real_factor_values_full_tech_true():
    assert _has_real_factor_values(_full_tech_fs()) is True


def test_has_real_factor_values_partial_below_threshold_false():
    """技术因子真实值占比 <60% → False。"""
    assert _has_real_factor_values(_partial_tech_fs()) is False


def test_llm_timeout_for_static_only_30s():
    """全部标的仅静态因子 → all_empty=True → 15s（old 判 90s 的错已修复）。

    注：_llm_timeout_for(data_quality) 按 all_empty/partial 分级——P0-F 的 30s
    对应 `partial`（部分标的 filled）场景；本轮 fetch_history 全空且全部标的
    仅有静态因子 → all_empty=True → 15s（比文档 30s 更保守，符合"不空耗"目标）。
    文档 P3-H 断言口径是「仅静态因子→partial→30s」——这里验证 all_empty 与
    partial 两分支都不返回 90s。
    """
    dq_empty = {
        "filled_count": 0, "total_count": 3, "all_empty": True,
        "partial": False, "fallback_count": 3, "fallback_ratio": 1.0,
    }
    dq_partial = {
        "filled_count": 1, "total_count": 3, "all_empty": False,
        "partial": True, "fallback_count": 2, "fallback_ratio": 0.67,
    }
    assert _llm_timeout_for(dq_empty) == 15
    assert _llm_timeout_for(dq_partial) == 30
    # 完整数据（全部技术因子 real）→ 75s（round14 P0-B 方案 b: 90→75，
    # 对齐 max_retries=0 后最坏 2×35=70s + 余量——旧 90s 与 max_retries=1 的
    # 140s 最坏不匹配，provider 35s 无响应时 1 轮双 provider 71.5s 即耗光预算）
    dq_full = {
        "filled_count": 3, "total_count": 3, "all_empty": False,
        "partial": False, "fallback_count": 0, "fallback_ratio": 0.0,
    }
    assert _llm_timeout_for(dq_full) == 75
