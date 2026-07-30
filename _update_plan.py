"""Update implementation-master-plan.md with v31.0 section."""
with open("docs/implementation-master-plan.md", "r", encoding="utf-8") as f:
    content = f.read()

old_marker = "| | **v30.0** | 2026-07-31 | **Phase 30 — v5 诊断方案实施：契约驱动 + TDD 修复6项问题** | 详见下方 |"

new_section = """| | **v31.0** | 2026-07-31 | **Phase 30b — v5 诊断方案剩余项：TaskManager/策略检查/板块轮动** | 详见下方 |
| | | | | **来源：** `docs/v5_diagnostic_and_optimization_plan.md` |
| | | | | **Z27 — TaskManager persist path 修复 (P1)：** `DEFAULT_PERSIST_PATH` 原为 `app/tasks/../data/tasks.json` → `backend/app/data/tasks.json`（不存在的目录）。**修复：** 改为 `../../data/tasks.json` → `backend/data/tasks.json`。 |
| | | | | **Z26 — 策略检查建议覆盖全 (P2)：** `generate_strategy_check_report` LLM prompt 仅有 `max_suggestions` 上限，LLM 倾向于跳过无因子数据的标的，建议数不足。**修复：** 新增 `min_suggestions = max(3, holdings_count // 2)` 下限 + prompt 中改为"建议条数范围: {min}~{max} 条（下限{min}条，必须覆盖每个持仓标的至少一条建议）"。 |
| | | | | **Z17 — 板块轮动 422 (P2)：** `/api/v1/market/sectors` 路由中 `type` 参数为 `Query(...)`（必需），前端未传参时返回 422。**修复：** `type` 改为 `Query("industry")`（默认值）；新增 `/sectors/rotation` 路由暴露 `fetch_sector_industry_cls`；前端 `api/index.js` 新增 `getSectorRotation()`。 |
| | | | | **Z25 — 热门个股 API 丰富 (P2)：** 前端 `marketApi` 新增 `getSectorRotation` 接口。 |
| | | | | **新增单测：** `tests/test_v5_diagnosis_fixes.py` 扩至 **14 用例全 PASS**：新增 Z27×4(persist path / create-get / list / update)、Z26×1(function signature)、Z17×1(fetch_sector_industry_cls callable)、Z25×1(stock_hot_rank callable)。 |
| | | | | **改动文件：** `backend/app/tasks/task_manager.py`（Z27）、`backend/app/analysis/llm.py`（Z26）、`backend/app/routers/market.py`（Z17）、`frontend/src/api/index.js`（Z17/Z25）、`backend/tests/test_v5_diagnosis_fixes.py`（扩至14用例）、`docs/implementation-master-plan.md`（本版本更新） |

"""

if old_marker in content:
    # Update the old marker to v30a and insert v31 before it
    updated_marker = old_marker.replace("Phase 30", "Phase 30a")
    content = content.replace(old_marker, new_section + updated_marker)
    print("SUCCESS: Replaced marker")
else:
    print("WARNING: Marker not found!")
    # Find any marker with v30.0
    for i, line in enumerate(content.split("\n")):
        if "v30.0" in line or "Phase 30" in line:
            print(f"  Line {i}: {line[:120]}")

with open("docs/implementation-master-plan.md", "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
