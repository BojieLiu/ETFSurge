"""LLM integration package — split from analysis/llm.py (Batch 2).

Sub-modules by responsibility:

- prompts.py: prompt loading (``load_prompt`` / ``SYSTEM_PROMPT``) + leak filtering
- gates.py: circuit breaker / quota gate / error diagnostics
- cache.py: report result cache
- client.py: ``llm_complete`` / ``llm_complete_stream`` / ``llm_complete_with_system``
- health.py: ``llm_health_check`` / global liquidity fetch
- news.py: news summary / news impact analysis
- reports.py: the ``generate_*`` report builders

This ``__init__`` re-exports every symbol that historically lived on the single
``app.analysis.llm`` module so existing imports keep working unchanged. Module-level
dependencies (``time`` / ``asyncio`` / ``token_store`` / ``get_agent`` /
``get_configured_providers`` / ``has_any_api_key``) are also bound here so tests that
``mock.patch("app.analysis.llm.<dep>")`` keep resolving the same objects.
"""

import asyncio
import hashlib
import json
import sys
import threading
import time
from typing import Any, AsyncGenerator

from app.analysis.provider import ProviderConfig, get_configured_providers, has_any_api_key
from app.analysis.registry import get_agent
from app.config import settings
from app.core.logging import get_logger
from app.monitor.token_usage import UsageRecord, token_store

logger = get_logger(__name__)

from app.analysis.llm.cache import (
    _REPORT_CACHE,
    _REPORT_CACHE_LOCK,
    _REPORT_CACHE_TTL,
    _report_cache_key,
    get_cached_report,
    put_cached_report,
)
from app.analysis.llm.client import (
    _LLM_RATE_LIMIT_CAP,
    LLM_MAX_RETRIES,
    LLM_RETRY_DELAY,
    _check_key,
    _rate_limit_wait,
    llm_complete,
    llm_complete_stream,
    llm_complete_with_system,
    run_stream_with_cache,
)
from app.analysis.llm.gates import (
    _CIRCUIT_FAIL_THRESHOLD,
    _CIRCUIT_TTL,
    LLMQuotaGate,
    _circuit,
    _circuit_allow,
    _circuit_record_failure,
    _circuit_record_success,
    _circuit_state,
    _clear_llm_error,
    _last_llm_error,
    _record_llm_error,
    get_last_llm_error,
    llm_quota_gate,
    reset_circuit,
)
from app.analysis.llm.health import _fetch_global_liquidity, llm_health_check
from app.analysis.llm.news import _news_body_text, analyze_news_impact, generate_news_summary
from app.analysis.llm.prompts import (
    _LEAK_PATTERNS,
    _PROMPT_DIR,
    SYSTEM_PROMPT,
    load_prompt,
    strip_internal_leak,
)
from app.analysis.llm.reports import (
    _build_advice_stream_prompt,
    _build_design_report_prompt,
    _build_engine_fallback,
    _build_factor_breakdown_table,
    _build_market_overview,
    _build_report_prompt,
    _empty_portfolio_response,
    _format_commodities,
    _format_indices,
    generate_advice,
    generate_design_report,
    generate_market_report,
    generate_sector_analysis,
    generate_strategy_check_report,
    generate_strategy_suggestions,
    generate_symbol_analysis,
)

__all__ = [
    # patch surface —— docstring 所述：绑定到包命名空间供 mock.patch("app.analysis.llm.<dep>") 使用
    "asyncio",
    "hashlib",
    "json",
    "sys",
    "threading",
    "time",
    "Any",
    "AsyncGenerator",
    "ProviderConfig",
    "get_configured_providers",
    "has_any_api_key",
    "get_agent",
    "settings",
    "UsageRecord",
    "token_store",
    # state / constants
    "LLM_MAX_RETRIES",
    "LLM_RETRY_DELAY",
    "_LLM_RATE_LIMIT_CAP",
    "_last_llm_error",
    "_CIRCUIT_TTL",
    "_CIRCUIT_FAIL_THRESHOLD",
    "_circuit",
    "_PROMPT_DIR",
    "_LEAK_PATTERNS",
    "SYSTEM_PROMPT",
    "llm_quota_gate",
    "_REPORT_CACHE_LOCK",
    "_REPORT_CACHE",
    "_REPORT_CACHE_TTL",
    # prompts
    "load_prompt",
    "strip_internal_leak",
    # gates
    "LLMQuotaGate",
    "get_last_llm_error",
    "_record_llm_error",
    "_clear_llm_error",
    "_circuit_state",
    "_circuit_allow",
    "_circuit_record_failure",
    "_circuit_record_success",
    "reset_circuit",
    # cache
    "_report_cache_key",
    "get_cached_report",
    "put_cached_report",
    # client
    "llm_complete",
    "llm_complete_stream",
    "llm_complete_with_system",
    "_check_key",
    "_rate_limit_wait",
    "run_stream_with_cache",
    # health
    "llm_health_check",
    "_fetch_global_liquidity",
    # news
    "generate_news_summary",
    "_news_body_text",
    "analyze_news_impact",
    # reports
    "_build_engine_fallback",
    "_format_indices",
    "_format_commodities",
    "_build_market_overview",
    "_build_report_prompt",
    "_empty_portfolio_response",
    "generate_market_report",
    "generate_advice",
    "generate_strategy_suggestions",
    "generate_strategy_check_report",
    "generate_sector_analysis",
    "generate_symbol_analysis",
    "generate_design_report",
    "_build_factor_breakdown_table",
    "_build_design_report_prompt",
    "_build_advice_stream_prompt",
]
