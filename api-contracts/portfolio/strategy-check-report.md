# Contract: Strategy Check Report Enhancement

**功能描述**: Strategy check report enhancement — add `report_text` column to strategy_check_records for LLM report storage, matching portfolio_designs schema.

**设计端点**: `GET /api/v1/portfolio/strategy-check` and `GET /api/v1/portfolio/strategy-check/{id}`

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `report_text` | string, nullable | Full LLM-generated report text (same as portfolio_designs.design_text) |

## Changes

1. Database: Add `report_text TEXT` column to `strategy_check_records` table
2. Model: Add `report_text` column to `StrategyCheckRecord` model with `to_dict()` serialization
3. Worker: Store `result.get("report_text")` in `strategy_check_worker.py` when saving to DB
4. Migration: `_migrate()` in `database.py` handles column addition

## Frontend-Backend Checklist

- [x] Backend: model StrategyCheckRecord has report_text column
- [x] Backend: migration adds report_text if missing
- [x] Backend: worker stores report_text in DB record
- [x] Backend: to_dict() serializes report_text
