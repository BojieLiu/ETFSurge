# Internal Module Contract: `app.services.portfolio` package

> 内部模块结构契约（非 HTTP API）——`docs/code-health-coverage-and-giant-file-split.md` 方案 B
> Step 1-2 的落地声明。HTTP API 契约不变（`api-contracts/portfolio/*` 无需改动）。
>
> **性质**：本契约约束**模块级符号面**（import path + 导出符号 + 行为等价），不约束 HTTP 路由。

## 1. 目标结构 / Target Structure

```
app/services/portfolio_service.py        ← 门面 re-export（Step 1-2 保留；Step 3 删除）
app/services/portfolio/
    __init__.py                          ← re-export 全部原符号（兼容层）
    _facade_refs.py                      ← 跨簇延迟代理（保留 mock.patch 语义）
    crud.py                              ← list_etfs/add_etf/update_etf/remove_etf/_resolve_tracked_index/_recompute_target_weight
    pricing.py                           ← build_price_map/_build_price_map_async/_get_etf_attr/_split_symbols/_fetch_realtime_price/_clear_price_map_cache + _PRICE_MAP_CACHE/_PRICE_MAP_TTL/_FUNDAMENTALS_CACHE
    allocation.py                        ← calculate_allocation/recompute_cost_after_trade/calculate_weight_drift
    pnl.py                               ← calculate_daily_pnl/calculate_cumulative_pnl
    strategy_check.py                    ← strategy_check + 全部 _rule_*/_factor_*/_compute_* 辅助 + _strategy_check_cache/_COMPOSITE_FACTOR_MAP
    design.py                            ← apply_portfolio_design
    transfer.py                          ← export_portfolio/import_portfolio
    formatting.py                        ← _factor_hint/_factor_strength_band/format_factor_summary/_factor_value_real/_has_real_factor_values/_normalize_confidence/_compute_confidence + FACTOR_LABELS/_RSI_HINT/_KDJ_HINT/_CONFIDENCE_ZH
```

## 2. 契约规则 / Contract Rules

### R1 符号面（Symbol Surface）

对以下每个符号，**必须同时**满足：

- 可从 `app.services.portfolio_service`（旧路径，Step 1-2 期间）导入；
- 可从 `app.services.portfolio.<子模块>`（新路径）导入；
- 二者解析到**行为等价**的可调用对象/常量（纯函数 `recompute_cost_after_trade` 输出一致）。

符号全集：`FACTOR_LABELS, _RSI_HINT, _KDJ_HINT, _CONFIDENCE_ZH, _PRICE_MAP_CACHE,
_PRICE_MAP_TTL, _FUNDAMENTALS_CACHE, _strategy_check_cache, _COMPOSITE_FACTOR_MAP,
_factor_hint, _factor_strength_band, format_factor_summary, _factor_value_real,
_has_real_factor_values, _normalize_confidence, _compute_confidence, build_price_map,
_build_price_map_async, _get_etf_attr, _split_symbols, _fetch_realtime_price,
_clear_price_map_cache, list_etfs, add_etf, update_etf, remove_etf,
_resolve_tracked_index, _recompute_target_weight, calculate_allocation,
recompute_cost_after_trade, calculate_weight_drift, calculate_daily_pnl,
calculate_cumulative_pnl, strategy_check, _is_failed_result, _build_llm_fail_summary,
_llm_timeout_for, _collect_strategy_data, _empty_portfolio_diagnosis,
_attach_composite_decisions, _cross_sectional_factor_composite,
_within_symbol_factor_composite, _full_pool_factor_composite,
_build_rule_fallback_holdings_analysis, _rule_based_suggestion,
_build_rule_fallback_report, _combine_risk_warnings, _compute_risk_warnings,
_compute_indicators, apply_portfolio_design, export_portfolio, import_portfolio`

### R2 跨簇引用（Cross-Cluster References）

- 跨簇函数依赖必须经由 `_facade_refs` 延迟代理解析——保证
  `unittest.mock.patch("app.services.portfolio_service.<name>")` 仍能拦截调用点。
- 共享可变状态（`_PRICE_MAP_CACHE`/`_FUNDAMENTALS_CACHE`）留在 `pricing.py`，
  `allocation.py` 直接 import 同一对象（禁止复制）。

### R3 行为零变化（Zero Behavior Change）

- 拆分只搬方法体 + 调整相对导入深度（`from ..` → `from ...`），不改断言/分支/日志文案。
- 公共函数签名（含参数名/默认值）逐字符不变。

### R4 死代码处理（Step 1）

- `_detect_regime`（无调用点）、`PORTFOLIO_TYPES`（无引用）随拆分删除，不 re-export。
- `_cross_sectional_factor_composite` 保留 re-export（测试直测，Step 3 再决策）。

## 3. 验证 / Verification

- `backend/tests/test_portfolio_module_structure.py`：结构断言（新旧路径符号存在 + 行为等价抽查）。
- 全量 `pytest`（2149 基线）不降 + `verify_e2e.py` 全 PASS。

## 4. 退出标准 / Exit Criteria (Step 3)

- `rg "from app.services.portfolio_service import"`（生产+测试）0 残留后删除 facade re-export 与 `_facade_refs`。
- 测试 patch 目标迁移到新子模块路径（`app.services.portfolio.pnl.list_etfs` 等）。
