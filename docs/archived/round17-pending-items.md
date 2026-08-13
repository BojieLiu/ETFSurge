# Round17 待排期项方案（2026-08-12）— P2-6/P2-8 体验项 + 性能债 + P3-6 基线

> **性质**：round16 实施（commit fab74d1）后遗留待排期项的**方案设计文档**——本份只设计不实施。
> **来源**：round16-container-acceptance-diagnosis.md §7 P2-6/P2-8 + 实施后新增实测（watchlist 冷态 7.3s、LLM 120s+、预热 57.3s、test 文件 212>197）。
> **状态**：3 轮 review 达标后进入实施（对照 docs/design-checklist.md 8 项）。
> **验证窗口**：涉及外部行情源项标注「交易日 9:30-11:30/13:00-15:00 + 真实环境」；非窗口结论打标「待复测」。

---

## 一、待排期项清单与优先级

| # | 项 | 来源 | 级别 | 性质 |
|---|---|---|---|---|
| P2-6 | 两套信号口径 UI 区分（技术信号 vs 因子综合信号） | round16 §3.6 ⚠️ | P2 | 体验 |
| P2-8 | 数据源冷却告警（degraded 标记前端消费 + 报告降级标注） | round16 §7 P2-8 | P2 | 体验/诚实性 |
| P1-2 | watchlist 冷态 7.3s（首拉预热覆盖） | round16 §2.3 + 实施后复测 | P1 | 性能债 |
| LLM-1 | design-async LLM 排队 120s+（超时分级） | 实施后实测（verify_e2e） | P1 | 性能债 |
| 预热 | warmup 57.3s（数据源冷却 vs 真实回退判别） | 实施后实测 | P2 | 复测确认 |
| P3-6 | test 文件 212>197 基线反弹 | pre-commit 门禁提示 | P2 | 治理 |

**实施顺序建议**：P2-6 → P2-8（低风险体验，前端为主）→ P1-2（性能，与 P2-8 后端联动）→ LLM-1（独立）→ 预热（复测先行，可能无改动）→ P3-6（收尾治理）。

---

## 二、P2-6 两套信号口径 UI 区分

### 证据链

- `/market/signal/{symbol}`（`market.py:366-393`）返回**技术信号** `{signal: buy/hold/sell, score, reasons}`（K 线指标 compute_all_indicators + generate_signal）；
- `SignalPanel.vue:14` 标题**「🎯 综合信号」**展示该技术信号——命名与语义不符（用户以为"综合"含因子/基本面）；
- 设计报告 `strategies[].etfs[].factor_score`（`strategy_design.py` 注入，P0-4 已透传到 get_design）是**因子综合分**（可为 -0.17 等连续值）；
- 实测矛盾（round16 §3.6）：510300 技术信号 buy、因子综合信号 -0.17 中性——两套口径并存，UI 未区分。

### 修复方案

1. **SignalPanel 标题与口径标注**（最小改动）：标题「🎯 综合信号」→「📈 技术信号」，副标题注明「基于 K 线技术指标（RSI/KDJ/MACD/MA），不含因子与基本面」；`signal.reasons` 已有技术依据，无需扩展。
2. **TechnicalAnalysisModal 同步修正**（review 2 发现）：`TechnicalAnalysisModal.vue:17` 的「综合信号」标签同为技术信号误称（弹窗嵌入 SectorHeatMap + WatchlistPanel 自选技术分析）——同改为「技术信号」，与 SignalPanel 口径一致。
3. **设计报告 plans 补因子分展示**（可选增强）：`DesignResult.vue` 持仓表加「因子分」列（数据已由 P0-4 透传 `factor_score`，`portfolio.py:291` 确认），列头 tooltip 注明「因子综合分（区别于技术信号）」——两处并存、语义可区分（DesignResult 与 SignalPanel 分属不同页面）。
4. **测试补强**：**新建** `SignalPanel.spec.js`（R4 review 提示：实施前确认前端 test 目录现状，当前未见既有 spec）加「标题=技术信号非综合信号」断言（负向：标题含"综合信号" → FAIL）；**新建** `DesignResult.spec.js`（当前仅见 DesignResult.p2vw.spec.js，实施前同样确认）加「因子分列存在且 tooltip 注明口径」断言；`TechnicalAnalysisModal` 相关既有 spec（`AnalysisView.p0-15.spec.js` 已源码级读文件）加「标签=技术信号」断言；**改名时同步清理** `TechnicalAnalysisModal.vue:15/:199` 注释与 `SectorHeatMap.spec.js:237` 用例名中的「综合信号」残留（该用例名本身含「综合信号」，若断言涉及文案需同步改断言；文档以「清理用例名」指令覆盖此场景）。

### 验收

- 技术分析页标题显示「技术信号」且口径说明清晰（SignalPanel + TechnicalAnalysisModal 两处一致）；
- 设计详情持仓表可见因子分（与信号面板技术信号并存、语义可区分）；
- 负向断言通过（标题误称"综合信号" → FAIL）。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ SignalPanel 现读 | ✅ market.py:366 + SignalPanel.vue:14 | —（无外部源） | ✅ 因子分已透传 | ✅ 前端渲染 | —（信号四态已具） | —（无新 IO） | ✅ ① |

---

## 三、P2-8 数据源冷却告警（degraded 标记前端消费）

### 证据链

- 后端已有 degraded 标记源：
  - `sectors/heat` 端点（`market.py:615-623`）：`nonzero_ratio < 0.5` 时返回 `degraded: true`（P0-17 已落地）；
  - 候选池 `market_data_hub._degraded`（P0-13）+ `strategy_design._degradation()["pool_degraded"]`（P0-13 已落地）；
- `/admin/sources/health`（`admin.py:53-76`）已返回各源 `available/cooldown_remaining/failures`；前端 `SourceMonitor.vue` 已消费（数据源页）；
- **缺口**：`degraded` 标记**前端 0 处消费**（rg 确认 frontend/src 无 degraded 引用）——报告/页面数据降级时用户无感知。

### 修复方案

1. **报告降级标注**（后端+前端）：
   - **持久化 degradation**（后端前置）：`task_manager.py:302` 现只取 `result["market_context"]`，`generate_enhanced_design` 的顶层 `degradation` 未持久化 → 在 `task_manager.py:350/403` 写 `market_snapshot_json` 前并入 `degradation`（`market_context["degradation"] = result.get("degradation")`），使**历史设计可查**（非仅新设计）；
   - `DesignResult.vue`：读 design 响应的 `degradation` → 顶部黄色提示条「⚠️ 数据源冷却，部分标的为降级数据」（含 `mode/pool_degraded` 细节）；
   - `get_design`（`portfolio.py:249-314`）返回体补 `degradation` 字段（从 `market_snapshot_json` 读出，读点在 `:297`）。
2. **板块热度降级提示**（前端）：`SectorHeatMap.vue` 读 `sectors/heat` 响应 `degraded`（P0-17 已返回）→ 顶部提示「⚠️ 部分板块涨跌幅数据源冷却（非零率 <50%）」。
3. **自选慢数据已有占位**（P1-6 已见）：`WatchlistPanel.vue` 行情加载中已有「loading-text」占位——本项不做重复。
4. **测试补强**：**新建** `DesignResult.spec.js`（当前仅见 DesignResult.p2vw.spec.js，实施前确认前端 test 目录现状）加「degradation 存在时显示冷却提示」断言（负向：degraded 无提示 → FAIL）；`SectorHeatMap.spec.js`（既有）加「heat 响应 degraded=true 显示提示」断言；后端 `test_design_pipeline_integration.py` 加「degradation 持久化到 market_snapshot_json」断言。

### 验收

- 数据源冷却时：设计详情/板块热度页显式提示（非静默）；
- 正常时无提示（不误报）——**负向断言**：`degraded=false` / 无 `degradation` 字段时提示条不渲染 → FAIL；
- **已实证**：`task_manager.py:302` 仅取 market_context、degradation 顶层未持久化——方案含持久化步骤，历史设计可查（非仅新设计）；
- 负向断言通过（含第 2 条新增）。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 已实证未持久化 | ✅ market.py:615 + tm:302 | ✅ 冷却期复测 | ✅ 显式降级标注 | ✅ DesignResult/SectorHeatMap | ✅ 提示条四态兼容 | ✅ 持久化一次写 | ✅ ④ |

---

## 四、P1-2 watchlist 冷态 7.3s（首拉预热覆盖）

### 证据链

- 实施后复测：`GET /api/v1/market/watchlist` 冷/热态均 ~7.3s（本地非交易时段）；
- P1-7 已并行化三市场批量（`market.py:714-728` `asyncio.gather`）——**批量不再串行**，但冷缓存首拉仍全量触网；
- `_PORTFOLIO_REALTIME_TTL = 15`（`market_service.py:1013`）应用级缓存——热态应 <500ms，但复测仍 7.3s 说明**首拉路径未命中缓存**（可能因 data 源冷却 + per-item 兜底叠加）；
- 预热 `_warmup_market_cache`（`main.py:197`）调 `refresh_market_cache()` → `get_portfolio_realtime()`（`market_refresh.py:17`）——**预热已覆盖 watchlist 常用标的**，但 10s 超时（`main.py:201`）在数据源冷却时可能未完成。

### 修复方案（需先探针确认首拉慢在哪个环节）

1. **探针**（D1 前置）：本地启动后 `time curl /api/v1/market/watchlist` 连续 3 次 + 后端日志查批量/per-item 耗时分布——确认慢在「批量 4s×N」「per-item 兜底」「resolve_symbol_to_code」哪一环。
2. **按探针结果选择**：
   - 若批量慢（数据源冷却）→ **冷态降级加速**：`_batch_for` 超时 4s→2s，冷却期快速降级 DB-only（`_degraded` 标记），不等满 4s；
   - 若 per-item 兜底慢 → 冷却期**跳过 per-item**（A 股缺失直接 DB-only，round9 P0-4 已做，确认 HK/US 同策略）；
   - 若 resolve 慢 → 缓存 symbol 归一化映射。
3. **verify_perf 阈值已含**（`verify_perf.py:26` watchlist ≤3s）——实施后本地验证达 ≤3s（非交易时段冷却期允许 degraded 快速返回而非 7.3s 卡死）。
4. **测试补强**：`test_watchlist_perf.py` 加「冷却期批量 2s 超时快速降级」断言（负向：冷却期仍等满 4s → FAIL）。

### 验收

- 冷态 watchlist ≤3s（或冷却期 degraded 快速返回 <3s，不 7.3s 卡死）；
- verify_perf watchlist 阈值 PASS（本地实测记录到提交说明）；
- 负向断言通过。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 前置探针（§四.1） | ✅ market.py:724（gather）+ _batch_for :701 + ms:1013 | ✅ 交易时段复测 | ✅ DB-only 显式降级 | ✅ watchlist 路由 | ✅ loading 占位已有 | ✅ 超时分级+缓存 | ✅ ③ |

---

## 五、LLM-1 design-async LLM 排队 120s+（超时分级）

### 证据链

- verify_e2e 实测：design-async 120s 内未完成（LLM 阶段排队）；
- 预算现状：`task_manager.py:442` `wait_for(generate_design_report, 240)` + `design_report.py:512` 内层 240s + provider timeout 240s 三层对齐（`task_manager.py:433-434` 注释）；
- 策略检查预算：`_llm_timeout_for`（`portfolio_service.py:604-619`）完整档 75s（P2-5 复核一致）；
- **缺口**：design 链路无「排队超时分级」（>45s warn、>90s 降级规则）——用户等待期间无进度反馈升级。

### 修复方案

1. **进度反馈分级**（前端为主）：design 任务 progress 卡 80%「LLM 报告生成中」超过 60s → 提示「LLM 排队中，可能需要更长时间（免费模型高峰 90s+）」；超过 150s → 提示「已接近超时，将降级为方案表格（无 LLM 分析）」——对照 `_notify` progress 推送（`task_manager.py` 已有 stage 推送）。
2. **后端降级分级**（可选，谨慎）：`generate_design_report` 外层 240s 保持（P0-1 已确保超时→partial 非 full 假数据），**不缩减预算**（过紧预算必然 partial，见 `task_manager.py:434` 注释）；仅补充「>150s 时日志 WARN + usage 标记」供监控。
3. **测试补强**：前端 `DashboardAiTools` 加「progress 80% 超 60s 显示排队提示」断言（负向：无提示 → FAIL）。

### 验收

- 用户等待 LLM 报告 >60s 时看到排队提示（非静默 240s 无反馈）；
- 超时降级仍 quality=partial（P0-1 回归不破坏）；
- 负向断言通过。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ verify_e2e 实测 | ✅ tm:442 + dr:512 | ✅ 高峰排队复测 | ✅ 超时→partial | ✅ DashboardAiTools | ✅ 排队提示四态 | ✅ 不改预算 | ✅ ③ |

---

## 六、预热 57.3s（复测确认项）

### 证据链

- 实施后启动实测：`Warmup took 57.3s (threshold 30s)`——超 30s 阈值（日志位 `main.py:526`）；
- round16 诊断（2026-08-11 交易日）：预热 7.6s 达标（≤25s 门禁）——**差异主因是本次非交易时段数据源冷却**（akshare/东财慢）；
- `main.py:197-201` `_warmup_market_cache` → `wait_for(refresh_market_cache(), timeout=10)`、global_indices 预热——预热本身有超时保护，超时仅降级不阻塞启动。

### 修复方案

1. **复测确认**（D3）：交易时段（9:30-15:00）重启后端，记录 warmup 耗时——若回到 ≤25s 则本项**关闭**（非问题，仅数据源冷却）；
2. 若仍 >30s → 分段优化（`fetch_macro_snapshot` 串行→并发或 24h 缓存，round16 §7 P1-5 方向）——**待复测后决定**，本份不预设改动；
3. 记录到提交说明/台账（软门禁性质）。

### 验收

- 交易时段复测记录 warmup 耗时；
- >30s 时产出分段瓶颈证据链（非静默），≤25s 时标注「冷却期现象，非代码问题」。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| ✅ 复测为探针 | ✅ main.py:197-201/526 | ✅ 交易时段 D3 | —（不适用：无新功能输出） | —（不适用） | —（不适用） | —（不适用） | —（不适用：复测项） |

---

## 七、P3-6 test 文件 212>197 基线反弹

### 证据链

- `check_test_baseline.py:21` `BASELINE = 197`；实测 `backend/tests/test_*.py` = **212**（前端 `*.spec.js` 不计入基线，BASELINE 仅统计后端 test 文件）；
- **基线早已超**（非本轮引入）：round16 实施前 commit `11f9433` 已 208 个（超 11 个）；round16 实施新增后端专项文件 `test_p020_indices_meta.py` / `test_p022_us_index_search.py` / `test_p023_amount_override.py` / `test_p29_contract_bias.py`（4 个，非文档此前误述的 10 个——前端 spec 不计基线）→ 208 + 4 = 212；
- 门禁性质：`check_test_baseline.py:42` 超基线时 `return 1`（脚本自身 FAIL），但 `.githooks/pre-commit:386-397` 把该脚本调用包在 `if ...; then ... else 提示不阻断` 中降级为提示（治理约定③）——212>197 现状已存在且 round16 实施（commit fab74d1）已成功提交佐证。

### 修复方案

1. **后端专项文件合并**（回退本轮新增 4 个）——
   - `test_p020_indices_meta.py` + `test_p022_us_index_search.py` → `test_search_sector_index.py`（指数搜索同域）；
   - `test_p023_amount_override.py` → `test_etf_scanner.py`（filter_etfs 同域）；
   - `test_p29_contract_bias.py` → **拆分并入** `test_analysis_contract.py` 与 `test_portfolio_list.py`（B1 入 analysis、B2/B6 入 portfolio——权威来源 round16 §3.9/P2-9；B6 为前端源码断言，并入 portfolio_list 时用分区注释标注来源防误删）——两目标均为既有文件，拆分不产生新文件。
   → 212 - 4 = **208**，仍 > 197；
2. **既有文件审视**（target 197 需再减 11）：对照 `backend/scripts/check_test_baseline.py` 注释（round11 226→197 是 7 组合并成果），从既有 208 个中识别可合并的同类小文件（如单用例文件并入主主题文件）——**需实施前审计清单**（不预设具体文件，避免空断言）；
3. 合并后仍 >197 → **conscious review 后调整 BASELINE**（`check_test_baseline.py:20` 注释「Bump ONLY via conscious review」）——调整时在脚本注释记录理由与计数。

### 验收

- 本轮新增 4 个后端专项文件**全部并入既有文件**（不回退为独立文件）→ 212 → **208**；
- 产出「既有文件可合并审计清单」（target 197 需再减 11）或 conscious review 后 bump BASELINE（记录理由）；pre-commit P3-6 提示消除或降级为 bump 记录；
- 全量测试仍绿（合并不丢用例）。

### design-checklist 对照

| 1探针 | 2证据 | 3窗口 | 4非兜底 | 5调用 | 6四态 | 7复杂度 | 8模式 |
|---|---|---|---|---|---|---|---|
| —（不适用：治理项） | ✅ check_test_baseline.py:20-21 + git 计数 208→212 | —（不适用） | —（不适用：无功能输出） | —（不适用） | —（不适用） | —（不适用） | —（不适用：治理/组织） |

---

## 八、实施顺序与验收口径

1. **P2-6**（SignalPanel 标题 + DesignResult 因子分列）：前端单测 2 项 + 回归；
2. **P2-8**（degraded 提示）：持久化 degradation（task_manager 350/403 前并入）→ `get_design` 透传 → 前端提示条 + 单测 2 项；
3. **P1-2**（watchlist 冷态）：探针定位慢环节 → 超时分级/降级加速 → verify_perf 阈值验证；
4. **LLM-1**（排队提示）：前端单测 1 项；
5. **预热**：交易时段复测记录（可能无改动）；
6. **P3-6**：测试文件合并 + 全量复跑。

> **每项 DoD**：测试绿 + 现实证真（真实调用点/非兜底数据/内容断言）+ design-checklist 8 项对照（已附各节）+ 性能记录（涉及热点路径项）。

---

## 附：已知但本轮不实施（避免范围膨胀）

- P1-3（A 股 LLM 链路 77.8s）：上下文采集并行化——涉及 LLM 链路重构，风险高于收益，单独轮次；
- P1-4（home Lighthouse 55）：前端性能优化，需 Lighthouse 复测基线，单独轮次；
- 候选池卫星层多样性（round16 P0-13③ 非阻塞）：引擎层调整，单独轮次。
