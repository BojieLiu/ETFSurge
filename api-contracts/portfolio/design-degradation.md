# API 契约: 非交易时段降级契约 (Z11)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z11
> 变更类型: 内部实现契约化（统一静态池 + fallback 元数据 + 降级形态契约），`/portfolio/design-async` 响应含降级标识
> 版本: v1.0

## 1. 概述 / Overview

**功能描述**: 统一非交易时段/数据管道断裂时的降级行为。定义静态兜底池、fallback 元数据、降级形态契约，确保 `/portfolio/design-async` 始终返回三套方案且前端可感知降级状态。

**触发场景**: 
- 非交易时段（因子矩阵为空、候选池为空）
- 数据源异常导致 `get_factor_matrix`/`get_pool` 失败
- 验证前端降级态显示

---

## 2. 端点定义 / Endpoint

### 2.1 生成增强型组合设计 / Generate Enhanced Portfolio Design (响应增强)

```
POST /api/v1/portfolio/design-async
```

#### 响应增强字段 / Enhanced Response Fields (Z11)

```json
{
  "strategies": [...],
  "generated_at": "2026-07-31T15:00:00Z",
  "market_context": {...},
  "degradation": {
    "mode": "static_pool",
    "reason": "非交易时段：因子矩阵为空，使用静态核心池兜底",
    "factor_matrix_empty": true,
    "pool_empty": true,
    "static_pool_used": ["510300", "510050", "518880", "511010", "159915", "588000"],
    "timestamp": "2026-07-31T15:00:00Z"
  }
}
```

#### degradation 字段契约 / Degradation Field Contract

| Field | Type | Description |
|-------|------|-------------|
| mode | string | `normal` \| `static_pool` \| `partial_data` —— 降级模式 |
| reason | string | 人类可读的降级原因 |
| factor_matrix_empty | boolean | 因子矩阵是否为空 |
| pool_empty | boolean | 候选池是否为空 |
| static_pool_used | array[string] | 实际使用的静态池代码列表 |
| timestamp | string (ISO8601) | 降级判定时间 |

#### 降级模式定义 / Degradation Modes

| mode | 触发条件 | 行为 |
|------|----------|------|
| `normal` | 因子矩阵非空 + 候选池非空 | 正常全量流程 |
| `static_pool` | `total_candidates == 0`（候选池空） | 使用静态核心池（6 只：沪深300/上证50/黄金/国债/创业板/科创50）按层预算分配 |
| `partial_data` | 因子矩阵部分为空/异常但候选池非空 | 可用因子计算分数，缺失因子按 0 填充，正常分配器跑通 |
| `degraded` | **round28 R59②**：数据采集超时（`DESIGN_DATA_TIMEOUT`）后以 `skip_refresh=True` 降级重试——跳过 `refresh()` 撞慢源，用内存 last-good / T-1 快照 / 静态池产出方案 | 返回可用方案（非 failed）；`reason` 标注「盘后数据源冷却/采集超时，使用最近缓存快照」；`pool_degraded=true`。**禁止**用「方案生成超时」空响应掩盖数据源冷却 |

> **round28 R59⑤**：非交易时段 + 已有 last-good 池时，`generate_enhanced_design` 主动跳过实时 `refresh()`（不尝试实时源干等超时）——`degradation.mode` 保持 `normal`/`partial_data`，但 `pool_degraded=true`（池为最近缓存快照），前端据此提示「数据源冷却」。唯一例外：池为空（首启）才尝试 `refresh()`（内部有 T-1 快照兜底）。

---

## 3. 内部契约 / Internal Contracts

### 3.1 静态兜底池 / Static Fallback Pool

**位置**: `backend/app/services/strategy_design.py` 模块级常量

```python
STATIC_CORE_POOL = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core"},
    {"symbol": "510050", "name": "上证50ETF", "layer": "core"},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense"},
    {"symbol": "511010", "name": "国债ETF", "layer": "defense"},
    {"symbol": "159915", "name": "创业板ETF", "layer": "satellite"},
    {"symbol": "588000", "name": "科创50ETF", "layer": "satellite"},
]
```

**层预算引用**: `STRATEGY_META.layer_budget`（core=0.5, satellite=0.3, defense=0.2），**不再硬编码 0.4/0.35/0.25**。

### 3.2 Fallback 元数据 / Fallback Metadata

每个静态池条目附带最小元数据（供分配器/理由生成使用）：
```python
{
    "symbol": "510300",
    "name": "沪深300ETF",
    "layer": "core",
    "factor_score": 0.5,      # 中性默认
    "trend_1m": 0.0,
    "trend_3m": 0.0,
    "fund_flow_20d": 0,
    "market_cap": 1e10,       # 量级估值
}
```

### 3.3 降级形态契约 / Degradation Shape Contract

无论何种降级模式，**响应结构必须保持一致**：
- `strategies` 长度 = 3（防御/均衡/进攻）
- 每个 strategy 含 `etfs` 数组（按层预算分配，可能为空）
- `risk_metrics` 正常计算（基于实际分配结果）
- `degradation` 字段**始终存在**（normal 模式下 `mode="normal"`，其余字段可选）

---

## 4. 行为契约 / Behavioral Contract (Z11)

1. **统一入口**: `generate_enhanced_design()` 内部，`get_factor_matrix`/`get_pool` 调用包裹 `try/except`，失败时 `factor_matrix = {}`、`pool = []` 而非抛错。
2. **候选池空判定**: `total_candidates == 0` → 触发 `static_pool` 模式。
3. **静态池分层分配**: 遍历 `STATIC_CORE_POOL`，按 `layer` 归入 core/satellite/defense，再按 `STRATEGY_META.layer_budget[layer]` 等权分配（每层内等权）。
4. **因子矩阵部分缺失**: `factor_matrix` 非空但部分 symbol 缺失因子分 → 缺失项补 0，正常走分配器（`partial_data` 模式）。
5. **前端感知**: 前端读取 `degradation.mode`，非 `normal` 时显示"当前为非交易时段/数据受限，方案基于静态核心池生成"提示。

---

## 5. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 响应含 degradation 字段 | ☐ | ☐ | 始终存在 |
| degradation.mode 枚举正确 | ☐ | ☐ | normal/static_pool/partial_data |
| static_pool 模式下 strategies 仍为 3 套 | ☐ | ☐ | 核心验收 |
| 静态池引用 STRATEGY_META.layer_budget | N/A | ☐ | 不硬编码权重 |
| 前端非 normal 模式显示降级提示 | ☐ | N/A | UX 要求 |
| 单测覆盖 static_pool/partial_data 两模式 | N/A | ☐ | mock 验证 |

---

## 6. 测试 / Tests

- 后端单测: `backend/tests/test_z11_degradation.py`（mock factor_matrix={}/pool=[] 验证 static_pool 模式；mock 部分因子缺失验证 partial_data 模式）
- verify_e2e: `section_portfolio` design-async 断言 degradation 字段存在