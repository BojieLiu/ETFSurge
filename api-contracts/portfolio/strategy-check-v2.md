# API 契约: 策略检查覆盖率规则兜底 (Z26)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z26
> 变更类型: 既有端点行为修订（LLM 超时/部分覆盖时规则引擎兜底 + 覆盖校验补齐 + 超时预算修正）
> 版本: v2.0

## 1. 概述 / Overview

**功能描述**: 修复策略检查（`/portfolio/strategy-check`）覆盖率依赖 LLM 响应稳定性的问题。引入规则引擎兜底，确保持仓 100% 覆盖；修正超时预算（126s→120s 对齐）；LLM prompt 硬约束 action 枚举为 `increase/decrease/hold`。

**触发场景**: 用户点击"策略检查"按钮，后台异步任务分析组合持仓并生成建议。

---

## 2. 端点定义 / Endpoints

### 2.1 发起策略检查 / Trigger Strategy Check

```
POST /api/v1/portfolio/strategy-check-async
```

#### 请求体 / Request Body

```json
{
  "capital": 500000,
  "portfolio_type": "on_exchange"
}
```

#### 成功响应 / Success Response — `202 Accepted`

```json
{
  "task_id": 123,
  "status": "pending",
  "message": "策略检查任务已创建"
}
```

---

### 2.2 获取策略检查任务状态 / Get Strategy Check Task

```
GET /api/v1/portfolio/tasks/{task_id}
```

#### 成功响应 / Success Response — `200 OK`

```json
{
  "task_id": 123,
  "task_type": "check",
  "status": "completed",
  "progress": 100,
  "stage": "分析完成",
  "result": {
    "summary": "组合整体偏进攻，建议增配防御资产",
    "market_regime": "range_bound",
    "suggestions": [
      {
        "symbol": "510300",
        "name": "沪深300ETF",
        "action": "increase",
        "current_weight": 0.15,
        "suggested_weight": 0.18,
        "reason": "核心宽基配置偏低，当前估值处于低位区间",
        "confidence": 0.85,
        "source": "rule"  // 新增：rule | llm
      }
    ],
    "holdings_analysis": [...],
    "risk_warnings": [...],
    "report_text": "完整报告文本...",
    "data_quality": {
      "filled_count": 8,
      "total_count": 10,
      "factor_coverage": 0.8
    },
    "coverage": {
      "total_holdings": 10,
      "covered_by_llm": 6,
      "covered_by_rule": 4,
      "coverage_pct": 1.0
    }
  },
  "record_id": 456,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:31:30Z"
}
```

#### 关键字段契约 / Key Field Contract (Z26)

| Field | Type | Description |
|-------|------|-------------|
| result.suggestions[].action | string | **必须为** `increase` \| `decrease` \| `hold`（与策略检查契约对齐，禁止 `BUY/SELL/HOLD`） |
| result.suggestions[].current_weight | number | 当前权重（0-1） |
| result.suggestions[].suggested_weight | number | 建议权重（0-1） |
| result.suggestions[].source | string | `rule`（规则引擎）\| `llm`（大模型） |
| result.suggestions[].confidence | number | 置信度 0-1，规则引擎输出默认 0.7 |
| result.coverage | object | **新增** 覆盖率统计，确保 100% |
| result.coverage.coverage_pct | number | 必须为 1.0（100%） |

---

### 2.3 策略检查历史记录 / Strategy Check History

```
GET /api/v1/portfolio/strategy-checks
```

#### 成功响应 / Success Response — `200 OK`

```json
{
  "items": [
    {
      "id": 456,
      "capital": 500000,
      "summary": "组合整体偏进攻...",
      "market_regime": "range_bound",
      "suggestions_json": "[...]",
      "holdings_json": "[...]",
      "risk_warnings_json": "[...]",
      "report_text": "完整报告...",
      "created_at": "2024-01-15T10:31:30Z"
    }
  ],
  "total": 1
}
```

---

## 3. 行为契约 / Behavioral Contract (Z26)

### 3.1 规则引擎兜底逻辑

**位置**: `backend/app/services/portfolio_service.py` → `strategy_check()` 内部，LLM 调用之后、结果持久化之前。

**触发条件**:
- LLM 调用超时（`asyncio.wait_for` 20s）
- LLM 返回结果为空/解析失败
- LLM 返回的 `suggestions` 覆盖持仓 < 100%

**兜底流程**:
1. 对每个持仓标的，若 LLLM 未给出建议，规则引擎基于以下指标生成：
   - **factor_score** 综合因子分（z-score 归一化后）
   - **technical_signal** 技术信号（`signal.signal` ∈ `buy/sell/hold`）
   - **weight_drift** 目标权重偏离度
   - **market_regime** 当前市场状态（`bull/bear/range_bound/defensive`）
2. **决策规则表**:

| 条件 | action | suggested_weight 调整 | reason 模板 |
|------|--------|----------------------|-------------|
| factor_score > 0.5 AND signal=buy AND regime!=bear | increase | `min(current * 1.2, max_weight)` | "因子评分优+技术买入信号，建议增仓" |
| factor_score < -0.5 AND signal=sell | decrease | `max(current * 0.7, min_weight)` | "因子评分弱+技术卖出信号，建议减仓" |
| weight_drift > 0.05 | decrease | `target_weight` | "权重偏离目标超 5%，建议回调至目标权重" |
| weight_drift < -0.05 | increase | `target_weight` | "权重低于目标超 5%，建议补仓至目标权重" |
| 其余 | hold | `current_weight` | "维持现状" |

3. **confidence**: 规则引擎输出固定 0.7；LLM 输出保留原值（默认 0.8）。
4. **去重**: 同一 symbol 只保留一条建议（LLM 优先，规则兜底补充）。

### 3.2 覆盖率校验补齐

- 统计 `total_holdings` = 持仓标的数（排除 CASH）
- 统计 `covered_by_llm` = LLM 返回建议覆盖的标的数
- 统计 `covered_by_rule` = 规则引擎补齐的标的数
- `coverage_pct = (covered_by_llm + covered_by_rule) / total_holdings` **必须 = 1.0**
- 若 < 1.0，记 ERROR 日志，仍返回结果但标记异常。

### 3.3 超时预算修正

| 环节 | 原预算 | 新预算 | 说明 |
|------|--------|--------|------|
| 数据采集 (indicators + factors) | 30s | 30s | 保持 |
| 策略检查核心逻辑 | - | 30s | 新增显式预算 |
| LLM 报告生成 | 120s (外层) | 20s (内层) + 规则兜底 | 原 126s 总超时拆分 |
| DB 持久化 | - | 10s | 新增 |
| **总计** | **~126s** | **≤ 90s** | **留 30s buffer 给 TaskManager 外层 120s** |

### 3.4 LLM Prompt 硬约束

`backend/app/analysis/llm.py` → `generate_strategy_check_report()` prompt 中：
- action **必须**为 `increase`/`decrease`/`hold`（小写，与契约一致）
- 必须输出 `current_weight`、`suggested_weight`（0-1 小数）
- 输出 JSON 格式，字段名与契约完全一致

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| suggestions[].action 仅为 increase/decrease/hold | ☐ | ☐ | 契约硬约束 |
| suggestions[] 含 current_weight/suggested_weight | ☐ | ☐ | 规则引擎必须输出 |
| suggestions[].source 字段区分 rule/llm | ☐ | ☐ | 前端可展示来源 |
| coverage.coverage_pct = 1.0 | ☐ | ☐ | 100% 覆盖强制 |
| 任务总耗时 ≤ 90s (预留 30s buffer) | N/A | ☐ | 超时预算修正 |
| LLM 超时/失败时规则兜底生效 | N/A | ☐ | 单测 mock 验证 |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_z26_strategy_check_coverage.py`（mock LLM 超时/部分覆盖/正常）
- verify_e2e: `section_portfolio` 策略检查链路断言 coverage_pct=1.0