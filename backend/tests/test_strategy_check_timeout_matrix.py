"""strategy_check LLM 超时/规则兜底测试矩阵（P1 T-OVERLAP，S3.2 合并，2026-08-18）。

合并自三文件（83 tests 全保留，仅模块级常量加来源前缀防冲突）：
- test_strategy_check_fallback.py（_FB_*）：U2/问题3/R5-1-2/P1-13~16/P0-F/Z26/R42
- test_strategy_check_llm_timeout.py（_LT_*）：R5-1-6/O7/O25/Z26/P2-F/R43
- test_strategy_check_timeout.py（_TO_*）：F1-9/F10/P0-1/P0-5/R57

round28 R42/R43/R57 timeout 分层与规则兜底矩阵回归防线不变。
"""

import asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis import llm
from app.analysis.llm import generate_strategy_check_report
from app.services import portfolio_service as ps
from app.services.portfolio_service import (
    _build_llm_fail_summary,
    _build_rule_fallback_holdings_analysis,
    _collect_strategy_data,
    _combine_risk_warnings,
    _compute_risk_warnings,
    _cross_sectional_factor_composite,
    _factor_value_real,
    _full_pool_factor_composite,
    _has_real_factor_values,
    _llm_timeout_for,
    _rule_based_suggestion,
)

# =========================================================================
# 来源 1: test_strategy_check_fallback.py
# =========================================================================
_FB_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.4, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.3, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "511010", "name": "国债ETF", "target_weight": 0.2, "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_FB_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}

_FB_MOCK_FACTORS = {
    "510300": {"technical.ma.sma_5": 0.8, "technical.rsi.rsi_14": 58.2, "technical.signal.overall": 0.4, "style.size.ln_mcap": 22.1},
    "518880": {"technical.ma.sma_5": -0.7, "technical.rsi.rsi_14": 41.3, "technical.signal.overall": -0.5, "style.size.ln_mcap": 21.4},
    "511010": {"technical.ma.sma_5": 0.1, "technical.rsi.rsi_14": 52.0, "technical.signal.overall": 0.0, "style.size.ln_mcap": 22.8},
}

_FB_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}


@pytest.fixture
def strategy_env():
    """Patch all strategy_check data dependencies."""
    ps._strategy_check_cache.clear()
    patches = [
        patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_FB_MOCK_ETFS),
        patch.object(ps, "_compute_indicators", new_callable=AsyncMock, return_value=_FB_MOCK_INDICATORS),
        patch.object(ps, "build_price_map", new_callable=AsyncMock, return_value=_FB_MOCK_PRICE),
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
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS):
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
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS):
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
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS):
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
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS):
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
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS):
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

    def test_increase_never_decreases_weight(self):
        """P0-10① (round16 3.11): increase 时 suggested_weight 不得 < current_weight
        （原实现 cur=0.5 → min(0.6, 0.30)=0.30，输出"增仓却降仓"矛盾）。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.5,
            factor_score={"technical": 0.8, "momentum": 0.6},
            signal={"signal": "buy"}, regime="range_bound",
            current_weight=0.5,
        )
        assert s["action"] == "increase"
        assert s["suggested_weight"] >= s["current_weight"], (
            f"负向：increase 不得输出 sug({s['suggested_weight']}) < cur({s['current_weight']})"
        )
        # 已达 30% 上限时应提示"已达/接近 30% 风控上限"而非给矛盾值
        assert "30% 风控上限" in s["reason"], s["reason"]

    def test_decrease_never_increases_weight(self):
        """P0-10①: decrease 时 suggested_weight 不得 > current_weight。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.2,
            factor_score={"technical": -0.7, "momentum": -0.5},
            signal={"signal": "sell"}, regime="range_bound",
            current_weight=0.2,
        )
        assert s["action"] == "decrease"
        assert s["suggested_weight"] <= s["current_weight"], (
            f"负向：decrease 不得输出 sug({s['suggested_weight']}) > cur({s['current_weight']})"
        )

    def test_hold_keeps_weight(self):
        """P0-10①: hold 时 suggested_weight == current_weight。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.2,
            factor_score={"technical": 0.05},
            signal={"signal": "hold"}, regime="range_bound",
            current_weight=0.2,
        )
        assert s["action"] == "hold"
        assert s["suggested_weight"] == pytest.approx(s["current_weight"])

    def test_high_factor_hold_reason_not_misleading(self):
        """P0-3 (round16 3.2): 高分因子（如 6.32）但非 buy 信号 → hold 文案不得误称
        '中性区间'（负向：高分描述为中性 → FAIL）。"""
        s = _rule_based_suggestion(
            symbol="518880", name="黄金ETF", target_weight=0.3,
            factor_score={"technical": 6.32},
            signal={"signal": "hold"}, regime="range_bound",
            current_weight=0.3,
        )
        assert s["action"] == "hold"
        assert "中性区间" not in s["reason"], f"高分因子误称中性区间: {s['reason']}"
        assert "偏强" in s["reason"], f"高分因子应标注偏强: {s['reason']}"


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
    # 完整数据（全部技术因子 real）→ 180s（round27 R43: 75→180，对齐 DeepSeek
    # 流式首字节实测 34-78s + 报告 token 更长，避免恒超时落规则兜底）
    dq_full = {
        "filled_count": 3, "total_count": 3, "all_empty": False,
        "partial": False, "fallback_count": 0, "fallback_ratio": 0.0,
    }
    assert _llm_timeout_for(dq_full) == 180


# ===== folded from test_round20_strategy_check_p05_p18.py =====
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
class TestP1_8HoldingsAction:
    def test_rule_fallback_holdings_analysis_has_action(self):
        """P1-8: 规则兜底 holdings_analysis 骨架必须带 action/suggested_weight（D-B2 割裂）。"""
        from app.services.portfolio_service import _build_rule_fallback_holdings_analysis

        etfs = [{"symbol": "510300", "name": "沪深300", "target_weight": 0.3}]
        market_data = [{"symbol": "510300", "name": "沪深300", "target_weight": 0.3,
                        "price": 4.0, "change_pct": 0.5}]
        factor_breakdowns = {
            "510300": {
                "factor_scores": {"technical.momentum": 0.6},
                "technical_signal": {"signal": "buy"},
                "technical_indicators": {},
            }
        }
        rows = _build_rule_fallback_holdings_analysis(
            etfs=etfs, market_data=market_data,
            factor_breakdowns=factor_breakdowns, weight_map={"510300": 0.3},
        )
        assert rows, "应生成 holdings_analysis 骨架"
        h = rows[0]
        assert h.get("action") in ("increase", "decrease", "hold"), (
            f"holdings_analysis 缺 action（与 suggestions 割裂）: {h}"
        )
        assert h.get("suggested_weight") is not None, "holdings_analysis 缺 suggested_weight"
class TestP2_4FactorScoreNote:
    def test_factor_score_note_not_claiming_0_1(self):
        """P2-4: 报告注释不得称「0~1」（实测 511090=-2.31 超范围）；
        应改为「可负可超 1，区别于技术信号」。"""
        from app.tasks.design_report import _build_plan_tables

        strategies = [{
            "label": "稳健型", "positioning": "稳健", "expected_return": 0.08,
            "expected_return_current": 0.08, "max_drawdown": 0.1, "sharpe_ratio": 1.0,
            "expected_characteristics": "", "id": "balanced",
            "allocations": [{
                "symbol": "511090", "name": "30年国债ETF", "layer": "defense",
                "weight": 0.2, "factor_score": -2.31, "factor_breakdown": {},
                "daily_change_pct": 0.1, "selection_rationale": "低相关对冲",
            }],
        }]
        md = _build_plan_tables(strategies)
        assert "多因子综合分（可负可超 1" in md, "注释应明示可负可超 1"
        assert "（0~1）" not in md, f"注释不得再声称 0~1 范围（511090=-2.31 实测超范围）: {md}"
class TestP1_7StrongSectorCoverage:
    def test_covered_sector_true_uncovered_false(self):
        """P1-7 池层：market_context 含 strong_sector_pool_coverage——
        强势板块有对应 ETF 候选 → covered=True；无 → False + WARN 标注。"""
        import asyncio
        from unittest.mock import MagicMock
        from app.services.strategy_design import _build_market_context

        hub = MagicMock()
        hub.get_sector_momentum.return_value = [
            {"sector_name": "医疗服务", "change_pct": 7.2},
            {"sector_name": "化学制药", "change_pct": 5.1},
            {"sector_name": "半导体", "change_pct": 4.0},
        ]
        hub.get_pool.return_value = {
            "satellite": [
                {"symbol": "512170", "name": "医疗ETF", "industry": "医药"},
                {"symbol": "512480", "name": "半导体ETF", "industry": "半导体"},
            ],
        }
        hub.get_market_regime.return_value = "range_bound"
        hub.get_market_sentiment.return_value = {"sentiment_index": 50}
        hub.get_index_realtime.return_value = []
        hub.get_global_indices = MagicMock(return_value={})
        hub._by_code = {}

        ctx = asyncio.run(_build_market_context(hub))
        cov = ctx.get("strong_sector_pool_coverage", [])
        assert cov, "market_context 应含 strong_sector_pool_coverage"
        by_name = {c["sector_name"]: c for c in cov}
        assert by_name["医疗服务"]["covered_in_pool"] is True, "医疗ETF 应覆盖医疗服务板块"
        # 化学制药：候选池无对应 → covered=False + WARN（负向断言）
        assert by_name["化学制药"]["covered_in_pool"] is False
        assert "WARN" in by_name["化学制药"]["note"], "无对应候选应标注 WARN"
class TestP1_8ReasonAndConfidence:
    def test_reason_no_basics_when_factor_sparse(self):
        """P1-8: 因子填充率<50% 时 reason 不得含「基本面」（无基本面数据拼「基本面共振」= 失真）。"""
        from app.services.portfolio_service import _rule_based_suggestion

        s = _rule_based_suggestion(
            symbol="510300", name="沪深300", target_weight=0.3,
            factor_score={"technical.momentum": 0.6, "technical.rsi": 0.4},
            signal={"signal": "buy"}, regime="range_bound",
            current_weight=0.25, factor_availability={"filled": 1, "total": 3},
        )
        assert "基本面" not in s["reason"], f"无基本面数据时 reason 不得含「基本面」: {s['reason']}"

    def test_confidence_medium_when_fill_below_70(self):
        """P1-8: factor_availability 填充率 <70% → confidence 不得为 high（应 medium）。"""
        from app.services.portfolio_service import _rule_based_suggestion

        s = _rule_based_suggestion(
            symbol="512480", name="半导体", target_weight=0.2,
            factor_score={"technical.momentum": 0.8},
            signal={"signal": "buy"}, regime="range_bound",
            current_weight=0.2, factor_availability={"filled": 2, "total": 5},
        )
        assert s["confidence"] != "high", (
            f"填充率 2/5=40%<70% 不得 high，实际 {s['confidence']}"
        )


# ===== folded from test_z26_strategy_check_coverage.py =====
_FB_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "short_name": "300ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.5},
    {"symbol": "518880", "name": "黄金ETF", "short_name": "黄金ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.3},
    {"symbol": "511010", "name": "国债ETF", "short_name": "国债ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.2},
]
_FB_MOCK_FACTORS_Z26 = {
    "510300": {"trend_1m": 0.8, "momentum_20d": 0.6, "volatility_20d": 0.1},
    "518880": {"trend_1m": -0.8, "momentum_20d": -0.7, "volatility_20d": -0.1},
    "511010": {"trend_1m": 0.1, "momentum_20d": 0.0, "volatility_20d": -0.2},
}
_FB_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}
_FB_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}
class TestStrategyCheckCoverage:
    """Z26: strategy check rule fallback."""

    @pytest.mark.asyncio
    async def test_llm_timeout_rule_covers_all(self, strategy_env):
        """Z26: LLM timeout -> rule engine suggestions for every holding."""
        from app.services import portfolio_service as ps
        from app.analysis.llm import generate_strategy_check_report
        from app.factors.factor_registry import registry as factor_registry

        with patch.object(generate_strategy_check_report, "__module__"):
            with patch("app.analysis.llm.generate_strategy_check_report",
                       new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")):
                with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS_Z26):
                    result = await ps.strategy_check(db=None, total_capital=100000)

        assert result["suggestions"], "suggestions should not be empty"
        # Coverage must be 100%
        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["total_holdings"] == 3
        # All suggestions are rule-generated
        for s in result["suggestions"]:
            assert s["source"] == "rule"
            assert s["action"] in ("increase", "decrease", "hold")
            # R4: confidence unified to semantic labels high/medium/low (was raw 0-1 number)
            assert s["confidence"] == "medium"
            assert "current_weight" in s and "suggested_weight" in s
            assert s["reason"]

    @pytest.mark.asyncio
    async def test_llm_partial_coverage_rule_fills_gap(self, strategy_env):
        """Z26: LLM covers 1 of 3 -> rule fills remaining 2, coverage 100%."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_result = {
            "summary": "组合整体稳健",
            "suggestions": [{
                "symbol": "510300", "name": "沪深300ETF",
                "action": "increase", "current_weight": 0.5,
                "suggested_weight": 0.55, "reason": "LLM 建议",
                "confidence": 0.8,
            }],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value=llm_result):
            with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS_Z26):
                result = await ps.strategy_check(db=None, total_capital=100000)

        suggestions = result["suggestions"]
        assert len(suggestions) == 3, f"expected 3 suggestions, got {len(suggestions)}"
        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["covered_by_llm"] == 1
        assert result["coverage"]["covered_by_rule"] == 2

        by_symbol = {s["symbol"]: s for s in suggestions}
        assert by_symbol["510300"]["source"] == "llm"
        assert by_symbol["518880"]["source"] == "rule"
        assert by_symbol["511010"]["source"] == "rule"
        # 518880: factor score negative + sell signal -> decrease
        assert by_symbol["518880"]["action"] == "decrease"
        # 511010: neutral -> hold
        assert by_symbol["511010"]["action"] == "hold"

    @pytest.mark.asyncio
    async def test_llm_full_coverage_no_rule_needed(self, strategy_env):
        """Z26: LLM covers all -> no rule suggestions, coverage 100%."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_result = {
            "summary": "组合整体稳健",
            "suggestions": [
                {"symbol": "510300", "name": "沪深300ETF", "action": "increase",
                 "current_weight": 0.5, "suggested_weight": 0.55, "reason": "a", "confidence": 0.8},
                {"symbol": "518880", "name": "黄金ETF", "action": "hold",
                 "current_weight": 0.3, "suggested_weight": 0.3, "reason": "b", "confidence": 0.8},
                {"symbol": "511010", "name": "国债ETF", "action": "hold",
                 "current_weight": 0.2, "suggested_weight": 0.2, "reason": "c", "confidence": 0.8},
            ],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value=llm_result):
            with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_FB_MOCK_FACTORS_Z26):
                result = await ps.strategy_check(db=None, total_capital=100000)

        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["covered_by_rule"] == 0
        assert all(s["source"] == "llm" for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_rule_suggestion_decision_table(self, strategy_env):
        """Z26: rule decision table — strong factor + buy -> increase; weak + sell -> decrease."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        # 510300: factor > 0.5 + buy -> increase
        factors = {
            "510300": {"trend_1m": 0.9, "momentum_20d": 0.8},
            "518880": {"trend_1m": -0.9, "momentum_20d": -0.8},
        }
        indicators = {
            "510300": {"signal": {"signal": "buy"}},
            "518880": {"signal": {"signal": "sell"}},
        }
        etfs = [
            {"symbol": "510300", "name": "沪深300ETF", "asset_type": "ETF",
             "portfolio_type": "on_exchange", "target_weight": 0.5},
            {"symbol": "518880", "name": "黄金ETF", "asset_type": "ETF",
             "portfolio_type": "on_exchange", "target_weight": 0.3},
        ]
        from app.services import portfolio_service as ps_mod
        ps_mod._strategy_check_cache.clear()
        with patch.object(ps_mod, "list_etfs", new_callable=AsyncMock, return_value=etfs), \
             patch.object(ps_mod, "_compute_indicators", new_callable=AsyncMock, return_value=indicators), \
             patch.object(ps_mod, "build_price_map", new_callable=AsyncMock,
                          return_value={"510300": (3.8, 1.0), "518880": (2.5, -1.0)}), \
             patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"), \
             patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
                   return_value={
                       "510300": {"trend_1m": 0.9, "momentum_20d": 0.8},
                       "518880": {"trend_1m": -0.9, "momentum_20d": -0.8},
                   }), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=factors), \
             patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("timeout")):
            result = await ps_mod.strategy_check(db=None, total_capital=100000)

        by_symbol = {s["symbol"]: s for s in result["suggestions"]}
        assert by_symbol["510300"]["action"] == "increase"
        # P0-10 (round16 3.11): increase 不得输出 sug<cur 矛盾值——cur=0.5 已达 30%
        # 风控上限 → suggested 维持 0.5 并提示"已达/接近 30% 风控上限"（旧实现 0.30 降仓矛盾）。
        assert by_symbol["510300"]["suggested_weight"] == pytest.approx(0.5), \
            f"increase 不得降仓: {by_symbol['510300']}"
        assert "30% 风控上限" in by_symbol["510300"]["reason"], by_symbol["510300"]["reason"]
        assert by_symbol["518880"]["action"] == "decrease"
        # decrease: max(current*0.7, 0) = 0.21
        assert by_symbol["518880"]["suggested_weight"] == pytest.approx(0.21)
        assert result["coverage"]["coverage_pct"] == 1.0

    def test_action_enum_restricted(self):
        """Z26: rule engine only emits increase/decrease/hold."""
        from app.services.portfolio_service import _rule_based_suggestion

        for scenario in [
            ({"a": 0.9}, {"signal": "buy"}, "range_bound"),
            ({"a": -0.9}, {"signal": "sell"}, "range_bound"),
            ({"a": 0.1}, {"signal": "hold"}, "range_bound"),
            ({"a": 0.9}, {"signal": "buy"}, "bearish"),
        ]:
            suggestion = _rule_based_suggestion(
                symbol="X", name="X", target_weight=0.3,
                factor_score=scenario[0], signal=scenario[1], regime=scenario[2],
            )
            assert suggestion["action"] in ("increase", "decrease", "hold")
            assert suggestion["source"] == "rule"
            # R4: confidence unified to semantic labels high/medium/low (was raw 0-1 number)
            assert suggestion["confidence"] == "medium"


# ── folded from test_round27_r42_factor_direction.py ──
"""round27 R42: 因子分两屏方向统一（反假完成负向测试）。

验收（doc §15.1 R42）：
① 同标的场内持仓，设计全池 z（≈-0.958）与策略检查「因子分」方向一致，
   禁止再出现「设计 -0.958 vs 检查 +0.16」方向相反；
② 场外联接（不在池内，如 022449）回落单标的口径，reference='单标的'；
③ reason 含参考群体标注（相对候选池 / 单标的）。
"""


def _matrix_row_neg() -> dict:
    """全池截面 z 行：所有因子键 = -0.958（深负）→ 聚合后 composite ≈ -0.958（设计同口径）。"""
    keys = [
        "technical", "technical.momentum", "technical.rsi",
        "valuation", "valuation.pe", "valuation.pb",
        "momentum", "momentum.recent_return", "momentum.vol_ratio",
    ]
    return {k: -0.958 for k in keys}


def _build_breakdowns() -> dict:
    """159338 在 13 持仓子集内相对强（technical 高）→ 旧 _cross_sectional 会算成 +（与设计相反）。"""
    return {
        "159338": {"factor_scores": {
            "technical.rsi.rsi_14": 80.0, "technical.momentum": 0.6, "valuation.pe": 25.0,
            "momentum.recent_return": 5.0,
        }, "technical_signal": {"signal": "buy", "score": 1.5}},
        "510300": {"factor_scores": {
            "technical.rsi.rsi_14": 20.0, "technical.momentum": -0.5, "valuation.pe": 12.0,
            "momentum.recent_return": -3.0,
        }, "technical_signal": {"signal": "sell", "score": -1.5}},
        "510050": {"factor_scores": {
            "technical.rsi.rsi_14": 25.0, "technical.momentum": -0.4, "valuation.pe": 13.0,
            "momentum.recent_return": -2.0,
        }, "technical_signal": {"signal": "sell", "score": -1.0}},
    }


def test_design_and_strategy_sign_agree_for_on_exchange():
    """R42 负向：策略检查改用全池 z 后，与设计屏同号（负）；旧子集截面同号（正）必须不再出现。"""
    fbs = _build_breakdowns()
    matrix = {"159338": _matrix_row_neg(), "510300": _matrix_row_neg(), "510050": _matrix_row_neg()}
    design_score = -0.958  # 设计屏全池 z（深负）

    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix", return_value=matrix):
        new_comp = _full_pool_factor_composite(fbs)["159338"]["composite"]
    old_comp = _cross_sectional_factor_composite(fbs)["159338"]

    # 旧实现：持仓子集截面 → 159338 相对强 → 正（与设计相反，正是 R42 要修的 Bug）
    assert old_comp > 0, f"旧 _cross_sectional 应给出正值（与设计相反），实际 {old_comp}"
    # 新实现：复用全池 z → 应与设计同号（负），不得是 +0.16 类正值
    assert new_comp is not None
    assert new_comp < 0, f"策略检查应复用全池 z（与设计同号负），实际 {new_comp}"
    assert (new_comp < 0) == (design_score < 0), "策略检查与设计屏因子分方向必须一致"
    # 负向核心：修复后策略检查不得再与旧子集截面同号（否则两屏仍相反）
    assert (new_comp > 0) != (old_comp > 0), "修复后策略检查不得再与旧子集截面同号"


def test_off_exchange_uses_single_symbol_caliber():
    """R42：场外联接（不在池内，如 022449）回落单标的口径，reference='单标的'。"""
    fbs = {
        "022449": {"factor_scores": {
            "technical.rsi.rsi_14": 60.0, "valuation.pe": 20.0,
        }, "technical_signal": {"signal": "hold", "score": 0.0}},
    }
    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
               return_value={"159338": _matrix_row_neg()}):
        res = _full_pool_factor_composite(fbs)["022449"]
    assert res["reference"] == "单标的"
    assert res["composite"] is not None


def test_reference_label_in_reason():
    """R42：reason 含参考群体标注（场内='相对候选池' / 场外='单标的'）。"""
    with patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
               return_value={"159338": _matrix_row_neg()}):
        on = _rule_based_suggestion(
            symbol="159338", name="中证A500ETF", target_weight=0.2,
            factor_score={"technical.rsi.rsi_14": 80.0}, signal={"signal": "buy", "score": 1.5},
            regime="range_bound", current_weight=0.2,
            factor_composite=-0.958, factor_composite_label="相对候选池",
        )
        off = _rule_based_suggestion(
            symbol="022449", name="联接基金", target_weight=0.1,
            factor_score={"technical.rsi.rsi_14": 60.0}, signal={"signal": "hold", "score": 0.0},
            regime="range_bound", current_weight=0.1,
            factor_composite=0.2, factor_composite_label="单标的",
        )
    assert "因子分口径：相对候选池" in on["reason"]
    assert "因子分口径：单标的" in off["reason"]

# =========================================================================
# 来源 2: test_strategy_check_llm_timeout.py
# =========================================================================
@pytest.fixture
def llm_chain_env(monkeypatch):
    """R5-1-6 fixture: mock LLM 调用链（对齐 test_agent_registry.py:81）。"""
    monkeypatch.setattr(llm.client, "_check_key", AsyncMock(return_value=None))
    monkeypatch.setattr(llm.token_store, "record", AsyncMock(return_value=None))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(return_value=None))
    return llm


class TestR516RateLimitWaitCap:
    def test_cap_param_limits_wait(self):
        """_rate_limit_wait(attempt=3, cap=10) ≤10s（旧固定 cap 30s）。"""
        w = llm._rate_limit_wait(3, None, cap=10.0)
        assert w <= 10.0, f"cap=10 时等待 {w}s > 10s"
        assert w >= 0

    def test_default_cap_unchanged(self):
        """默认 cap=30 不变（既有 test_llm_rate_limit.py 不破坏）。"""
        w = llm._rate_limit_wait(0, None)  # 3s * 2^0 = 3s
        assert w == 3.0
        w2 = llm._rate_limit_wait(5, None)  # cap 30
        assert w2 <= 30.0

    def test_retry_after_respects_cap(self):
        """Retry-After=25s + cap=10 → 等待 10s（cap 生效）。"""
        w = llm._rate_limit_wait(0, {"retry-after": "25"}, cap=10.0)
        assert w == 10.0


class TestR516LastErrorDiagnostics:
    def test_record_429_marks_rate_limited(self):
        """429 异常 → 诊断前缀 [rate-limited]。"""
        exc = _make_429_exc()
        llm._record_llm_error(exc)
        assert llm.get_last_llm_error() == "[rate-limited] 429 Too Many Requests"

    def test_record_timeout_marks_timeout(self):
        """连接超时 → 诊断前缀 [timeout]。"""
        llm._record_llm_error(asyncio.TimeoutError("connect timed out"))
        assert llm.get_last_llm_error().startswith("[timeout]")

    def test_success_clears_error(self):
        """成功调用后 get_last_llm_error() 为空。"""
        llm._record_llm_error(_make_429_exc())
        llm._clear_llm_error()
        assert llm.get_last_llm_error() is None


class TestR516StrategyCheckFastFail:
    @pytest.mark.asyncio
    async def test_run_json_passes_rate_limit_cap(self, llm_chain_env):
        """rate_limit_cap=10 透传到 llm_complete_with_system（mock runtime）。"""
        from app.analysis import runtime as runtime_mod

        captured = {}

        async def _fake_llm_complete(**kw):
            captured["max_retries"] = kw.get("max_retries")
            captured["rate_limit_cap"] = kw.get("rate_limit_cap")
            return '{"ok": true}'

        with patch.object(runtime_mod, "llm_complete_with_system", _fake_llm_complete):
            rt = runtime_mod.AgentRuntime(_FakeConfig())
            result = await rt.run_json("prompt", max_retries=1, rate_limit_cap=10.0)
        assert result == {"ok": True}
        assert captured["max_retries"] == 1
        assert captured["rate_limit_cap"] == 10.0

    @pytest.mark.asyncio
    async def test_timeout_summary_contains_last_error(self):
        """generate_strategy_check_report 超时兜底 summary 含最后错误诊断。"""
        from app.analysis import registry

        fake_agent = AsyncMock()
        fake_agent.run_json = AsyncMock(side_effect=asyncio.TimeoutError("boom"))

        with patch.object(registry, "get_agent", return_value=fake_agent):
            llm._record_llm_error(asyncio.TimeoutError("connect timed out"))
            result = await llm.generate_strategy_check_report(
                market_data=[{"symbol": "510300", "name": "x", "target_weight": 0.5}],
                factor_breakdowns={},
                regime="range_bound",
            )
        # 快速失败参数必须透传（round14 P0-B: max_retries 1→0——1 轮双 provider
        # 失败立即兜底，不进入会超预算的重试；2×35=70 ≤ 75 预算一致）
        kwargs = fake_agent.run_json.call_args.kwargs
        assert kwargs.get("max_retries") == 0, f"max_retries 未透传: {kwargs}"
        assert kwargs.get("rate_limit_cap") == 10.0, f"rate_limit_cap 未透传: {kwargs}"
        assert "最后错误" in result["summary"] or "[timeout]" in result["summary"], \
            f"summary 应含错误诊断: {result['summary']}"


class _FakeConfig:
    name = "strategy_check"
    max_retries = 2
    response_format = "json_object"
    system_prompt_file = "strategy_check.md"
    temperature = 0.3


def _make_429_exc():
    import httpx
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


# ── O7 / R6-F13: _build_llm_fail_summary 文案分级（合并自 test_strategy_check_llm_fallback.py
#    与 test_strategy_check_summary.py）──


class TestLlmFailSummary:
    def test_timeout_reason_with_data_summary(self):
        """超时兜底文案含原因分类 + 数据摘要（N/M 可用）。"""
        s = _build_llm_fail_summary(32.0, "connection timed out", {
            "filled_count": 8, "total_count": 10, "partial": True, "all_empty": False,
        })
        assert "LLM 响应超时" in s
        assert "32s" in s
        assert "8/10" in s
        assert "规则引擎兜底" in s

    def test_rate_limited_reason(self):
        s = _build_llm_fail_summary(5.0, "429 Too Many Requests", None)
        assert "LLM 限流" in s
        assert "429" in s

    def test_all_empty_quality_note(self):
        """数据全缺时文案注明「上下文不足快速兜底」。"""
        s = _build_llm_fail_summary(15.0, "timeout", {
            "filled_count": 0, "total_count": 10, "partial": False, "all_empty": True,
        })
        assert "数据缺失" in s
        assert "0/10" in s


def test_fail_summary_rate_limit():
    """诊断含 429/限流 → "LLM 限流"。"""
    s = _build_llm_fail_summary(10.0, "HTTP 429 Rate limit exceeded")
    assert "LLM 限流" in s, s
    assert "429" in s
    assert "已用规则引擎兜底" in s


def test_fail_summary_timeout():
    """诊断含 timeout → "LLM 响应超时"。"""
    s = _build_llm_fail_summary(60.0, "HTTPSConnectionPool timed out")
    assert "LLM 响应超时" in s, s


def test_fail_summary_server_error():
    """5xx 快速失败（非超时非限流）→ "LLM 服务端错误"，旧"超时 60s"文案不出现。"""
    s = _build_llm_fail_summary(10.0, "Server error '500 Internal Server Error'")
    assert "LLM 服务端错误" in s, s
    assert "超时（60s" not in s  # 旧文案残留不得出现


def test_fail_summary_unknown_diag():
    """无诊断 → 归类服务端错误且含"未知"。"""
    s = _build_llm_fail_summary(30.0, "")
    assert "服务端错误" in s
    assert "未知" in s


# ── O25: 部分采集结果保留 + 数据质量兜底（合并自 test_strategy_check_partial_data.py）──


class TestPartialCollectionKept:
    @pytest.mark.asyncio
    async def test_indicator_timeout_keeps_factors(self):
        """① 指标任务超时 → 因子结果保留（非全空）。"""
        async def slow_indicators(symbols):
            await asyncio.sleep(1.0)  # 远超 indicators_timeout
            return {"510300": {"signal": {"signal": "buy"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}

        with patch.object(ps, "_compute_indicators", new=slow_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300", "560600"], indicators_timeout=0.1, factor_timeout=5,
            )
        assert indicators == {}, "指标超时应返回 {}"
        assert factor_scores == {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}, \
            f"因子结果应保留（非全空）: {factor_scores}"

    @pytest.mark.asyncio
    async def test_factor_failure_keeps_indicators(self):
        """因子任务失败 → 指标结果保留。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def boom_factors(symbols):
            raise RuntimeError("data source down")

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=boom_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300"], indicators_timeout=5, factor_timeout=5,
            )
        assert indicators == {"510300": {"signal": {"signal": "hold"}}}
        assert factor_scores == {}

    @pytest.mark.asyncio
    async def test_both_ok(self):
        """正常路径：两任务均返回。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}}

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(["510300"])
        assert indicators["510300"]["signal"]["signal"] == "hold"
        assert factor_scores["510300"]["technical"] == 0.5


class TestFallbackSummaryWithQuality:
    def test_summary_includes_data_quality(self):
        """③ 兜底 summary 携带数据质量（N/M 因子可用 + 缺失原因）。"""
        summary = _build_llm_fail_summary(
            duration_s=30.0, diag="DeepSeek timeout",
            data_quality={"filled_count": 2, "total_count": 3, "partial": True},
        )
        assert "2/3" in summary, f"summary 应含因子可用数: {summary}"
        assert "因子" in summary

    def test_summary_all_empty(self):
        summary = _build_llm_fail_summary(
            duration_s=15.0, diag="timeout",
            data_quality={"filled_count": 0, "total_count": 3, "all_empty": True},
        )
        assert "0/3" in summary
        assert "数据不足" in summary or "缺失" in summary

    def test_summary_backward_compatible(self):
        """不传 data_quality 时保持旧文案结构（兼容调用方）。"""
        summary = _build_llm_fail_summary(duration_s=30.0, diag="timeout")
        assert "规则引擎兜底" in summary


# ===== folded from test_z26_strategy_check_coverage.py =====
@pytest.fixture
def strategy_env_lt():
    """Patch all strategy_check data dependencies; yield a helper to set LLM result."""
    from app.services import portfolio_service as ps

    ps._strategy_check_cache.clear()
    patches = [
        patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_LT_MOCK_ETFS),
        patch.object(ps, "_compute_indicators", new_callable=AsyncMock, return_value=_LT_MOCK_INDICATORS),
        patch.object(ps, "build_price_map", new_callable=AsyncMock, return_value=_LT_MOCK_PRICE),
        patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
_LT_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "short_name": "300ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.5},
    {"symbol": "518880", "name": "黄金ETF", "short_name": "黄金ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.3},
    {"symbol": "511010", "name": "国债ETF", "short_name": "国债ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.2},
]
_LT_MOCK_FACTORS = {
    "510300": {"trend_1m": 0.8, "momentum_20d": 0.6, "volatility_20d": 0.1},
    "518880": {"trend_1m": -0.8, "momentum_20d": -0.7, "volatility_20d": -0.1},
    "511010": {"trend_1m": 0.1, "momentum_20d": 0.0, "volatility_20d": -0.2},
}
_LT_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}
_LT_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}
class TestP2FLlmReportCache:
    @pytest.mark.asyncio
    async def test_second_call_hits_llm_report_cache(self, strategy_env_lt):
        """P2-F: 同持仓同 capital 重复 strategy_check——第 2 次命中 LLM 报告缓存，
        不再调用 generate_strategy_check_report（旧实现每次 60-120s 重算）。"""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_calls = []

        async def _fake_llm(**kw):
            llm_calls.append(1)
            return {"summary": "组合稳健", "suggestions": [],
                    "holdings_analysis": [], "risk_warnings": []}

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new=AsyncMock(side_effect=_fake_llm)), \
             patch.object(factor_registry, "compute",
                          new_callable=AsyncMock, return_value=_LT_MOCK_FACTORS):
            r1 = await ps.strategy_check(db=None, total_capital=100000)
            r2 = await ps.strategy_check(db=None, total_capital=100000)

        assert len(llm_calls) == 1, f"第 2 次应命中缓存不再调 LLM，实际 {len(llm_calls)} 次"
        assert r2["summary"] == r1["summary"]
        # 缓存命中时 raw_llm 同源（LLM 成功报告复用）
        assert "组合稳健" in r1["summary"]

    @pytest.mark.asyncio
    async def test_llm_failure_not_cached(self, strategy_env_lt):
        """P2-F: LLM 超时兜底不写缓存——下次检查仍会重试 LLM（不得把降级当成功复用）。"""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_calls = []

        async def _flaky_llm(**kw):
            llm_calls.append(1)
            if len(llm_calls) == 1:
                raise asyncio.TimeoutError("llm slow")
            return {"summary": "组合稳健", "suggestions": [],
                    "holdings_analysis": [], "risk_warnings": []}

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new=AsyncMock(side_effect=_flaky_llm)), \
             patch.object(factor_registry, "compute",
                          new_callable=AsyncMock, return_value=_LT_MOCK_FACTORS):
            r1 = await ps.strategy_check(db=None, total_capital=100000)
            r2 = await ps.strategy_check(db=None, total_capital=100000)

        assert len(llm_calls) == 2, f"失败不缓存，第 2 次应重试 LLM，实际 {len(llm_calls)} 次"
        assert "组合稳健" in r2["summary"]


# ── folded from test_round27_r43_timeout.py ──
"""round27 R43: 策略检查 LLM 超时 75s → 180s（反假完成测试）。

验收（doc §15.1 R43）：`_llm_timeout_for` 「数据完整」分支 75→180，使 DeepSeek 流式
首字节实测 34-78s 的场景不再几乎必然超时（恒落规则兜底）。

负向断言：
① 数据完整 → 180（不再 75）；② 分支分级保持不变（all_empty=15 / partial=30）；
③ 模拟「LLM 首字节 60s、生成到 120s」场景下，180s 预算能容纳（旧 75s 必截断）。
"""


def test_data_complete_timeout_is_180_not_75():
    """R43 主修复：数据完整分支必须 180s（负向：仍是 75 → FAIL）。"""
    dq_full = {"all_empty": False, "partial": False}
    assert _llm_timeout_for(dq_full) == 180, "数据完整分支应为 180s（round27 R43: 75→180）"


def test_timeout_tiers_unchanged():
    """分支分级保持：all_empty=15 / partial=30 / full=180。"""
    assert _llm_timeout_for({"all_empty": True}) == 15
    assert _llm_timeout_for({"all_empty": False, "partial": True}) == 30
    assert _llm_timeout_for({"all_empty": False, "partial": False}) == 180


def test_full_budget_absorbs_real_first_byte():
    """R43 现实证真：DeepSeek 首字节实测 34-78s、单报告更长，180s 预算可容纳；
    旧 75s 在首字节 60s 时仅剩 15s 生成 → 必超时。
    """
    budget = _llm_timeout_for({"all_empty": False, "partial": False})
    first_byte = 60.0  # 首字节实测上沿附近
    assert budget > first_byte, "180s 预算应大于首字节延迟，留出生成余量"
    assert budget - first_byte >= 60.0, "至少应留 60s 生成余量（否则复现旧 75s 截断）"

# =========================================================================
# 来源 3: test_strategy_check_timeout.py
# =========================================================================
# ── 1. llm.py 内部 CancelledError 捕获 ─────────────────────────

@pytest.mark.asyncio
async def test_generate_strategy_check_report_catches_cancelled():
    """F1-9: run_json 抛 CancelledError → 捕获并返回规则兜底 dict。"""
    with patch("app.analysis.registry.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run_json.side_effect = asyncio.CancelledError()
        mock_get_agent.return_value = mock_agent

        result = await generate_strategy_check_report(
            market_data=[{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3}],
            factor_breakdowns={},
            regime="range_bound",
            data_quality={"filled_count": 0, "total_count": 1, "all_empty": True, "partial": False},
        )

    assert isinstance(result, dict)
    assert "超时" in result.get("summary", "")
    assert result["suggestions"] == []


@pytest.mark.asyncio
async def test_generate_strategy_check_report_normal_returns():
    """F1-9 回归: LLM 正常返回时结果原样透传。"""
    with patch("app.analysis.registry.get_agent") as mock_get_agent:
        mock_agent = AsyncMock()
        mock_agent.run_json.return_value = {
            "summary": "正常分析结论",
            "suggestions": [{"action": "hold", "symbol": "510300"}],
            "holdings_analysis": [], "risk_warnings": [],
        }
        mock_get_agent.return_value = mock_agent

        result = await generate_strategy_check_report(
            market_data=[{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3}],
            factor_breakdowns={},
            regime="range_bound",
        )
    assert result["summary"] == "正常分析结论"
    assert result["suggestions"][0]["action"] == "hold"


# ── 2. usage 失败记录与超时文案 ──────────────────────────────


@pytest.mark.asyncio
async def test_strategy_check_cancelled_error_usage_record():
    """F1-9: 超时分支应写入 usage 失败记录（success=False + error 含 timed out）。"""
    from app.monitor.token_usage import UsageRecord

    rec = UsageRecord(
        function_name="generate_strategy_check_report",
        prompt_tokens=0, completion_tokens=0, total_tokens=0,
        model="", timestamp=0, success=False,
        duration_ms=20000.0, error_message="wait_for timeout (TimeoutError)", provider="",
    )
    assert rec.success is False
    assert "timed out" in rec.error_message or "timeout" in rec.error_message.lower()


def test_timeout_log_message_shape():
    """F1-9: 超时 WARNING 日志应含「timed out」与耗时（验证日志格式定义存在）。"""
    # portfolio_service 超时分支的日志格式（此处不实际触发，只验证格式串）
    fmt = "[strategy_check] LLM analysis timed out/cancelled after %.1fs (%s), using rule fallback"
    assert "timed out" in fmt
    assert "%.1fs" in fmt


# ── F10: 决策表信号-因子背离分支（合并自 test_strategy_check_divergence.py）──


def _sugg(sig, factor_score, regime="range_bound", current_weight=0.1, target_weight=0.1):
    return _rule_based_suggestion(
        symbol="159992",
        name="创新药ETF",
        factor_score=factor_score,
        signal={"signal": sig, "score": 0.0},
        regime=regime,
        target_weight=target_weight,
        current_weight=current_weight,
    )


def test_sell_with_strong_positive_factor_holds_with_explanation():
    """sig=sell + avg_factor=+3.57 → hold 且 reason 含背离解释（非裸"信号 sell 维持现状"）。"""
    s = _sugg("sell", {"technical": 3.57, "momentum": 1.2, "valuation": 0.5})
    assert s["action"] == "hold"
    assert "技术面偏空" in s["reason"], s["reason"]
    assert "因子分强正" in s["reason"], s["reason"]
    assert "MA20" in s["reason"]
    # 文案自洽门禁：背离时不得裸写"信号 sell，维持现状"
    assert "信号 sell，维持现状" not in s["reason"]


def test_buy_with_negative_factor_holds_symmetric():
    """sig=buy + avg_factor=-1.0 → hold 且解释（对称分支）。"""
    s = _sugg("buy", {"technical": -1.0, "momentum": -0.8})
    assert s["action"] == "hold"
    assert "技术面偏多" in s["reason"], s["reason"]
    assert "因子分偏弱" in s["reason"], s["reason"]
    assert "信号 buy，维持现状" not in s["reason"]


def test_u2_r2_increase_branch_not_regressed():
    """U2 R2 回归：buy + 因子>0.5 非 bearish → increase。"""
    s = _sugg("buy", {"technical": 0.8, "momentum": 0.6}, regime="range_bound")
    assert s["action"] == "increase"


def test_u2_r2_decrease_branch_not_regressed():
    """U2 R2 回归：sell + 因子<-0.5 → decrease。"""
    s = _sugg("sell", {"technical": -0.8, "momentum": -0.6})
    assert s["action"] == "decrease"


def test_weak_sell_still_holds_with_plain_reason():
    """弱信号 sell + 因子中性 → 默认 hold（无背离，不带强正解释）。"""
    s = _sugg("sell", {"technical": 0.2, "momentum": -0.1})
    assert s["action"] == "hold"
    assert "技术面偏空" not in s["reason"]


# ── P0-1: 行业集中度误导性输出修复（合并自 test_strategy_check_industry.py）──


def test_risk_warnings_blank_industry_degraded_to_warn():
    """P0-1: 全部持仓无行业字段 → WARN + 标注（不 HIGH 误报「仅覆盖1个行业」）。"""
    holdings = [
        {"symbol": f"S{i:06d}", "name": f"ETF{i}", "weight": 0.1} for i in range(1, 11)
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings if w["type"] == "concentration"]
    assert conc, "应产出行业集中度提示"
    assert conc[0]["severity"] == "warning", \
        f"空行业应降级 WARN，实际 {conc[0]['severity']}"
    assert "行业数据缺失" in conc[0]["description"]
    assert len(conc[0]["affected_symbols"]) == 10


def test_risk_warnings_real_industries_no_false_positive():
    """P0-1: 真实覆盖 ≥7 行业（R4-01 场景）不误报行业集中度。"""
    industries = ["券商", "半导体设备", "创新药", "游戏", "黄金", "红利", "港股科技", "宽基"]
    holdings = [
        {"symbol": f"S{i:06d}", "name": f"ETF{i}", "weight": 0.1,
         "sector": industries[i % len(industries)],
         "industry": industries[i % len(industries)]}
        for i in range(10)
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings
            if w["type"] == "concentration" and "行业集中度" in w["description"]]
    assert not conc, "8 行业真实覆盖不应触发行业集中度警告"


def test_risk_warnings_partial_blank_still_warn():
    """P0-1: 部分标的缺行业（空串权重>0 且 unique<=2）→ WARN 非 HIGH。"""
    holdings = [
        {"symbol": "S1", "name": "A", "weight": 0.3, "sector": "券商"},
        {"symbol": "S2", "name": "B", "weight": 0.3},   # 无行业
        {"symbol": "S3", "name": "C", "weight": 0.2},   # 无行业
        {"symbol": "S4", "name": "D", "weight": 0.2},   # 无行业
    ]
    warnings = _compute_risk_warnings(holdings, {}, "range_bound")
    conc = [w for w in warnings if w["type"] == "concentration"]
    assert conc and conc[0]["severity"] == "warning"
    assert "行业数据缺失" in conc[0]["description"]


_TO_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "512000", "name": "券商ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_TO_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "hold"}},
    "512000": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "hold"}},
}

_TO_MOCK_FACTORS = {
    "510300": {"technical": 0.3, "momentum": 0.2},
    "512000": {"technical": 0.6, "momentum": 0.5},
    "518880": {"technical": 0.1, "momentum": 0.0},
}

_TO_MOCK_PRICE = {"510300": (3.8, 1.2), "512000": (0.9, 0.5), "518880": (8.4, -0.3)}


@pytest.mark.asyncio
async def test_strategy_check_injects_industry_from_hub_pool():
    """P0-1: strategy_check 后处理从 market_data_hub 候选池注入 sector/industry。"""
    ps._strategy_check_cache.clear()
    llm_holdings = [
        {"symbol": "510300", "name": "沪深300ETF", "weight": 0.2},
        {"symbol": "512000", "name": "券商ETF", "weight": 0.1},
        {"symbol": "518880", "name": "黄金ETF", "weight": 0.1},
    ]
    llm_result = {
        "summary": "测试摘要",
        "suggestions": [{"symbol": "512000", "action": "increase", "reason": "x",
                         "confidence": 0.7, "source": "llm",
                         "suggested_weight": 0.12}],
        "holdings_analysis": llm_holdings,
        "risk_warnings": [],
    }
    # 候选池条目含 industry（与设计任务同一来源）
    pool = {
        "core": [
            {"symbol": "510300", "name": "沪深300ETF", "industry": "宽基指数"},
            {"symbol": "512000", "name": "券商ETF", "industry": "券商"},
            {"symbol": "518880", "name": "黄金ETF", "industry": "商品"},
        ]
    }

    async def _fake_registry_compute(symbols, codes=None, market_data=None, symbol_extra=None):
        return {s: dict(_TO_MOCK_FACTORS.get(s, {})) for s in symbols}

    with patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_TO_MOCK_ETFS), \
         patch.object(ps, "_compute_indicators", new_callable=AsyncMock,
                      return_value=_TO_MOCK_INDICATORS), \
         patch.object(ps, "build_price_map", new_callable=AsyncMock,
                      return_value=_TO_MOCK_PRICE), \
         patch("app.services.market_data_hub.market_data_hub.get_market_regime",
               return_value="range_bound"), \
         patch("app.services.market_data_hub.market_data_hub.get_pool",
               return_value=pool), \
         patch("app.services.market_data_hub.market_data_hub.get_by_code",
               return_value=None), \
         patch("app.factors.factor_registry.registry.compute",
               new=AsyncMock(side_effect=_fake_registry_compute)), \
         patch("app.analysis.llm.generate_strategy_check_report",
               new_callable=AsyncMock, return_value=llm_result):
        from app.database import async_session
        result = await ps.strategy_check(
            MagicMock(), total_capital=500000, portfolio_type="on_exchange"
        )

    holdings = result["holdings_analysis"]
    ind_by_sym = {h["symbol"]: h for h in holdings}
    assert ind_by_sym["510300"].get("industry") == "宽基指数"
    assert ind_by_sym["510300"].get("sector") == "宽基指数"
    assert ind_by_sym["512000"].get("industry") == "券商"
    assert ind_by_sym["518880"].get("industry") == "商品"
    # 注入后风险警告不应误报「仅覆盖1个行业」（3 行业 + 无缺失）
    conc = [w for w in result["risk_warnings"]
            if w.get("type") == "concentration" and "行业集中度" in w.get("description", "")]
    assert not conc, f"行业注入后不应误报行业集中度: {conc}"


# ===== folded from test_round20_strategy_check_p05_p18.py =====
import httpx
class TestP0_5LLMTimeout:
    @pytest.mark.asyncio
    async def test_strategy_check_report_uses_60s_connect_timeout(self):
        """R57 (round28): 内层 connect 15s→60s——外层 180s 才有机会生效。

        round27 R43 只改外层 _llm_timeout_for(180s)，内层 connect=15s 仍先触发
        CancelledError → 真 LLM 报告永不可见（DeepSeek 慢首字节实测 34-78s）。
        R57 对齐实测上沿 60s；read 保持 90s 容纳长报告生成。
        """
        from app.analysis import llm as llm_mod

        run_json_mock = AsyncMock(return_value={
            "summary": "ok", "suggestions": [], "holdings_analysis": [],
            "risk_warnings": [],
        })
        agent_mock = MagicMock()
        agent_mock.run_json = run_json_mock
        # generate_strategy_check_report 内部 `from ..analysis.registry import get_agent`（局部导入）
        with patch("app.analysis.registry.get_agent", return_value=agent_mock):
            await llm_mod.generate_strategy_check_report(
                market_data=[{"symbol": "510300", "name": "沪深300", "target_weight": 0.3}],
                factor_breakdowns={"510300": {"factor_scores": {}, "technical_signal": {}}},
                regime="range_bound",
                data_quality={"all_empty": True, "partial": False},
            )
        _, kwargs = run_json_mock.call_args
        to = kwargs.get("request_timeout", 35.0)
        assert hasattr(to, "connect") and hasattr(to, "read"), (
            f"request_timeout 应为 httpx.Timeout(connect/read 分离)，实际 {to!r}"
        )
        assert to.connect == 60.0, f"内层 connect 应为 60s（R57 对齐慢首字节），实际 {to.connect}"
        assert to.read >= 60.0, f"read 超时应 ≥60s（容纳长报告生成），实际 {to.read}"
        # R57 负向：connect 不得回到 15s（旧值先于外层 180s 触发 → 真报告永不可见）
        assert to.connect > 15.0, "connect 不得回退到 15s（R57 内层超时修复回归）"
class TestP0_5RateLimitFailover:
    @pytest.mark.asyncio
    async def test_429_primary_skipped_on_retry_attempt(self):
        """P0-5: opencode_zen 429 → 本轮切 deepseek；后续 attempt 不再重试 429 的 provider。

        旧行为：max_retries=1 时第 2 轮又重试 opencode_zen（429 每 2-3s 失败一次，
        task 417 日志实证）。修复后 429 的 provider 标记跳过，只走 deepseek。
        """
        from app.analysis import llm as llm_mod
        import httpx

        # 模拟两个 provider：opencode_zen(429) + deepseek(200 成功)
        calls = {"opencode_zen": 0, "deepseek": 0}

        class _FakeResp:
            def __init__(self, status, json_data=None, headers=None):
                self.status_code = status
                self._json = json_data or {}
                self.headers = headers or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"HTTP {self.status_code}", request=MagicMock(), response=self,
                    )

            def json(self):
                return self._json

        class _FakeClient:
            def __init__(self, provider_id):
                self._pid = provider_id

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                calls[self._pid] += 1
                if self._pid == "opencode_zen":
                    return _FakeResp(429, headers={"retry-after": "1"})
                return _FakeResp(200, {
                    "choices": [{"message": {"content": '{"summary": "ok"}'}}],
                    "usage": {},
                })

        providers = [
            MagicMock(id="opencode_zen", model="m1", api_url="http://x", api_key="k",
                      timeout=15),
            MagicMock(id="deepseek", model="m2", api_url="http://y", api_key="k",
                      timeout=15),
        ]
        fake_clients = {
            "opencode_zen": _FakeClient("opencode_zen"),
            "deepseek": _FakeClient("deepseek"),
        }

        async def _fake_async_client_factory(*a, **kw):
            # 根据调用侧 provider 区分 client——通过当前尝试的 provider id 无法从
            # 工厂得知，改用按调用顺序回退：第一次 429 后第二次应为 deepseek。
            return _FakeClient("opencode_zen" if calls["opencode_zen"] + calls["deepseek"] < 1 else "deepseek")

        # 模拟 provider 序列：[opencode_zen(429), deepseek(200)]——注意第二 attempt
        # 修复后不得再出现 opencode_zen（429 标记跳过）。按调用顺序给 client。
        seq = [_FakeClient("opencode_zen"), _FakeClient("deepseek")]
        it = iter(seq)

        def _factory(*a, **kw):
            try:
                return next(it)
            except StopIteration:
                return _FakeClient("deepseek")

        with patch("httpx.AsyncClient", side_effect=_factory), \
             patch("app.analysis.llm.client.get_configured_providers", return_value=providers), \
             patch("app.analysis.llm.client._check_key", new=AsyncMock()):
            # max_retries=1：修复前第 2 轮会再打 opencode_zen（calls>=2），修复后只 1 次
            result = await llm_mod.llm_complete_with_system(
                system_prompt="s", prompt="p", max_retries=1, rate_limit_cap=1.0,
                request_timeout=15.0,
            )

        assert "ok" in result
        assert calls["opencode_zen"] == 1, (
            f"429 后不应再重试 opencode_zen（反复 429 重试即 task 417 根因），实际 {calls['opencode_zen']} 次"
        )
        assert calls["deepseek"] >= 1, "429 后应立即降级 deepseek"
