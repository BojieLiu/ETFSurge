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
| `id` | int | Design ID |
| `_type` | string | Always `"design"` |
| `created_at` | string | ISO 8601 timestamp |
| `status` | string | Task status: `"completed"`, `"failed"`, `"running"` |
| `capital` | float | Portfolio capital |
| `error_message` | string |null | Error details if failed |

### Item fields (check type)
| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Check record ID |
| `_type` | string | Always `"check"` |
| `created_at` | string | ISO 8601 timestamp |
| `status` | string | Task status |
| `summary` | string | Check result summary |
| `error_message` | string |null | Error details if failed |

## Implementation Notes

- Queries both `portfolio_designs` and `strategy_check_records` tables
- Merged and sorted by `created_at` DESC
- Pagination applied after merge sort
- `total` equals the sum of both table record counts (unfiltered)
- Running tasks are NOT included here (the frontend `taskStore` adds them locally)

## Frontend-Backend Checklist

- [ ] Backend: `GET /timeline` route added to `routers/portfolio.py`
- [ ] Backend: Queries both tables, merges, sorts, paginates
- [ ] Frontend: `portfolioApi.getTimeline(limit, offset)` method added
- [ ] Frontend: `DashboardAiTools.vue` uses single timeline call instead of two parallel calls
