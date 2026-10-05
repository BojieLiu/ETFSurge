# Timeline Contract — Portfolio History Timeline

## Route

**GET** `/api/v1/portfolio/timeline`

## Description

Returns a merged, chronologically-sorted list of portfolio design and strategy check records. Used by the frontend to display a unified activity timeline instead of making two separate API calls.

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | int | No | 20 | Maximum number of items to return (1-100) |
| `offset` | int | No | 0 | Pagination offset |

## Response 200

```json
{
  "items": [
    {
      "id": 42,
      "_type": "design",
      "created_at": "2026-07-26T12:00:00",
      "status": "completed",
      "capital": 500000.0,
      "error_message": null
    },
    {
      "id": 7,
      "_type": "check",
      "created_at": "2026-07-25T10:30:00",
      "status": "completed",
      "summary": "策略检查已完成",
      "error_message": null
    }
  ],
  "total": 42
}
```

## Fields

### Item fields (design type)
| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Design ID (or record_id for task-sourced items) |
| `_type` | string | Always `"design"` |
| `created_at` | string | ISO 8601 timestamp |
| `status` | string | Task status: `"completed"`, `"failed"`, `"running"` |
| `capital` | float \| null | Portfolio capital (null for task-sourced items) |
| `error_message` | string \| null | Error details if failed |
| `task_id` | int \| null | **O12**: task record id for task-sourced items (retry entry) |
| `task_id` | int \| null | **round63**: 关联的 task id（design 记录有对应 task 时回带，否则 null）。前端本地去重（`AiDesign.vue` 的 `timelineTaskIds`）只认带 `task_id` 的行——design 行不带时该集合恒为空、去重恒失效，会从残留的 running store 条目合成幻影行 |

### Item fields (check type)
| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Check record ID |
| `_type` | string | Always `"check"` |
| `created_at` | string | ISO 8601 timestamp |
| `status` | string | Task status |
| `summary` | string | Check result summary |
| `error_message` | string \|null | Error details if failed |
| `task_id` | int \| null | **round63**: 同 design——关联的 task id，无关联时 null |

## Implementation Notes

- Queries both `portfolio_designs` and `strategy_check_records` tables
- **O12 (round8)**: additionally joins `tasks` table (`task_type='design'`) —
  failed / running design tasks appear with `status='failed'` + `error_message`
  + `task_id`; completed tasks that already have a design record are NOT duplicated
- **round63 去重规则（LLM 报告窗口）**：任务已 `record_id` 指向某条 design/check
  记录时**不再单独出一行，且不看任务状态**。理由：设计管线在 progress 65 就把
  `PortfolioDesign` 写成 `status='completed'`（`report_quality` 仍 `pending`），
  LLM 报告窗口内任务状态是 `quick_ready` —— 旧规则要求
  `status ∈ {completed, completed_with_errors}`，于是同一次运行同时返回
  design 行（"成功" + capital）与 task 行（"运行中"，capital 恒 null），
  前端渲染成两行，看起来像"点了两次"。
  - **例外**：`failed` 任务始终保留，否则失败会被"成功"的 design 行掩盖。
  - 前置条件：`record_id` 必须在记录落库时立即回填（design 侧 progress 75 前、
    check 侧 LLM 研判注释前），不能等到 completed —— 否则窗口内无关联可查。
- Merged and sorted by `created_at` DESC
- Pagination applied after merge sort
- `total` equals the sum of all merged records (designs + checks + design tasks)
- Running tasks are included (previously frontend `taskStore` added them locally)

## Frontend-Backend Checklist

- [x] Backend: `GET /timeline` route added to `routers/portfolio.py`
- [x] Backend: Queries both tables, merges, sorts, paginates
- [x] Backend (O12): joins `tasks` table — failed/running design tasks visible with `status`/`error_message`/`task_id`
- [x] Backend (round63): 去重规则不依赖任务终态（LLM 报告窗口内 `quick_ready` 不再重复出行）；`failed` 仍保留 — `tests/test_timeline_joins_tasks.py::TestNoDuplicateDuringLLMReportWindow` ×8
- [x] Backend (round63): `record_id` 在记录落库时立即回填（design progress 75 前 / check LLM 注释前）— `tests/test_design_pipeline_integration.py::test_record_id_persisted_before_llm_report_starts`（读测试库 tasks 列，避开 mock session 污染）
- [x] Backend (round63): design/check 行回带 `task_id`（前端本地去重依赖）— 同上 timeline 用例
- [x] Frontend (round63): task store 的 taskId 读写两端统一归一化字符串（WS 数字键 vs fetch 字符串键曾导致孪生条目 + `updateTask` 静默 no-op）— `src/test/taskStore.spec.js` ×7
- [x] Frontend (round63): `AiDesign` 把本页发起的任务置终态（WS + 轮询，幂等）— `src/test/AiDesign.spec.js` ×3
- [x] Frontend: `portfolioApi.getTimeline(limit, offset)` method added
- [x] Frontend: `DashboardAiTools.vue` uses single timeline call instead of two parallel calls
- [x] Frontend: DesignHistory renders failed items with error detail + retry entry

<!-- 路由登记（P3-5 check_routes 门禁） -->
GET /api/v1/portfolio/timeline
