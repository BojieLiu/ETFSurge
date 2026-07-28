# Contract: Report Quality Grading

**功能描述**: Report quality grading for portfolio design — 4-tier quality system replaces the previous binary "full"/"pending" classification.

**设计端点**: `GET /api/v1/portfolio/designs/{id}` and `GET /api/v1/portfolio/designs`

## Fields

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `report_quality` | string | `full` / `partial` / `empty` / `failed` / `pending` / `none` | Quality grade of the design pipeline output |
| `status` | string | `completed` / `failed` / `running` / `pending` / `completed_with_errors` | Overall pipeline execution status |

### Quality Grades

| Grade | Condition | Meaning |
|-------|-----------|---------|
| `full` | strategies have >=3 real ETFs + LLM report complete | Normal operation |
| `partial` | allocation succeeded but LLM report incomplete (timeout) | Usable scheme data, partial AI analysis |
| `empty` | allocation returned 0 real ETFs across all 3 strategies | No valid ETFs found — all cash |
| `failed` | pipeline execution error | System error |
| `pending` | pipeline still running | Waiting for completion |
| `none` | no quality assessment yet | Initial state |

### Allocation Validation Rules

1. Each strategy in strategies_json containing only CASH (no real ETF symbols) indicates empty allocation
2. If all 3 strategies have 0 real ETFs, report_quality must be empty
3. If at least one strategy has >=3 real ETFs and LLM report generated, report_quality = full
4. If allocation succeeded but LLM timed out, report_quality = partial

## Frontend-Backend Checklist

- [x] Backend: report_quality 4-tier grading in _design_pipeline_with_semaphore
- [x] Backend: empty quality when all strategies have 0 real ETFs
- [x] Backend: partial quality when LLM report times out
- [x] Backend: error_message populated with specific failure reason on empty allocation
- [x] Verify: verify_e2e.py checks strategies have real ETFs for full quality
