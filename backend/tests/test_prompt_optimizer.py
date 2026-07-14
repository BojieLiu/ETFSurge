import sys, json, asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_optimizer_clean import (
    parse_json,
    analyze_output,
    score_portfolio,
    get_csi300_history,
    get_csi300_weekly,
    estimate_portfolio_return,
)
from app.analysis.llm import SYSTEM_PROMPT, PORTFOLIO_DESIGN_SYSTEM_PROMPT, generate_portfolio_design


class TestParseJson:
    def test_clean_json(self):
        assert parse_json('{"a": 1}') == {"a": 1}

    def test_markdown_wrapped(self):
        assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_markdown_wrapped_no_lang(self):
        assert parse_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_extra_text(self):
        assert parse_json('text {"a": 1} text') == {"a": 1}

    def test_extra_text_with_fluff(self):
        assert parse_json('Here is the answer: {"portfolios": []}') == {"portfolios": []}

    def test_broken_json(self):
        assert parse_json('{"a":') == {}

    def test_empty_string(self):
        assert parse_json('') == {}

    def test_nested_json(self):
        result = parse_json('{"outer": {"inner": [1, 2]}}')
        assert result == {"outer": {"inner": [1, 2]}}


class TestAnalyzeOutput:
    def _make_etf(self, name, weight=0.1, logic="test"):
        return {"name": name, "symbol": "000000", "weight": weight, "logic": logic}

    def _make_portfolio(self, pf_type, etf_names, cash=0.12):
        etfs = [self._make_etf(n) for n in etf_names]
        return {
            "type": pf_type,
            "name": pf_type + "_portfolio",
            "etfs": etfs,
            "cash_weight": cash,
        }

    def test_normal_portfolio(self):
        names = [f"ETF{i}" for i in range(8)]
        pfs = [
            self._make_portfolio("aggressive", names, cash=0.10),
            self._make_portfolio("balanced", names, cash=0.15),
            self._make_portfolio("defensive", names, cash=0.15),
        ]
        result = analyze_output({"portfolios": pfs})
        assert result["total_etf_count"] == 24
        assert len(result["warnings"]) == 0

    def test_style_classification(self):
        etfs = [
            self._make_etf("红利ETF"),
            self._make_etf("科技ETF"),
            self._make_etf("黄金ETF"),
            self._make_etf("纳指ETF"),
            self._make_etf("沪深300ETF"),
        ]
        pf = self._make_portfolio("balanced", [])
        pf["etfs"] = etfs
        result = analyze_output({"portfolios": [pf]})
        assert result["style_breakdown"]["value"] == 1
        assert result["style_breakdown"]["growth"] == 1
        assert result["style_breakdown"]["commodity"] == 1
        assert result["style_breakdown"]["cross_border"] == 1
        assert result["style_breakdown"]["balanced"] == 1
        assert result["asset_categories"]["broad_index"] == 1

    def test_mixed_classification(self):
        etfs = [
            self._make_etf("银行ETF"),
            self._make_etf("保险ETF"),
            self._make_etf("半导体ETF"),
            self._make_etf("AIETF"),
            self._make_etf("新能源ETF"),
            self._make_etf("原油ETF"),
            self._make_etf("H股ETF"),
            self._make_etf("中概ETF"),
            self._make_etf("国债ETF"),
            self._make_etf("中证500ETF"),
        ]
        pf = self._make_portfolio("balanced", [])
        pf["etfs"] = etfs
        result = analyze_output({"portfolios": [pf]})
        assert result["style_breakdown"]["value"] == 2
        assert result["style_breakdown"]["growth"] == 3
        assert result["style_breakdown"]["commodity"] == 1
        assert result["style_breakdown"]["cross_border"] == 2
        assert result["style_breakdown"]["bond"] == 1
        assert result["asset_categories"]["broad_index"] == 1
        assert result["asset_categories"]["bond"] == 1

    def test_aggressive_cash_warning(self):
        pf = self._make_portfolio("aggressive", [f"ETF{i}" for i in range(8)], cash=0.15)
        result = analyze_output({"portfolios": [pf]})
        assert any("cash 15%" in w for w in result["warnings"])

    def test_defensive_cash_warning(self):
        pf = self._make_portfolio("defensive", [f"ETF{i}" for i in range(8)], cash=0.25)
        result = analyze_output({"portfolios": [pf]})
        assert any("cash 25%" in w and "may hurt returns" in w for w in result["warnings"])

    def test_too_few_etfs(self):
        pf = self._make_portfolio("balanced", ["ETF1", "ETF2", "ETF3"], cash=0.12)
        result = analyze_output({"portfolios": [pf]})
        assert any("only 3 ETFs" in w for w in result["warnings"])

    def test_empty_portfolios(self):
        result = analyze_output({})
        assert result["total_etf_count"] == 0
        assert len(result["warnings"]) == 0

    def test_cash_below_threshold(self):
        pf = self._make_portfolio("defensive", [f"ETF{i}" for i in range(8)], cash=0.05)
        result = analyze_output({"portfolios": [pf]})
        assert any("cash 5%" in w for w in result["warnings"])


class TestScorePortfolio:
    @patch("prompt_optimizer_clean.estimate_portfolio_return")
    @patch("prompt_optimizer_clean.get_csi300_weekly")
    def test_aggressive_full_score(self, mock_csi, mock_return):
        mock_csi.return_value = (0.3, 1.0)
        mock_return.return_value = (1.0, 2.0)
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        data = {"portfolios": [{"type": "aggressive", "etfs": etfs, "cash_weight": 0}]}
        score, details = asyncio.run(score_portfolio(data))
        assert score >= 30
        assert details["csi300_annual_return"] == 15.6

    @patch("prompt_optimizer_clean.estimate_portfolio_return")
    @patch("prompt_optimizer_clean.get_csi300_weekly")
    def test_balanced_medium_score(self, mock_csi, mock_return):
        mock_csi.return_value = (1.0, 0.5)
        mock_return.return_value = (0.05, 0.3)
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        data = {"portfolios": [{"type": "balanced", "etfs": etfs, "cash_weight": 0}]}
        score, details = asyncio.run(score_portfolio(data))
        pf = details["portfolio_scores"]["balanced"]
        assert "excess_return_vs_csi300" in pf

    @patch("prompt_optimizer_clean.estimate_portfolio_return")
    @patch("prompt_optimizer_clean.get_csi300_weekly")
    def test_defensive_vol_ok(self, mock_csi, mock_return):
        mock_csi.return_value = (0.3, 1.0)
        mock_return.return_value = (0.06, 0.3)
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        data = {"portfolios": [{"type": "defensive", "etfs": etfs, "cash_weight": 0}]}
        score, details = asyncio.run(score_portfolio(data))
        pf = details["portfolio_scores"]["defensive"]
        assert pf["vol_ok"] is True

    @patch("prompt_optimizer_clean.estimate_portfolio_return")
    @patch("prompt_optimizer_clean.get_csi300_weekly")
    def test_empty_portfolios(self, mock_csi, mock_return):
        result = asyncio.run(score_portfolio({}))
        assert result == {"error": "No portfolios"}

    @patch("prompt_optimizer_clean.get_csi300_weekly")
    def test_no_benchmark(self, mock_csi):
        mock_csi.return_value = (0.0, 0.0)
        data = {
            "portfolios": [
                {
                    "type": "aggressive",
                    "etfs": [{"name": "ETF", "symbol": "000001", "weight": 1.0}],
                    "cash_weight": 0,
                }
            ]
        }
        result = asyncio.run(score_portfolio(data))
        assert result == {"error": "No CSI 300 benchmark data"}


class TestSystemPrompt:
    """Tests for the production SYSTEM_PROMPT in app.analysis.llm.
    Note: specific risk gradients (85%, 65-75%, 55-65%) are now in V8 instructions
    in generate_portfolio_design(), not in SYSTEM_PROMPT."""

    def test_etf_count_range(self):
        assert "8~12" in SYSTEM_PROMPT

    def test_no_bonds(self):
        assert "不得包含任何债券" in SYSTEM_PROMPT

    def test_diversification_rule(self):
        assert "8~12" in SYSTEM_PROMPT and "分散化" in SYSTEM_PROMPT

    def test_data_driven(self):
        assert "数据驱动" in SYSTEM_PROMPT

    def test_market_stage_framework(self):
        assert "市场阶段" in SYSTEM_PROMPT

    def test_forbidden_individual_stocks(self):
        assert "不得推荐具体个股" in SYSTEM_PROMPT


class TestV8Instructions:
    """Verify V50 instructions are present in generate_portfolio_design() prompt."""

    @patch("app.analysis.llm.llm_complete_with_system")
    def test_risk_gradients_in_prompt(self, mock_llm):
        mock_llm.return_value = '{"plans": []}'
        result = asyncio.run(generate_portfolio_design(
            indices=[{"name": "上证指数", "price": 3200, "change_pct": -1.0}],
            commodities=[{"name": "黄金", "price": 580, "change_pct": 0.5}],
            market_data=[{"name": "标普500", "price": 5500, "change_pct": 0.8}],
            news=[{"title": "新闻"}], macro_news=[]
        ))
        # We verify via the call args that llm_complete_with_system received
        # system prompt is first arg, user prompt is second
        system_prompt = mock_llm.call_args[0][0]
        assert "权益仓位90-95%" in system_prompt
        assert "权益仓位85-92%" in system_prompt
        assert "权益仓位60-75%" in system_prompt

    @patch("app.analysis.llm.llm_complete_with_system")
    def test_no_bonds_in_prompt(self, mock_llm):
        mock_llm.return_value = '{"plans": []}'
        result = asyncio.run(generate_portfolio_design(
            indices=[], commodities=[], market_data=[],
            news=[{"title": "新闻"}], macro_news=[]
        ))
        system_prompt = mock_llm.call_args[0][0]
        assert "不得包含任何债券" in system_prompt or "不含债券" in system_prompt or "无债券" in system_prompt or "不包含债券" in system_prompt

    @patch("app.analysis.llm.llm_complete_with_system")
    def test_defensive_composition_in_prompt(self, mock_llm):
        mock_llm.return_value = '{"plans": []}'
        result = asyncio.run(generate_portfolio_design(
            indices=[{"name": "上证指数", "price": 3200, "change_pct": -1.0}],
            commodities=[{"name": "黄金", "price": 580, "change_pct": 0.5}],
            market_data=[], news=[{"title": "新闻"}], macro_news=[]
        ))
        system_prompt = mock_llm.call_args[0][0]
        assert "公用事业" in system_prompt or "宽基" in system_prompt or "资产类别" in system_prompt


class TestGetCsi300:
    @patch("requests.get")
    def test_get_csi300_history(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"close": "3000"},
            {"close": "3100"},
            {"close": "3200"},
        ]
        mock_get.return_value = mock_resp
        result = get_csi300_history(2)
        assert result == [3100.0, 3200.0]

    @patch("requests.get")
    def test_get_csi300_history_api_fail(self, mock_get):
        mock_get.side_effect = Exception("API error")
        result = get_csi300_history(2)
        assert result == []

    @patch("prompt_optimizer_clean.get_csi300_history")
    def test_get_csi300_weekly(self, mock_history):
        mock_history.return_value = [3000, 3100, 3200]
        avg, vol = get_csi300_weekly(2)
        assert avg == 3.28
        assert vol == 0.05

    @patch("prompt_optimizer_clean.get_csi300_history")
    def test_get_csi300_weekly_no_data(self, mock_history):
        mock_history.return_value = []
        avg, vol = get_csi300_weekly(2)
        assert avg == 0.0
        assert vol == 0.0


class TestEstimatePortfolioReturn:
    @patch("prompt_optimizer_clean.get_daily_returns")
    def test_single_etf(self, mock_returns):
        mock_returns.return_value = [1.0, 2.0, -1.0, 0.5, 0.0]
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        avg, vol = estimate_portfolio_return(etfs, 4)
        assert avg != 0.0
        assert vol != 0.0

    @patch("prompt_optimizer_clean.get_daily_returns")
    def test_multiple_etfs(self, mock_returns):
        mock_returns.return_value = [1.0, 2.0, -1.0, 0.5, 0.0]
        etfs = [
            {"name": "ETF1", "symbol": "000001", "weight": 0.6, "logic": "a"},
            {"name": "ETF2", "symbol": "000002", "weight": 0.4, "logic": "b"},
        ]
        avg, vol = estimate_portfolio_return(etfs, 4)
        assert avg != 0.0

    def test_empty_etfs(self):
        avg, vol = estimate_portfolio_return([], 4)
        assert avg == 0.0
        assert vol == 0.0

    @patch("prompt_optimizer_clean.get_daily_returns")
    def test_empty_returns(self, mock_returns):
        mock_returns.return_value = []
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        avg, vol = estimate_portfolio_return(etfs, 4)
        assert avg == 0.0
        assert vol == 0.0

    @patch("prompt_optimizer_clean.get_daily_returns")
    def test_too_few_days(self, mock_returns):
        mock_returns.return_value = [1.0, 2.0]
        etfs = [{"name": "ETF", "symbol": "000001", "weight": 1.0, "logic": "test"}]
        avg, vol = estimate_portfolio_return(etfs, 4)
        assert avg == 0.0
        assert vol == 0.0


class TestGeneratePortfolioDesign:
    @patch("app.analysis.llm.llm_complete_with_system")
    def test_successful_design(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "plans": [
                {
                    "style": "进攻型",
                    "style_label": "进攻型",
                    "portfolio_name": "进攻型组合",
                    "positioning": "捕捉主线高弹性机会",
                    "expected_return": 0.15,
                    "max_drawdown": 0.25,
                    "sharpe_ratio": 0.8,
                    "expected_characteristics": "预期年化波动20-25%，最大回撤区间22-28%",
                    "weight_logic": [
                        {"group": "科技三层穿透", "total_weight_pct": 45, "rationale": "宽基β+设备龙头+高弹性芯片"}
                    ],
                    "allocations": [
                        {"name": "沪深300ETF", "symbol": "510300", "target_weight": 0.15, "selection_rationale": "test", "weight_rationale": "test", "asset_class": "equity", "tracked_index": "000300", "key_metrics": {}}
                    ],
                    "market_analysis": {},
                    "allocation_rationale": {},
                    "risk_factors": [],
                    "rebalance_rules": "月度检视"
                }
            ],
            "market_environment": "测试环境",
            "design_text": "测试报告",
            "data_snapshot_time": "2026-07-14 20:28（北京时间）",
            "comparison_table": {}
        })
        result = asyncio.run(generate_portfolio_design([], [], [], [], []))
        assert "plans" in result
        assert result["plans"][0]["style"] == "进攻型"

    @patch("app.analysis.llm.llm_complete_with_system")
    def test_broken_json_fallback(self, mock_llm):
        mock_llm.return_value = 'Some text {"plans": [{"style": "平衡型", "style_label": "平衡型", "portfolio_name": "平衡型", "allocations": []}], "market_environment": "", "design_text": "", "data_snapshot_time": "", "comparison_table": {}} trailing'
        result = asyncio.run(generate_portfolio_design([], [], [], [], []))
        assert "plans" in result

    @patch("app.analysis.llm.llm_complete_with_system")
    def test_complete_failure(self, mock_llm):
        mock_llm.return_value = "Totally invalid response without JSON"
        result = asyncio.run(generate_portfolio_design([], [], [], [], []))
        assert "market_environment" in result
        # Fallback returns default plans, not empty
        assert isinstance(result["plans"], list)
        assert len(result["plans"]) == 3
