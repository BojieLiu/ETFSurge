# Internal Module Contract: `app.analysis.llm` package

> 内部模块结构契约（非 HTTP API）——`docs/code-health-coverage-and-giant-file-split.md` 方案 C
> Step 1-2 的落地声明。HTTP API 契约不变（`api-contracts/analysis/*` 无需改动）。

## 1. 目标结构 / Target Structure

```
app/analysis/llm/__init__.py          ← 门面 re-export + 模块级依赖绑定（time/asyncio/token_store/get_agent/get_configured_providers/has_any_api_key）
app/analysis/llm/client.py            ← llm_complete/llm_complete_stream/llm_complete_with_system/_check_key/_rate_limit_wait/run_stream_with_cache
app/analysis/llm/gates.py             ← LLMQuotaGate + llm_quota_gate/_circuit_*/reset_circuit/_record_llm_error/get_last_llm_error/_clear_llm_error
app/analysis/llm/cache.py             ← _REPORT_CACHE_*/_report_cache_key/get_cached_report/put_cached_report
app/analysis/llm/reports.py           ← generate_design_report/generate_strategy_check_report/generate_strategy_suggestions/generate_market_report/generate_advice/generate_sector_analysis/generate_symbol_analysis + 全部 _build_* 辅助
app/analysis/llm/news.py              ← generate_news_summary/analyze_news_impact/_news_body_text
app/analysis/llm/health.py            ← llm_health_check/_fetch_global_liquidity
app/analysis/llm/prompts.py           ← load_prompt/_PROMPT_DIR(修正 parent.parent)/SYSTEM_PROMPT/strip_internal_leak/_LEAK_PATTERNS
```

原 `app/analysis/llm.py` 删除（替换为同名包）。

## 2. 契约规则 / Contract Rules

### R1 符号面（Symbol Surface）

对 `app.analysis.llm` 的既有 import 符号（生产 8 消费方 + 32 测试文件）全部保持可导入，行为等价。
关键符号：`llm_complete / llm_complete_stream / llm_complete_with_system / _check_key /
_rate_limit_wait / run_stream_with_cache / LLMQuotaGate / llm_quota_gate / _circuit_* /
reset_circuit / get_last_llm_error / _record_llm_error / _clear_llm_error /
load_prompt / SYSTEM_PROMPT / strip_internal_leak / _REPORT_CACHE* / _report_cache_key /
get_cached_report / put_cached_report / llm_health_check / _fetch_global_liquidity /
generate_* 全部 / analyze_news_impact / _news_body_text / _build_* 全部 / LLM_MAX_RETRIES /
LLM_RETRY_DELAY / _LLM_RATE_LIMIT_CAP / ProviderConfig / get_agent / token_store / UsageRecord / settings`

### R2 模块级依赖绑定

`__init__.py` 必须绑定 `time` / `asyncio` / `token_store` / `get_agent` /
`get_configured_providers` / `has_any_api_key` —— 保证
`mock.patch("app.analysis.llm.time.monotonic")`、`patch("app.analysis.llm.token_store.record")`
等仍能拦截（time/asyncio 为全局模块对象，token_store 为单例）。

### R3 行为零变化

- 拆分只搬方法体 + 修正相对导入深度 + `_PROMPT_DIR` 路径（`parent.parent`）。
- 41 个顶层 def（函数 + LLMQuotaGate 类）与原文 byte-identical（已脚本比对）。

### R4 测试补丁目标迁移（本轮必要改动）

`_check_key` / `get_configured_providers` / `has_any_api_key` / `get_agent` / `load_prompt` /
`get_last_llm_error` 从「patch 包属性」迁移到「patch 消费子模块全局」
（`app.analysis.llm.client.*` / `app.analysis.llm.reports.*` / `app.analysis.llm.health.*`）。

### R5 死代码处理

- `settings` import（未使用）保留 re-export（模块面兼容）。
- `NEWS_IMPACT_SYSTEM_PROMPT`（0 引用）随拆分删除，不 re-export。

## 3. 验证 / Verification

- `backend/tests/test_llm_module_structure.py`：新旧符号面 + 行为等价抽查。
- 全量 pytest 不降 + `verify_e2e.py` 全 PASS + mypy 0 errors。

## 4. 退出标准 / Exit Criteria (Step 3)

- `rg "from app.analysis.llm import"`（生产+测试）迁移到子模块路径后删除 facade re-export。
- `runtime.py` / `routers/analysis.py` 等消费方改 import 新路径。
