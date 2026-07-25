## Handoff: Scaffold Factor Implementation

### Starting point
- `main` branch at commit `2e5a519`
- All 15 diagnostic/fix commits pushed
- Workspace clean (3 untracked diag files, irrelevant)

### Where to start
- `docs/scaffold-factor-resolution-plan.md` — complete analysis of 7 stub factors
- Implementation priority: P1/P2/P3 table at bottom of doc

### First fix (lowest hanging fruit)
1. `backend/app/factors/factor_registry.py` around line 150-160:
   - `_compute_amount_stability`: change `data.get("amount", [])` → `data.get("volume", [])`
   - This is a 1-line fix, removes 1 factor from known_scaffolds

### Known constraints
- `test_core_factors_no_scaffold` in `test_data_health.py` will FAIL if you fix a factor
  but forget to remove it from `known_scaffolds` set
- `fund_etf_fund_info_em` akshare API is blocked by proxy — don't depend on it
- `test_integration_pipeline.py` takes ~25s (teardown HTTP leak not fully eliminated)
- `test_pool_manager.py` all 11 pass in ~8-16s

### Files to edit
- Primary: `backend/app/factors/factor_registry.py`
- Data bridge: `backend/app/services/pool_manager.py` (step 3c for sentiment)
- Test gate: `backend/tests/test_data_health.py` (known_scaffolds set)
- Doc: `docs/scaffold-factor-resolution-plan.md` (update after each fix)

### Keep in mind
- All tests must pass before commit
- `test_core_factors_no_scaffold` is the gatekeeper — if it fails, the fix didn't work
- DQ tests (14 of them) in `test_design_optimization_plan.py` run in ~1.2s
