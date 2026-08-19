"""patrol.py 编排脚本单测（docs/patrol-orchestration-plan.md §6 Step 3）。

原则（§6 Step 3 + AGENTS.md 反假完成）：
- mock subprocess，断言档位判定 / 退出码聚合 / 报告结构，**不跑真实 subprocess**；
- 覆盖 §6 Step 2 验收用例（纯文档 / 仅测试 / untracked 新测试 / router 映射 /
  共享层全量 / 后端离线 SKIP / --module 显式覆盖）；
- 负向断言：后端离线不得误报硬失败（须 SKIP + 退出码 2）、SKIP 必须带 reason。
"""
import pytest

from scripts import patrol


# ── §4.2 档位判定 ───────────────────────────────────────────────

class TestClassifyChanges:
    def test_docs_only_is_pure_doc(self):
        """只改 docs/diag → 不触发任何层（档 4）。"""
        r = patrol.classify_changes(["docs/patrol-orchestration-plan.md", "diag/foo.txt"])
        assert r["tiers"] == set()
        assert r["logic_files"] == []
        assert r["test_files"] == []
        assert r["frontend"] is False

    def test_test_only_is_tier2(self):
        """仅改 backend/tests/*.py → 档 2（不触发全量 / e2e）。"""
        r = patrol.classify_changes(["backend/tests/test_x.py"])
        assert 2 in r["tiers"]
        assert 0 not in r["tiers"] and 1 not in r["tiers"]
        assert r["test_files"] == ["backend/tests/test_x.py"]

    def test_conftest_is_tier0(self):
        r = patrol.classify_changes(["backend/tests/conftest.py"])
        assert 0 in r["tiers"]

    def test_market_router_is_tier1_plus_routes(self):
        r = patrol.classify_changes(["backend/app/routers/market.py"])
        assert 1 in r["tiers"]
        assert "1r" in r["tiers"]
        assert "1e" not in r["tiers"]

    def test_engine_is_tier1_plus_purity(self):
        r = patrol.classify_changes(["backend/app/engine/allocation_engine.py"])
        assert 1 in r["tiers"]
        assert "1e" in r["tiers"]

    def test_frontend_is_tier3(self):
        r = patrol.classify_changes(["frontend/src/App.vue"])
        assert 3 in r["tiers"]
        assert r["frontend"] is True

    def test_public_asset_not_tier3(self):
        """frontend/public/* 静态资源不触发 L5（§4.2 注）。"""
        r = patrol.classify_changes(["frontend/public/favicon.ico"])
        assert 3 not in r["tiers"]


# ── §4.3 e2e 子模块映射 ─────────────────────────────────────────

class TestSelectE2eModules:
    def test_news_router_narrow(self):
        """改 routers/news.py → 只跑 news, 5xx, encoding（非全量）。"""
        assert patrol.select_e2e_modules(["backend/app/routers/news.py"]) == [
            "5xx", "encoding", "news",
        ]

    def test_market_router_domain(self):
        """改 routers/market.py → market 域 12 模块。"""
        mods = patrol.select_e2e_modules(["backend/app/routers/market.py"])
        assert set(mods) == {
            "market", "search", "sectors", "indicator-quality", "fundamentals",
            "db-integrity", "encoding", "hk-market", "us-market", "5xx",
            "round19-boundary", "quality",
        }

    def test_hub_shared_is_full(self):
        """改 services/market_data_hub.py（表 B 共享层）→ 全量。"""
        assert patrol.select_e2e_modules(
            ["backend/app/services/market_data_hub.py"]) is None

    def test_unknown_fetcher_falls_back_full(self):
        """改 fetchers/xxx.py（兜底规则）→ 全量。"""
        assert patrol.select_e2e_modules(
            ["backend/app/fetchers/whatever.py"]) is None

    def test_scripts_change_falls_back_full(self):
        """改 scripts/verify_e2e.py 不在表 A/B → 兜底全量。"""
        assert patrol.select_e2e_modules(
            ["backend/scripts/verify_e2e.py"]) is None

    def test_explicit_module_override(self):
        """--module 显式覆盖映射。"""
        assert patrol.select_e2e_modules(
            ["backend/app/routers/market.py"], explicit_modules=["news"]) == ["news"]


# ── 层计划（模式 × 档位 × 显式覆盖） ────────────────────────────

class TestPlanLayers:
    def test_full_excludes_smoke(self):
        plan = patrol.plan_layers("full", [])
        assert set(plan["layers"]) == set(patrol.FULL_LAYERS)
        assert "L2-smoke" not in plan["layers"]

    def test_smoke_mode(self):
        plan = patrol.plan_layers("smoke", [])
        assert set(plan["layers"]) == {"L2-e2e", "L2-health"}
        assert plan["e2e_smoke"] is True

    def test_diff_docs_only_no_layers(self):
        plan = patrol.plan_layers("diff", ["docs/x.md"])
        assert plan["layers"] == []

    def test_diff_test_only_runs_subset(self):
        plan = patrol.plan_layers("diff", ["backend/tests/test_x.py"])
        assert set(plan["layers"]) == {"L1-unit"}
        assert plan["pytest_subset"] == ["tests/test_x.py"]

    def test_diff_market_router(self):
        plan = patrol.plan_layers("diff", ["backend/app/routers/market.py"])
        layers = set(plan["layers"])
        for expected in ("L1-unit", "L2-e2e", "L2-health", "L3-perf",
                         "L2-smoke", "L4-async", "L4-routes"):
            assert expected in layers, f"missing {expected}"
        assert "L4-purity" not in layers
        assert set(plan["e2e_modules"]) == {
            "market", "search", "sectors", "indicator-quality", "fundamentals",
            "db-integrity", "encoding", "hk-market", "us-market", "5xx",
            "round19-boundary", "quality",
        }

    def test_explicit_layer_overrides_tier(self):
        """--diff --layer L1-unit 只跑 L1，忽略档 1 的 e2e（§3）。"""
        plan = patrol.plan_layers("diff", ["backend/app/routers/market.py"],
                                  explicit_layers=["L1-unit"])
        assert plan["layers"] == ["L1-unit"]

    def test_explicit_module_overrides_mapping(self):
        plan = patrol.plan_layers("diff", ["backend/app/routers/market.py"],
                                  explicit_modules=["news"])
        assert plan["e2e_modules"] == ["news"]


# ── §3 退出码聚合 ───────────────────────────────────────────────

class TestComputeExitCode:
    def test_all_pass(self):
        assert patrol.compute_exit_code({"L1-unit": {"status": "PASS"}}, False) == 0

    def test_fail(self):
        assert patrol.compute_exit_code({"L1-unit": {"status": "FAIL"}}, False) == 1

    def test_warn_only_still_zero(self):
        assert patrol.compute_exit_code({"L3-perf": {"status": "WARN"}}, False) == 0

    def test_required_backend_skip(self):
        results = {"L2-e2e": {"status": "SKIP", "reason": "backend offline"}}
        assert patrol.compute_exit_code(results, True) == 2

    def test_fail_beats_incomplete(self):
        """硬门禁失败优先于巡检不完整（1 优先于 2）。"""
        results = {"L1-unit": {"status": "FAIL"},
                   "L2-e2e": {"status": "SKIP", "reason": "backend offline"}}
        assert patrol.compute_exit_code(results, True) == 1


# ── 后端离线 SKIP（§4.4，防误报硬失败） ─────────────────────────

class TestBackendSkip:
    def test_backend_dependent_layers_skip(self):
        assert patrol.backend_layer_skip_reason("L2-e2e", False) is not None
        assert patrol.backend_layer_skip_reason("L3-perf", False) is not None

    def test_non_backend_layers_do_not_skip(self):
        assert patrol.backend_layer_skip_reason("L1-unit", False) is None
        assert patrol.backend_layer_skip_reason("L2-health", False) is None

    def test_online_no_skip(self):
        assert patrol.backend_layer_skip_reason("L2-e2e", True) is None


# ── §5 报告结构（四级状态语义） ─────────────────────────────────

class TestReport:
    def test_report_structure(self):
        results = {"L1-unit": {"status": "PASS", "duration_s": 1.0, "detail": ""}}
        report = patrol.build_report("full", 42.3, 0, results,
                                     "2026-08-19T15:30:00+08:00")
        assert report["mode"] == "full"
        assert report["exit_code"] == 0
        assert report["timestamp"] == "2026-08-19T15:30:00+08:00"
        assert report["layers"]["L1-unit"]["status"] == "PASS"

    def test_report_includes_skip_layers_with_reason(self):
        results = {"L5-frontend": {"status": "SKIP",
                                   "reason": "no frontend change in --diff mode"}}
        report = patrol.build_report("diff", 1.0, 0, results, "t")
        assert report["layers"]["L5-frontend"]["reason"]

    def test_classify_perf_warn(self):
        """L3-perf 超阈值 → WARN（软门禁，不 FAIL）。"""
        assert patrol._classify("L3-perf", 0, "[WARN] watchlist 3.4s > 3.0s", "") == "WARN"

    def test_classify_perf_hard_fail(self):
        """verify_perf 硬门禁（timeline/metrics）退出 1 → FAIL。"""
        assert patrol._classify("L3-perf", 1, "[FAIL] timeline", "") == "FAIL"

    def test_classify_plain_pass_fail(self):
        assert patrol._classify("L1-unit", 0, "ok", "") == "PASS"
        assert patrol._classify("L1-unit", 1, "boom", "") == "FAIL"
