"""Tests for Phase 2b - Policy Factors (P1.2c) + mypy fixes (P1.6)."""
from __future__ import annotations

import ast
import os
import subprocess

import pytest

# Project paths from tests/
APP_DIR = os.path.join(os.path.dirname(__file__), "..", "app")


# ---- P1.2c: Policy Factors ----


class TestP1_2c_PolicyFactors:
    """P1.2c: Policy factor compute functions + mappings."""

    def test_five_year_plan_function_exists(self):
        path = os.path.join(APP_DIR, "factors", "factor_registry.py")
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_five_year_plan":
                    return
        pytest.fail("_compute_five_year_plan not found")

    def test_strategic_emerging_function_exists(self):
        path = os.path.join(APP_DIR, "factors", "factor_registry.py")
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_strategic_emerging":
                    return
        pytest.fail("_compute_strategic_emerging not found")

    def test_dual_circulation_function_exists(self):
        path = os.path.join(APP_DIR, "factors", "factor_registry.py")
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "_compute_dual_circulation":
                    return
        pytest.fail("_compute_dual_circulation not found")

    def test_policy_alignment_mapping_exists(self):
        path = os.path.join(APP_DIR, "factors", "factor_registry.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_POLICY_ALIGNMENT" in content
        for key in ["半导体", "计算机", "国防军工", "医药生物"]:
            assert key in content, f"_POLICY_ALIGNMENT missing key: {key}"

    def test_policy_factors_registered_in_builtin_computers(self):
        path = os.path.join(APP_DIR, "factors", "factor_registry.py")
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = {"five_year_plan": False, "strategic_emerging": False, "dual_circulation": False}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key_node in node.keys:
                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        if "five_year_plan" in key_node.value:
                            found["five_year_plan"] = True
                        elif "strategic_emerging" in key_node.value:
                            found["strategic_emerging"] = True
                        elif "dual_circulation" in key_node.value:
                            found["dual_circulation"] = True
        for name, found_flag in found.items():
            assert found_flag, f"Policy factor '{name}' not registered in _BUILTIN_COMPUTERS"

    def test_five_year_plan_returns_correct_score(self):
        from app.factors.factor_registry import _compute_five_year_plan
        assert _compute_five_year_plan({"industry": "半导体"}) == 0.95
        assert _compute_five_year_plan({"industry": "银行"}) == 0.25
        assert _compute_five_year_plan({"industry": "未知行业"}) == 0.30

    def test_strategic_emerging_matches(self):
        from app.factors.factor_registry import _compute_strategic_emerging
        assert _compute_strategic_emerging({"industry": "半导体"}) == 1.0
        assert _compute_strategic_emerging({"industry": "银行"}) == 0.0

    def test_dual_circulation_matches_industry(self):
        from app.factors.factor_registry import _compute_dual_circulation
        assert _compute_dual_circulation({"industry": "食品饮料"}) == 1.0
        assert _compute_dual_circulation({"industry": "银行"}) == 0.0

    def test_dual_circulation_matches_concepts(self):
        from app.factors.factor_registry import _compute_dual_circulation
        assert _compute_dual_circulation({"industry": "其他", "concepts": ["消费升级", "内需驱动"]}) == 1.0
        assert _compute_dual_circulation({"industry": "其他", "concepts": ["数字货币"]}) == 0.0

    def test_policy_factors_have_yaml_definitions(self):
        path = os.path.join(APP_DIR, "factors", "factor_definitions.yaml")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "china.policy.five_year_plan" in content
        assert "china.policy.strategic_emerging" in content
        assert "china.policy.dual_circulation" in content


# ---- P1.6: mypy type errors ----


class TestP1_6_MyPyTypeErrors:
    """P1.6: mypy errors should be zero."""

    def test_mypy_errors_zero(self):
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        result = subprocess.run(
            ["python", "-m", "mypy", "app/", "--ignore-missing-imports"],
            capture_output=True, text=True, cwd=backend_dir,
        )
        errors = [line for line in result.stdout.split("\n") if "error:" in line]
        assert len(errors) == 0, f"mypy errors:\n" + "\n".join(errors)

    def test_mypy_ini_no_unused_sections(self):
        ini_path = os.path.join(os.path.dirname(__file__), "..", ".mypy.ini")
        with open(ini_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "scripts" not in content, ".mypy.ini should not have [mypy-scripts.*]"

    def test_market_router_delegates_to_hub(self):
        path = os.path.join(APP_DIR, "services", "market_router.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # v6 Phase 3/5: market_router delegates US/HK fetches to MarketDataHub
        assert "from app.fetchers import global_markets_fetcher" not in content
        assert "market_data_hub.get_us_stock_realtime" in content
        assert "market_data_hub.get_hk_stock_realtime" in content
        assert 'type: ignore[attr-defined]' not in content

    def test_market_router_no_stooq_fetcher(self):
        path = os.path.join(APP_DIR, "services", "market_router.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Only check import/function call references, not comments
        lines = [l for l in content.split(chr(10)) if "stooq" in l.lower() and "API closed" not in l and "# Stooq" not in l]
        assert len(lines) == 0, f"stooq code references remain: {lines[:3]}"
