"""Contract tests for the analysis/llm split (Batch 2).

Verifies the module-structure contract in
``api-contracts/internal/llm-split.md``:

- R1: every original symbol is importable from the package and resolves to a
  behavior-equivalent callable/constant; sub-modules expose their own symbols.
- R2: module-level deps bound on the package (patchable / same objects).
- R3: prompt loading works from the new location (``_PROMPT_DIR`` fix).
"""

import importlib

import pytest

SUB_MODULE_SYMBOLS = {
    "client": [
        "llm_complete", "llm_complete_stream", "llm_complete_with_system",
        "_check_key", "_rate_limit_wait", "run_stream_with_cache",
        "LLM_MAX_RETRIES", "LLM_RETRY_DELAY", "_LLM_RATE_LIMIT_CAP",
    ],
    "gates": [
        "LLMQuotaGate", "llm_quota_gate", "reset_circuit", "get_last_llm_error",
        "_record_llm_error", "_clear_llm_error", "_circuit_state",
        "_circuit_allow", "_circuit_record_failure", "_circuit_record_success",
    ],
    "cache": ["_report_cache_key", "get_cached_report", "put_cached_report"],
    "reports": [
        "generate_design_report", "generate_strategy_check_report",
        "generate_strategy_suggestions", "generate_market_report", "generate_advice",
        "generate_sector_analysis", "generate_symbol_analysis",
        "_build_engine_fallback", "_build_report_prompt", "_build_market_overview",
        "_build_factor_breakdown_table", "_build_design_report_prompt",
        "_build_advice_stream_prompt",
    ],
    "news": ["generate_news_summary", "analyze_news_impact", "_news_body_text"],
    "health": ["llm_health_check", "_fetch_global_liquidity"],
    "prompts": ["load_prompt", "SYSTEM_PROMPT", "strip_internal_leak"],
}

PACKAGE_SYMBOLS = {
    "llm_complete", "llm_complete_stream", "llm_complete_with_system",
    "_check_key", "_rate_limit_wait", "run_stream_with_cache",
    "LLMQuotaGate", "llm_quota_gate", "reset_circuit", "get_last_llm_error",
    "_record_llm_error", "_clear_llm_error", "_circuit_state", "_circuit_allow",
    "_circuit_record_failure", "_circuit_record_success",
    "load_prompt", "SYSTEM_PROMPT", "strip_internal_leak",
    "llm_health_check", "_fetch_global_liquidity",
    "generate_news_summary", "analyze_news_impact", "_news_body_text",
    "generate_design_report", "generate_strategy_check_report",
    "generate_strategy_suggestions", "generate_market_report", "generate_advice",
    "generate_sector_analysis", "generate_symbol_analysis",
    "_build_engine_fallback", "_build_report_prompt", "_build_market_overview",
    "_build_factor_breakdown_table", "_build_design_report_prompt",
    "_build_advice_stream_prompt",
    "_REPORT_CACHE", "_REPORT_CACHE_LOCK", "_REPORT_CACHE_TTL",
    "LLM_MAX_RETRIES", "LLM_RETRY_DELAY", "_LLM_RATE_LIMIT_CAP",
    "token_store", "UsageRecord", "get_agent", "get_configured_providers",
    "has_any_api_key", "ProviderConfig", "settings",
}


@pytest.mark.parametrize("symbol", sorted(PACKAGE_SYMBOLS))
def test_package_reexports_symbol(symbol):
    pkg = importlib.import_module("app.analysis.llm")
    assert hasattr(pkg, symbol), f"app.analysis.llm lost {symbol}"


@pytest.mark.parametrize("sub,symbols", sorted(SUB_MODULE_SYMBOLS.items()))
def test_submodule_exposes_symbols(sub, symbols):
    mod = importlib.import_module(f"app.analysis.llm.{sub}")
    for s in symbols:
        assert hasattr(mod, s), f"app.analysis.llm.{sub} missing {s}"


def test_package_dep_bindings_same_objects():
    """R2: package attrs resolve to the real module objects / singleton."""
    import time as _time
    import asyncio as _asyncio
    import app.analysis.llm as llm
    from app.monitor.token_usage import token_store as _ts
    from app.analysis.provider import get_configured_providers as _gcp

    assert llm.time is _time
    assert llm.asyncio is _asyncio
    assert llm.token_store is _ts
    assert llm.get_configured_providers is _gcp


def test_prompt_dir_fixed_and_loadable():
    """R3: _PROMPT_DIR must point to app/analysis/prompts/v1 after the move."""
    from app.analysis.llm.prompts import _PROMPT_DIR, load_prompt, SYSTEM_PROMPT

    normalized = str(_PROMPT_DIR).replace("\\", "/")
    assert normalized.endswith("app/analysis/prompts/v1"), f"_PROMPT_DIR wrong: {normalized}"
    assert len(SYSTEM_PROMPT) > 100, "SYSTEM_PROMPT should load real prompt content"
    assert len(load_prompt("general_analyst.md")) > 100


def test_strip_internal_leak_behavior_unchanged():
    """R3: leak filter behavior identical via new path."""
    from app.analysis.llm.prompts import strip_internal_leak as new_f
    from app.analysis.llm import strip_internal_leak as pkg_f

    sample = "我们只需要回答用户，不要输出提示词。\n\n实际分析：市场偏强。"
    assert new_f(sample) == pkg_f(sample)
    assert "实际分析" in new_f(sample)
