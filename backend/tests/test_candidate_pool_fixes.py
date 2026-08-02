"""
M1-M3 (docs/combination-design-review.md): 候选池口径修正测试。

- M1: WIDE_BASIS_STATIC 补充 中证A500(560600/159338) 与红利(512890/515080)，
      CORE_KEYWORDS 增加"红利低波/中证红利"（用户决策 2026-08-01：红利归 core 防守端）。
- M2: _inject_static_wide_basis 注入后打 INFO 日志；required 未命中打 WARNING（消除静默失效）。
- M3: tracked_index / segment 家族归一化——中证500价值/成长/增强 → 中证500，
      沪深300增强/价值 → 沪深300（同一指数家族只保留 fund_scale 最大者）。

全部 mock，无网络调用。
"""

import logging

import pytest

from app.fetchers.etf_scanner import (
    CORE_KEYWORDS,
    CORE_REQUIRED,
    WIDE_BASIS_STATIC,
    _inject_static_wide_basis,
    _log_missing_required,
    classify_etf,
    full_pipeline,
)
from app.engine.allocation_engine import _normalize_segment
from app.services.market_data_hub import MarketDataHub


# ── M1: 候选池静态兜底清单 ────────────────────────────────────

class TestM1StaticPool:
    def test_wide_basis_static_contains_a500(self):
        """M1: WIDE_BASIS_STATIC 必须包含中证A500（沪市 560600 + 深市兜底 159338）。"""
        codes = {e["symbol"] for e in WIDE_BASIS_STATIC if e["layer"] == "core"}
        assert "560600" in codes, "560600 中证A500ETF 必须在静态兜底清单（CORE_REQUIRED 依赖）"
        assert "159338" in codes, "159338 中证A500ETF（深市兜底）必须在静态兜底清单"

    def test_wide_basis_static_contains_dividend(self):
        """M1: 红利低波(512890)/中证红利(515080) 归 core（用户决策 2026-08-01）。"""
        core = {e["symbol"]: e["layer"] for e in WIDE_BASIS_STATIC}
        assert core.get("512890") == "core", "红利低波 512890 必须归 core"
        assert core.get("515080") == "core", "中证红利 515080 必须归 core"

    def test_core_keywords_contains_dividend(self):
        """M1: CORE_KEYWORDS 含 '红利低波'/'中证红利' → classify_etf 正确分类。"""
        assert "红利低波" in CORE_KEYWORDS
        assert "中证红利" in CORE_KEYWORDS
        assert classify_etf("红利低波ETF") == "core"
        assert classify_etf("中证红利ETF") == "core"

    def test_static_fallback_change_pct_is_none(self):
        """F3 R9 联动：静态兜底条目 change_pct 置 None（不伪造 0% 涨跌）。"""
        for e in WIDE_BASIS_STATIC:
            assert e.get("change_pct") is None, f"{e['symbol']} 静态条目 change_pct 应为 None 而非 0.0"

    def test_a500_in_core_required(self):
        """560600 是 CORE_REQUIRED 成员（注入校验会检查它）。"""
        assert "560600" in CORE_REQUIRED


# ── M2: 注入校验日志 ──────────────────────────────────────────

class TestM2InjectionLogging:
    def test_inject_logs_info_when_injected(self, caplog):
        """M2: 静态兜底注入成功后打 INFO（注入数量与代码）。"""
        core = [{"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300",
                 "fund_scale": 900.0, "amount": 2e9, "price": 0.0, "change_pct": None}]
        with caplog.at_level(logging.INFO, logger="app.fetchers.etf_scanner"):
            _inject_static_wide_basis(core, "core", [])
        assert any("WideBasisInject" in r.message for r in caplog.records), \
            "注入后必须打 INFO 日志（WideBasisInject）"
        # 注入后 560600 必须进 core
        codes = {e["symbol"] for e in core}
        assert "560600" in codes and "512890" in codes

    def test_missing_required_warns(self, caplog):
        """M2: required 未命中打 WARNING（消除静默失效）。"""
        with caplog.at_level(logging.WARNING, logger="app.fetchers.etf_scanner"):
            _log_missing_required("core", ["510300", "999999"], [{"symbol": "510300"}])
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("REQUIRED codes missing" in r.message for r in warnings), \
            "required 未命中必须打 WARNING"


# ── M3: 家族归一化 ────────────────────────────────────────────

class TestM3FamilyNormalization:
    def test_normalize_tracked_index_csi500_family(self):
        """M3: 中证500价值/成长/增强 → 中证500。"""
        for raw in ("中证500", "中证500价值", "中证500成长", "中证500增强"):
            assert MarketDataHub._normalize_tracked_index(raw) == "中证500", raw

    def test_normalize_tracked_index_hs300_family(self):
        """M3: 沪深300增强/价值 → 沪深300。"""
        assert MarketDataHub._normalize_tracked_index("沪深300") == "沪深300"
        assert MarketDataHub._normalize_tracked_index("沪深300增强") == "沪深300"
        assert MarketDataHub._normalize_tracked_index("沪深300价值") == "沪深300"

    def test_normalize_segment_csi500_family(self):
        """M3: allocation_engine._normalize_segment 家族归一化。"""
        assert _normalize_segment("中证500价值") == "中证500"
        assert _normalize_segment("中证500成长") == "中证500"
        assert _normalize_segment("中证500增强") == "中证500"
        assert _normalize_segment("中证500") == "中证500"
        assert _normalize_segment("沪深300增强") == "沪深300"

    def test_deduplicate_by_index_keeps_largest_in_family(self):
        """M3: 同一家族（中证500价值/成长/增强）去重后只保留 fund_scale 最大者。"""
        pool = {
            "core": [
                {"symbol": "510500", "name": "中证500ETF", "tracked_index": "中证500",
                 "fund_scale": 800.0},
                {"symbol": "562330", "name": "中证500价值ETF", "tracked_index": "中证500价值",
                 "fund_scale": 120.0},
                {"symbol": "562340", "name": "中证500成长ETF", "tracked_index": "中证500成长",
                 "fund_scale": 100.0},
                {"symbol": "563030", "name": "中证500增强ETF", "tracked_index": "中证500增强",
                 "fund_scale": 90.0},
            ],
            "satellite": [],
            "defense": [],
        }
        result = MarketDataHub._deduplicate_by_index(pool)
        core_syms = {e["symbol"] for e in result["core"]}
        assert "510500" in core_syms, "规模最大的 510500 必须保留"
        assert not ({"562330", "562340", "563030"} & core_syms), \
            "中证500 家族切片不得同时出现 ≥2 只（伪分散）"
        assert len(core_syms) == 1, "同一家族只保留 1 只"

    def test_deduplicate_by_index_keeps_other_indices(self):
        """M3: 归一化不影响非家族指数（沪深300/中证A500 各自保留）。"""
        pool = {
            "core": [
                {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300",
                 "fund_scale": 900.0},
                {"symbol": "560600", "name": "中证A500ETF", "tracked_index": "中证A500",
                 "fund_scale": 550.0},
            ],
            "satellite": [],
            "defense": [],
        }
        result = MarketDataHub._deduplicate_by_index(pool)
        core_syms = {e["symbol"] for e in result["core"]}
        assert core_syms == {"510300", "560600"}


# ── M1: full_pipeline 集成（mock 数据源）────────────────────────

class TestFullPipelineM1:
    def test_full_pipeline_injects_a500_and_dividend(self, monkeypatch):
        """M1: full_pipeline 候选池必须包含 A500/红利（静态兜底注入生效）。"""

        def _fake_fetch_all():
            # 全市场扫描只有迷你 ETF（会被 filter_etfs 过滤掉）→ 走静态兜底注入
            return [{"代码": "999999", "名称": "迷你债ETF", "最新价": 1.0, "涨跌幅": 0.0,
                     "成交额": 5e5, "成交量": 1000, "换手率": 0.1,
                     "流通市值": 0.5, "总市值": 0.5}]

        monkeypatch.setattr("app.fetchers.etf_scanner.fetch_all_etfs_base", _fake_fetch_all)
        layers = full_pipeline()
        core_syms = {e["symbol"] for e in layers["core"]}
        assert "560600" in core_syms, "560600 必须出现在 core 候选池"
        assert "512890" in core_syms, "512890 红利低波必须出现在 core 候选池"
        assert "515080" in core_syms, "515080 中证红利必须出现在 core 候选池"
        # CORE_REQUIRED 全部命中（M2 无 WARNING 的前提）
        for req in CORE_REQUIRED:
            assert req in core_syms, f"required {req} 必须命中"
