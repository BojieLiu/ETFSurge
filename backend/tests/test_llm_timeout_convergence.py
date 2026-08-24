from __future__ import annotations
"""
round35 §19 GapE: LLM 超时常量单点收敛钉定测试。

收敛前：connect/write/pool 四元组字面量散落 reports.py 两处（策略检查 90s /
设计报告 120s read 各自硬编码），provider 级默认超时硬编码 config.py。
收敛后：唯一事实源 = app/core/llm_timeouts.py，本文件防止漂移回潮。
"""

import inspect

from app.config import settings
from app.core.llm_timeouts import (
    DESIGN_REPORT_READ_S,
    LLM_HTTP_CONNECT_S,
    LLM_HTTP_POOL_S,
    LLM_HTTP_WRITE_S,
    LLM_PROVIDER_FALLBACK_TIMEOUT_S,
    LLM_PROVIDER_PRIMARY_TIMEOUT_S,
    STRATEGY_CHECK_READ_S,
    llm_http_timeout,
)


class TestHelperValues:
    def test_helper_produces_converged_timeout(self):
        t = llm_http_timeout(STRATEGY_CHECK_READ_S)
        assert t.connect == LLM_HTTP_CONNECT_S == 60.0
        assert t.read == 90.0
        assert t.write == LLM_HTTP_WRITE_S == 15.0
        assert t.pool == LLM_HTTP_POOL_S == 15.0

    def test_design_report_budget(self):
        t = llm_http_timeout(DESIGN_REPORT_READ_S)
        assert t.read == 120.0


class TestConfigSingleSource:
    def test_provider_default_timeouts_reference_constants(self):
        """settings 类默认值必须等于常量（env 可覆盖运行值，但单源不破）。"""
        fields = type(settings).model_fields
        assert fields["llm_primary_timeout"].default == LLM_PROVIDER_PRIMARY_TIMEOUT_S == 20
        assert fields["llm_fallback_timeout"].default == LLM_PROVIDER_FALLBACK_TIMEOUT_S == 45


class TestReportsLiteralElimination:
    def test_reports_no_bare_httpx_timeout_literals(self):
        """reports.py 不得再出现 httpx.Timeout(connect=60.0...) 字面量（防漂移）。"""
        from app.analysis.llm import reports as reports_mod

        src = inspect.getsource(reports_mod)
        assert "httpx.Timeout(connect=60.0" not in src, (
            "超时常量已收敛至 core/llm_timeouts.py，reports.py 不得回潮硬编码"
        )
        assert "llm_http_timeout" in src
