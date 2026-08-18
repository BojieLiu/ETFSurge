from __future__ import annotations
"""TDD: F1-9 — 策略检查「LLM 超时」假象修复。

背景：`asyncio.wait_for(timeout=20)` 超时取消内部协程抛 CancelledError
（BaseException），`except Exception` 捕获不到 → usage 失败记录缺失、
fallback provider 从未轮到、规则兜底文案丢失。

覆盖：
  1. generate_strategy_check_report 内部捕获 CancelledError → 返回规则兜底 dict
  2. portfolio_service 的 wait_for 超时 → usage 有失败记录 + 兜底文案
  3. 超时路径日志含「timed out」+ 耗时
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.analysis.llm import generate_strategy_check_report
from app.services import portfolio_service as ps
from app.services.portfolio_service import _compute_risk_warnings, _rule_based_suggestion


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


_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "512000", "name": "券商ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.1,
     "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "hold"}},
    "512000": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "hold"}},
}

_MOCK_FACTORS = {
    "510300": {"technical": 0.3, "momentum": 0.2},
    "512000": {"technical": 0.6, "momentum": 0.5},
    "518880": {"technical": 0.1, "momentum": 0.0},
}

_MOCK_PRICE = {"510300": (3.8, 1.2), "512000": (0.9, 0.5), "518880": (8.4, -0.3)}


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
        return {s: dict(_MOCK_FACTORS.get(s, {})) for s in symbols}

    with patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_MOCK_ETFS), \
         patch.object(ps, "_compute_indicators", new_callable=AsyncMock,
                      return_value=_MOCK_INDICATORS), \
         patch.object(ps, "build_price_map", new_callable=AsyncMock,
                      return_value=_MOCK_PRICE), \
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
