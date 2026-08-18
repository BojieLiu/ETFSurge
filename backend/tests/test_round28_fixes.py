"""
round28 修复防护测试（docs/round28-container-reacceptance-and-optimization.md §14）。

覆盖：
- R56: 预热 global_indices 基数断言——禁止 create_task 两次（F3 重构遗漏回归）
- R57: 策略检查 LLM 内层 connect 超时 15s→60s（外层 180s 才有机会生效）
- R58: IC 回填 K 线缓存未就绪 → 重试而非永久跳过（_wait_for_kline_rows）
- R61: 港股 realtime 源空 → last-good 报价兜底（is_estimated 标注）
- R62: indicators asset_type 按 symbol 推断市场（AAPL→US / 00700→HK）
- R65: 资讯 ai_summary 规则兜底（_rule_news_summary 非 null）
- R66: 因子分跨屏一致——策略检查复用 design 同款 ic_series 聚合

mock 数据源，无网络；对 main.py 预热结构做源码级守卫（防 F3 式重构遗漏）。
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


# ── R56: global_indices 预热基数断言 ──────────────────────────────────────


class TestR56WarmupGlobalIndicesCardinality:
    def test_standalone_create_task_removed(self):
        """负向：禁止独立 `create_task(_warmup_global_indices())` 残留（F3 重构遗漏）。

        round28 §1: main.py:268 独立 task + sequence :334 重复调用 → 双重预热 18.4s。
        源码级守卫：独立 create_task 形式不得出现（该调用只允许出现在 sequence 内）。
        """
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "create_task(_warmup_global_indices())" not in src, \
            "独立 create_task(_warmup_global_indices()) 应已删除（R56）"

    def test_sequence_contains_global_indices_once(self):
        """sequence 内 `_warmup_global_indices(),` 恰好出现一次（基数断言）。"""
        src = open(main_mod.__file__, encoding="utf-8").read()
        # 定义行是 `async def _warmup_global_indices():`（无逗号），
        # sequence 内调用是 `_warmup_global_indices(),`（带逗号）——精确匹配调用点。
        count = src.count("_warmup_global_indices(),")
        assert count == 1, f"sequence 内 _warmup_global_indices() 应为 1 次，实际 {count}（双重执行回归）"

    def test_warmup_sequence_has_design_data_step(self):
        """R59④: 预热 sequence 包含设计数据预热步骤（K 线缓存预热）。"""
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "_warmup_design_data()" in src, "预热 sequence 应含设计数据预热（R59④）"

    def test_design_warmup_awaits_market_warmup(self):
        """R59④ 修复: 设计数据预热必须先等行情缓存预热任务完成（防 pool-empty 竞态跳过）。

        round28 实测：_warmup_market_cache 是非阻塞后台任务（sequence 内立即返回），
        旧 _warmup_design_data 直接读 pool → 必然先于 pool 填充执行 → 跳过
        （日志「design-data warmup skipped: pool empty」）→ R58 IC 回填拿不到
        K 线、R59③ 永不落盘。修复须 await _market_warmup_task + 轮询 pool。
        """
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "_market_warmup_task" in src, \
            "设计数据预热必须等待行情预热任务（R59④ 防竞态）"
        assert "asyncio.shield(_mkt_task)" in src, \
            "必须 await 市场预热任务（asyncio.shield 防超时取消）"


# ── R57: 策略检查 LLM 内层 connect 超时 ───────────────────────────────────


class TestR57StrategyCheckInnerTimeout:
    @pytest.mark.asyncio
    async def test_inner_request_timeout_connect_is_60(self):
        """generate_strategy_check_report 的 httpx.Timeout(connect=60.0)。

        round28 §2.2: round27 R43 只改外层 _llm_timeout_for(180s)，内层 connect=15s
        先触发 CancelledError → 真 LLM 报告永不可见。内层 connect 须 ≥60s（对齐
        DeepSeek 慢首字节实测 34-78s），使外层 180s 有机会生效。
        """
        import httpx
        from app.analysis import registry

        captured = {}

        async def _fake_run_json(*args, **kwargs):
            captured["request_timeout"] = kwargs.get("request_timeout")
            return {"summary": "ok", "suggestions": [], "holdings_analysis": [],
                    "risk_warnings": []}

        fake_agent = MagicMock()
        fake_agent.run_json = _fake_run_json
        with patch.object(registry, "get_agent", return_value=fake_agent):
            from app.analysis import llm
            await llm.generate_strategy_check_report(
                market_data=[{"symbol": "510300", "name": "x", "target_weight": 0.5}],
                factor_breakdowns={},
                regime="range_bound",
            )
        rt = captured.get("request_timeout")
        assert rt is not None, "request_timeout 必须透传到 run_json"
        assert rt.connect == 60.0, f"内层 connect 应为 60s（对齐慢首字节实测），实际 {rt.connect}"
        assert rt.read == 90.0, f"read 应保持 90s 容纳长生成，实际 {rt.read}"

    def test_outer_budget_still_dominant(self):
        """外层 _llm_timeout_for 数据完整档仍为 180s（内外层超时层级不变）。"""
        from app.services.portfolio_service import _llm_timeout_for
        assert _llm_timeout_for({"all_empty": False, "partial": False}) == 180
        assert _llm_timeout_for({"all_empty": True}) == 15
        assert _llm_timeout_for({"all_empty": False, "partial": True}) == 30


# ── R58: IC 回填 K 线缓存未就绪重试 ───────────────────────────────────────


class TestR58IcBackfillRetry:
    class _FakeHub:
        """渐进就绪的假 hub——第 1 次检查空、第 2 次检查有 rows。"""

        def __init__(self):
            self._checks = 0

        @property
        def _kline_cache_rows(self):
            self._checks += 1
            if self._checks >= 2:
                return {"510300": [{"date": "2026-08-14", "close": 3.8}]}
            return {}

    @pytest.mark.asyncio
    async def test_retries_until_kline_ready(self):
        """K 线缓存第 1 次未就绪 → 重试第 2 次就绪 → 返回 rows（非永久跳过）。"""
        hub = self._FakeHub()
        with patch.object(main_mod, "logger") as _logger:
            rows = await main_mod._wait_for_kline_rows(
                hub, initial_sleep=0.0, retry_delays=(0.0, 0.0), max_retries=2
            )
        assert rows, "缓存第 2 次就绪后应返回 rows（重试生效，非永久跳过）"
        assert hub._checks >= 2, f"应至少检查 2 次，实际 {hub._checks}"

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        """缓存恒未就绪 → 重试耗尽返回空 dict（调用方诚实放弃）。"""
        hub = MagicMock()
        hub._kline_cache_rows = {}
        with patch.object(main_mod, "logger") as _logger:
            rows = await main_mod._wait_for_kline_rows(
                hub, initial_sleep=0.0, retry_delays=(0.0, 0.0), max_retries=2
            )
        assert rows == {}, "重试耗尽后应返回空 dict（不得返回 None 或抛异常）"

    @pytest.mark.asyncio
    async def test_wait_for_pool_symbols_polls_until_ready(self):
        """R58 延伸: 启动时组合池未就绪（refresh() 60-90s）→ 轮询等待非空（非恒跳过）。"""
        class _FakePoolHub:
            def __init__(self):
                self._calls = 0

            def get_pool(self):
                self._calls += 1
                if self._calls >= 3:
                    return {
                        "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
                        "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
                    }
                return {}

        hub = _FakePoolHub()
        with patch.object(main_mod, "logger"):
            syms = await main_mod._wait_for_pool_symbols(
                hub, checks=5, interval=0.0,
            )
        assert "510300" in syms, "池就绪后应返回 symbol 列表（轮询生效，非恒跳过）"
        assert hub._calls >= 3, f"应轮询 ≥3 次，实际 {hub._calls}"

    @pytest.mark.asyncio
    async def test_wait_for_pool_symbols_gives_up_honestly(self):
        """池恒空 → 返回空列表（调用方诚实放弃，不抛异常）。"""
        hub = MagicMock()
        hub.get_pool.return_value = {}
        with patch.object(main_mod, "logger"):
            syms = await main_mod._wait_for_pool_symbols(hub, checks=2, interval=0.0)
        assert syms == [], "池恒空应返回空列表"


# ── R61: 港股 realtime last-good 兜底 ─────────────────────────────────────


class TestR61HkLastGoodFallback:
    @pytest.mark.asyncio
    async def test_hk_realtime_sources_empty_falls_back_to_last_good(self, monkeypatch):
        """HK 数据源冷却返回空 → 读 last-good 报价兜底（is_estimated 标注）。"""
        from app.fetchers import china_market

        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr(
            china_market, "fetch_hk_stock_realtime",
            lambda *a, **k: [],  # 数据源冷却：返回空列表
        )
        monkeypatch.setattr(
            ms, "cache_get",
            AsyncMock(return_value={"symbol": "00700", "name": "腾讯控股",
                                    "price": 380.0, "change_pct": 1.2,
                                    "as_of": "2026-08-17T08:00:00Z"}),
        )
        result = await ms.get_asset_realtime("00700", "HK")
        assert result is not None, "HK realtime 源空时应返回 last-good 兜底而非 None"
        assert result["price"] == 380.0
        assert result.get("is_estimated") is True, "兜底价必须标注 is_estimated"
        assert result.get("estimate_source") == "last_good"

    @pytest.mark.asyncio
    async def test_hk_no_last_good_returns_none(self, monkeypatch):
        """HK 源空 + 无 last-good 缓存 → 返回 None（诚实，不编造数据）。"""
        from app.fetchers import china_market

        monkeypatch.setattr(ms, "_asset_realtime_cache", {})
        monkeypatch.setattr(
            china_market, "fetch_hk_stock_realtime",
            lambda *a, **k: [],
        )
        monkeypatch.setattr(ms, "cache_get", AsyncMock(return_value=None))
        result = await ms.get_asset_realtime("00700", "HK")
        assert result is None, "无 last-good 缓存时不得编造数据"


# ── R62: indicators asset_type 按 symbol 推断 ─────────────────────────────


class TestR62InferMarketFromSymbol:
    @pytest.mark.parametrize("symbol,expected", [
        ("00700", "HK"),          # 5 位数字 0 开头 → 港股
        ("02800", "HK"),
        ("00700.HK", "HK"),       # 显式后缀优先
        ("AAPL", "US"),           # 纯字母 → 美股
        ("SPY", "US"),
        ("510300", "A"),          # 6 位数字 → A 股
        ("600519", "A"),
        ("sh688981", "A"),        # 交易所前缀剥除后仍 A
        ("", "A"),                # 空 → 保守 A
    ])
    def test_infer(self, symbol, expected):
        assert infer_market_from_symbol(symbol) == expected, \
            f"{symbol} → 应推断为 {expected}"

    @pytest.mark.asyncio
    async def test_indicators_endpoint_infers_us_asset_type(self, monkeypatch):
        """/market/indicators/AAPL 默认 asset_type='A' → 自动推断为 US（R62）。"""
        from app.routers import market as market_router

        async def _fake_history(symbol, asset_type, period):
            # 40 根 K 线（≥30 满足 data_available）
            rows = [{"date": f"2026-08-{i:02d}", "open": 10 + i * 0.1,
                     "close": 10 + i * 0.1, "high": 10 + i * 0.2,
                     "low": 10 - i * 0.05, "volume": 1000} for i in range(1, 41)]
            return rows

        captured = {}

        async def _fake_get_market_history(symbol, asset_type, period):
            captured["asset_type"] = asset_type
            return await _fake_history(symbol, asset_type, period)

        with patch.object(market_router.market_data_hub,
                          "get_market_history", _fake_get_market_history), \
             patch.object(market_router.market_data_hub, "is_kline_stale",
                          lambda *a: False):
            result = await market_router.indicators("AAPL", asset_type="A")
        assert captured["asset_type"] == "US", \
            f"indicators(AAPL) 应推断 asset_type=US，实际 {captured['asset_type']}"
        assert result.get("asset_type") == "US", \
            f"响应 asset_type 应为 US，实际 {result.get('asset_type')}"


# ── R65: 资讯 ai_summary 规则兜底 ─────────────────────────────────────────


class TestR65RuleNewsSummary:
    def test_content_first_sentence(self):
        """content 存在 → 取首句（截断 ≤80 字）。"""
        item = {"title": "重磅", "content": "央行宣布降息。市场反应积极。后续关注。"}
        s = _rule_news_summary(item)
        assert s == "央行宣布降息", f"应取 content 首句，实际 {s!r}"

    def test_long_content_truncated(self):
        """超长首句截断到 80 字 + 省略号。"""
        item = {"title": "x", "content": "长" * 200 + "。"}
        s = _rule_news_summary(item)
        assert s.endswith("…"), f"超长应截断加省略号，实际 {s[-5:]!r}"
        assert len(s) <= 81

    def test_no_content_falls_back_title(self):
        """content 空 → 回落 title。"""
        item = {"title": "美联储议息会议", "content": ""}
        assert _rule_news_summary(item) == "美联储议息会议"

    def test_empty_item_returns_none(self):
        assert _rule_news_summary({}) is None


# ── R66: 因子分跨屏一致（复用 ic_series 聚合） ────────────────────────────


class TestR66FactorCompositeIcSeries:
    def test_within_symbol_composite_passes_ic_series(self):
        """_within_symbol_factor_composite 必须透传 ic_series（与 design 同口径）。

        round28 §2.4: 策略检查旧实现不传 ic_series → 等权回退，而 allocation_engine
        传 ic_series（IC 加权）→ 同标的数值量级不一致（-0.9007 vs -0.08）。
        """
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as _reg

        captured = {}
        fake_ic = {"technical.ma.sma_5": [0.1, 0.2]}
        _reg._ic_series_cache = fake_ic

        def _fake_aggregate(fs, **kwargs):
            captured["ic_series"] = kwargs.get("ic_series")
            return {"technical": 0.5, "momentum": 0.3, "valuation": 0.2,
                    "sentiment": 0.1}

        with patch("app.core.factor_aggregate.aggregate_factor_scores",
                   side_effect=_fake_aggregate):
            comp = ps._within_symbol_factor_composite(
                {"technical.ma.sma_5": 0.6, "momentum.20d": 0.4}
            )
        assert captured.get("ic_series") == fake_ic, \
            "策略检查因子复合必须透传 ic_series（与设计同口径，R66）"
        assert comp is not None and comp > 0

    def test_full_pool_composite_labels_match(self):
        """_full_pool_factor_composite 返回 reference 标签（相对候选池/单标的）。"""
        from app.services import portfolio_service as ps
        out = ps._full_pool_factor_composite({
            "510300": {"factor_scores": {"technical.ma.sma_5": 0.6}},
        })
        assert "510300" in out
        assert out["510300"].get("reference") in ("相对候选池", "单标的")


# ── R59①: refresh 采集并发化——K 线预热回退 last-good 池 ─────────────────────


class TestR59RefreshConcurrentKlinePreWarm:
    def test_prewarm_falls_back_to_pool_when_by_code_empty(self):
        """R59① 修复: 冷启动/重启时 _by_code 为空（扫描未完成）→ K 线预热必须回退
        last-good 池（_pool），否则预热线恒空转（实测无「kline pre-warm finished」日志）。
        """
        src = open(
            os.path.join(os.path.dirname(main_mod.__file__), "services", "market_data_hub.py"),
            encoding="utf-8",
        ).read()
        # _warm_kline_concurrent 内：_by_code 为空时遍历 _pool.values() 收集 symbol
        assert "_last_pool = getattr(self, \"_pool\", None) or {}" in src, \
            "K 线预热须在 _by_code 为空时回退 last-good 池（R59① 防空转）"


# ── R59②: design 超时 → skip_refresh 降级重试（不失败、不掩盖） ─────────────


class TestR59DesignDegradeRetry:
    """round28 §14.4.2 ②: 数据采集超时后以 skip_refresh=True 重试（缓存快照兜底），
    产出降级方案（degradation.mode=degraded）而非「方案生成超时」失败。"""

    @staticmethod
    def _apply_engine_path_mocks(monkeypatch):
        """打桩 generate_enhanced_design 引擎路径所需全部依赖（池非空 → 走 engine 分支）。"""
        from app.services.market_data_hub import market_data_hub as hub
        from app.services import strategy_design as sd

        pool = {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511010", "name": "国债ETF", "layer": "defense"}],
        }

        def _fake_get_pool(layer=None):
            return pool.get(layer, []) if layer else pool

        monkeypatch.setattr(hub, "get_factor_matrix", lambda: {
            "510300": {"technical.ma.sma_5": 0.5},
            "159915": {"momentum.20d": 0.4},
            "511010": {"valuation.pe": -0.3},
        })
        monkeypatch.setattr(hub, "get_pool", _fake_get_pool)
        monkeypatch.setattr(hub, "get_market_regime", lambda: "range_bound")
        monkeypatch.setattr(hub, "get_sector_momentum", lambda: [])
        monkeypatch.setattr(hub, "get_by_code", lambda *a: {})
        monkeypatch.setattr(hub, "get_asset_realtime",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(sd, "_build_market_context", AsyncMock(return_value={}))
        monkeypatch.setattr(sd, "_market_data_fetched_at", lambda *a: "2026-08-18T00:00:00Z")
        monkeypatch.setattr(sd, "engine_allocate", lambda **kw: [{
            "id": "balanced", "label": "平衡型", "layer_budget": {},
            "allocations": [
                {"symbol": "510300", "name": "沪深300ETF", "weight": 0.3, "layer": "core"},
                {"symbol": "159915", "name": "创业板ETF", "weight": 0.2, "layer": "satellite"},
            ],
        }])
        monkeypatch.setattr(sd, "apply_risk_controls",
                            lambda allocs, fm, **kw: allocs)
        monkeypatch.setattr(sd, "_correlation_medians_for", lambda *a: {})
        monkeypatch.setattr(sd, "_correlation_matrix_for", lambda *a: {})
        monkeypatch.setattr(sd, "build_rationale", lambda **kw: "理由")
        monkeypatch.setattr(sd, "_find_candidate_meta", lambda *a: {})
        monkeypatch.setattr(sd, "_kline_change_pct", lambda *a: None)
        monkeypatch.setattr(sd, "_snapshot_change_pct", lambda *a: None)
        monkeypatch.setattr(sd, "_validate_target_amount_consistency", lambda *a: None)

    @pytest.mark.asyncio
    async def test_skip_refresh_skips_refresh_and_marks_degraded(self, monkeypatch):
        """skip_refresh=True → refresh() 不调用、hub._degraded=True、degradation.mode='degraded'。"""
        from app.services.market_data_hub import market_data_hub as hub
        self._apply_engine_path_mocks(monkeypatch)

        refresh_calls = []

        async def _no_refresh():
            refresh_calls.append(1)
        monkeypatch.setattr(hub, "refresh", _no_refresh)

        try:
            from app.services.strategy_design import generate_enhanced_design
            result = await generate_enhanced_design(capital=500000, skip_refresh=True)
        finally:
            hub._degraded = False  # 重置单例状态防串扰

        assert refresh_calls == [], f"skip_refresh 时不得调用 refresh()，实际 {len(refresh_calls)} 次"
        assert result["degradation"]["mode"] == "degraded", \
            f"skip_refresh 降级重试应标注 degradation.mode=degraded，实际 {result['degradation']['mode']}"
        assert "降级" in result["degradation"]["reason"]
        assert result["degradation"]["pool_degraded"] is True
        assert len(result["strategies"]) >= 1, "降级重试仍应产出可用方案（非失败）"

    @pytest.mark.asyncio
    async def test_off_hours_with_pool_skips_realtime_refresh(self, monkeypatch):
        """R59⑤: 非交易时段 + last-good 池 → 主动走快照（不调 refresh 干等实时源）。"""
        from app.services.market_data_hub import market_data_hub as hub
        self._apply_engine_path_mocks(monkeypatch)

        refresh_calls = []

        async def _no_refresh():
            refresh_calls.append(1)
        monkeypatch.setattr(hub, "refresh", _no_refresh)
        monkeypatch.setattr(hub, "_is_market_hours", lambda: False)
        # R59⑤ 判定依赖 _pool 非空（last-good 池存在）——注入假池（monkeypatch 自动还原）
        monkeypatch.setattr(hub, "_pool", {
            "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
            "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
            "defense": [{"symbol": "511010", "name": "国债ETF", "layer": "defense"}],
        })

        try:
            from app.services.strategy_design import generate_enhanced_design
            result = await generate_enhanced_design(capital=500000)
        finally:
            hub._degraded = False

        assert refresh_calls == [], f"盘后 + 池非空时应跳过 refresh，实际 {len(refresh_calls)} 次"
        assert result["degradation"]["pool_degraded"] is True
        assert len(result["strategies"]) >= 1


class TestR59PipelineTimeoutDegradeRetry:
    """task_manager 层：DESIGN_DATA_TIMEOUT 超时 → skip_refresh=True 重试 → 任务完成。"""

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_timeout_triggers_skip_refresh_retry(self, mock_gen, mock_llm, mock_db, task_mgr):
        """首次调用超时 → 二次调用 skip_refresh=True → 任务 completed（非 failed）。"""
        from app.tasks.task_manager import design_pipeline
        from tests.test_design_pipeline_integration import (
            _mock_strategies, _mock_market_context, _make_mock_session,
        )

        calls = []
        first = True

        async def _flaky(**kwargs):
            calls.append(dict(kwargs))
            nonlocal first
            if first:
                first = False
                raise asyncio.TimeoutError("数据源响应过慢")
            return {"strategies": _mock_strategies(), "market_context": _mock_market_context()}

        mock_gen.side_effect = _flaky
        mock_llm.return_value = "## 市场分析\n当前市场处于震荡阶段。"
        mock_db.side_effect = [
            _make_mock_session(design_id=1101),  # Stage 3 写库
            _make_mock_session(design_id=1101),  # Stage 4 回填
        ]

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed", f"降级重试应完成任务，实际 {got['status']}"
        assert len(calls) == 2, f"应重试一次（共 2 次调用），实际 {len(calls)}"
        assert calls[0].get("skip_refresh") is None, "首次调用不得带 skip_refresh"
        assert calls[1].get("skip_refresh") is True, \
            f"超时后二次调用必须 skip_refresh=True（降级重试），实际 {calls[1]}"


# ── R58 延伸: IC 计算对字符串因子值防御（abs(str) TypeError 修复） ──────────


class TestR58IcTrackerStringTolerance:
    """round28 实测：R58 回填真正跑起来后，数据源异常时 factor value 可能为 str
    → abs(str) TypeError 使整批 IC 计算失败（「bad operand type for abs(): 'str'」），
    factor_ic_records 仍写不进 ≥60 交易日。防御：非数值因子值跳过（计零分）。"""

    def test_compute_periodic_ic_tolerates_str_factor_values(self):
        """str 因子值 → 跳过不崩溃；数值因子仍参与 IC 计算。"""
        from app.factors.ic_tracker import ic_tracker

        market_data = {
            "510300": {"close": [3.8, 3.9, 4.0, 4.1, 4.2]},
            "159915": {"close": [1.0, 1.1, 1.2, 1.3, 1.4]},
            "511010": {"close": [100.0, 100.5, 101.0, 101.5, 102.0]},
        }
        factor_values = {
            "510300": {"technical.rsi.rsi_14": "12.5"},  # 数据源异常 → str
            "159915": {"technical.rsi.rsi_14": 55.0},
            "511010": {"technical.rsi.rsi_14": 30.0},
        }
        out = ic_tracker.compute_periodic_ic(factor_values, market_data, window=1)
        assert isinstance(out, dict), "str 因子值不得使 IC 计算抛异常"
        # str 值被跳过，仍应有 IC 结果（数值因子参与）

    def test_all_str_factor_values_no_crash(self):
        """全为 str（整批异常）→ 返回空 dict 不抛异常。"""
        from app.factors.ic_tracker import ic_tracker

        market_data = {
            "510300": {"close": [3.8, 3.9, 4.0, 4.1, 4.2]},
            "159915": {"close": [1.0, 1.1, 1.2, 1.3, 1.4]},
            "511010": {"close": [100.0, 100.5, 101.0, 101.5, 102.0]},
        }
        factor_values = {
            sym: {"technical.rsi.rsi_14": "bad"} for sym in market_data
        }
        out = ic_tracker.compute_periodic_ic(factor_values, market_data, window=1)
        assert isinstance(out, dict)


# ── R60: symbol-analysis K 线注入（Hub 缓存兜底） ──────────────────────────


class TestR60SymbolAnalysisKlineFallback:
    """round28 §14.1 R60: 指标端点有数据时，分析端点不得「历史K线为空」。
    get_history 全链空 → 从 Hub K 线缓存取任意年龄数据兜底注入 prompt。"""

    @staticmethod
    def _fake_req(symbol="600519", name="贵州茅台"):
        class _FakeReq:
            def __init__(self):
                self.symbol = symbol
                self.name = name
                self.asset_type = "A"
                self.market = "A"
                self.question = ""
        return _FakeReq()

    @staticmethod
    def _make_prompt_capture():
        captured = {}

        def _fake_agent(name):
            class _A:
                async def run_stream(self, prompt, **kwargs):
                    # R49: prompt 捕获发生在 body_iterator 消费期间（async generator）
                    captured["prompt"] = prompt
                    yield {"event": "done", "data": {"full_text": "ok", "usage": {}}}
            return _A()

        return captured, _fake_agent

    @staticmethod
    async def _collect(resp):
        async for chunk in resp.body_iterator:
            pass

    @pytest.mark.asyncio
    async def test_history_empty_falls_back_to_hub_kline_cache(self, monkeypatch):
        """R60 负向: get_history 全链空 + Hub K线缓存有数据 → prompt 含历史K线与技术指标。"""
        from app.routers import analysis as ar

        captured, fake_agent = self._make_prompt_capture()

        async def _fake_realtime(symbol, asset_type):
            return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

        async def _fake_history(symbol, asset_type, period="daily"):
            return []  # 盘后/源冷却：全链空

        rows = [
            {"date": "2026-08-14", "open": 1680.0, "close": 1700.0, "high": 1710.0,
             "low": 1670.0, "volume": 1000},
            {"date": "2026-08-15", "open": 1700.0, "close": 1705.0, "high": 1715.0,
             "low": 1695.0, "volume": 1100},
        ]

        monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
        monkeypatch.setattr(ar, "get_history", _fake_history)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_rows_any", lambda symbol: rows)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_age_seconds", lambda symbol: 86400.0)
        monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
        monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
        monkeypatch.setattr(ar, "compute_all_indicators",
                            lambda hist: {"rsi": 55.2, "ma5": 1701.0} if hist else {})
        monkeypatch.setattr(ar, "get_agent", fake_agent)
        monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", lambda *a, **k: None)

        resp = await ar.symbol_analysis_stream(self._fake_req())
        await self._collect(resp)
        assert "历史K线" in captured["prompt"]
        assert "2026-08-15" in captured["prompt"], "prompt 应含 Hub 缓存 K 线（不得「K线为空」）"
        assert "技术指标" in captured["prompt"] and "rsi" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_hub_cache_empty_still_honest(self, monkeypatch):
        """R60 负向: get_history 与 Hub 缓存均空 → 诚实标注「无」（不伪造 K 线）。"""
        from app.routers import analysis as ar

        captured, fake_agent = self._make_prompt_capture()

        async def _fake_realtime(symbol, asset_type):
            return {"symbol": symbol, "name": "贵州茅台", "price": 1700.0}

        async def _fake_history(symbol, asset_type, period="daily"):
            return []

        monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
        monkeypatch.setattr(ar, "get_history", _fake_history)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_rows_any", lambda symbol: None)
        monkeypatch.setattr(ar.market_data_hub, "get_kline_age_seconds", lambda symbol: None)
        monkeypatch.setattr(ar.market_data_hub, "get_news_headlines", lambda: [])
        monkeypatch.setattr(ar.market_data_hub, "get_news_macro", lambda: [])
        monkeypatch.setattr(ar, "compute_all_indicators", lambda hist: {} if not hist else {"rsi": 1.0})
        monkeypatch.setattr(ar, "get_agent", fake_agent)
        monkeypatch.setattr("app.routers.analysis.asyncio.to_thread", lambda *a, **k: None)

        resp = await ar.symbol_analysis_stream(self._fake_req())
        await self._collect(resp)
        assert "历史K线(最近30条)：无" in captured["prompt"], \
            "两源均空时应诚实标注「无」，不得伪造 K 线"