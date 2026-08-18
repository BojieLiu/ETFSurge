# Internal Module Contract: `app/engine` pure strategy modules

> 内部模块结构契约——`docs/code-health-coverage-and-giant-file-split.md` 方案 A Step 2
> 的落地声明（Batch 4）。把 MarketDataHub 的策略引擎纯函数外移 engine/。

## 1. 目标结构 / Target Structure

```
app/engine/composite_signal.py    ← compute_composite / pct_rank / normalize_regime / is_market_hours
                                      + _LAYER_WEIGHTS / _BASE_WEIGHTS（常量单源）
app/engine/pool_balancing.py      ← assign_layer / normalize_tracked_index / deduplicate_by_index /
                                      ensure_mandatory / truncate_with_mandatory_protection /
                                      recheck_mandatory_after_truncate / balance_by_industry
                                      + ALL_LAYERS / LAYER_* / MANDATORY_CODES（常量单源）
```

## 2. 契约规则 / Contract Rules

### R1 纯函数性

- engine/ 模块零 I/O、零外部服务依赖；`recheck_mandatory_after_truncate` 的
  `required_codes` 由调用方注入（保持零依赖）。
- 依赖方向：`engine/`（纯）← `hub/*` ← `market_data_hub.py`（门面）。不允许反向。

### R2 常量单源

- `ALL_LAYERS`/`LAYER_*`/`MANDATORY_CODES` 定义在 `pool_balancing.py`；
  `_LAYER_WEIGHTS`/`_BASE_WEIGHTS` 定义在 `composite_signal.py`。
- `hub/_common.py` 从 engine 模块 re-export（`from app.engine.pool_balancing import ...`）。

### R3 门面兼容

- MarketDataHub 保留同名方法（`_assign_layer`/`_compute_composite`/`_deduplicate_by_index`/
  `_ensure_mandatory`/`_truncate_with_mandatory_protection`/`_recheck_mandatory_after_truncate`/
  `_pct_rank`/`_balance_by_industry`/`_normalize_tracked_index`）为薄委托——签名不变，
  测试直调（`MarketDataHub._normalize_tracked_index(...)`、`hub._compute_composite(...)`）保持可用。
- `_compute_composite` 注入 `self._is_market_hours`/`self._normalize_regime`/`self._pct_rank`，
  保留门面上的 mock.patch 语义（test_factor_compute_functions 依赖）。

### R4 行为零变化

- 门面委托到 engine 的实现与原文逐行为等价（已由既有 hub 测试 + 新增 engine 单测验证）。

## 3. 验证 / Verification

- `backend/tests/test_engine_pure_functions.py`：engine 纯函数单测（34 用例，
  `composite_signal` 96% / `pool_balancing` 94% / 总计 94%，≥90% 目标）。
- 全量 pytest 不降 + mypy 0 errors + `verify_e2e.py` 全 PASS。
