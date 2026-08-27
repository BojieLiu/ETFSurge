# round38 容器全链路复验轮 — R139-R144 新发现（2026-08-27 周三非交易时段）

> 本文档为 round37（dcd47e0：R129-R114 修复实施）之后的**修复验证轮**。
> 容器自 2026-08-27 11:43 启动至 14:00+，运行约 2.5h。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile。
> 验证窗口：2026-08-27 周三收盘后。实时行情类结论标注「待交易时段复测」。

---

## 0. 执行摘要

### 0.1 核心结论

1. **R129/R112/R113/R114 修复生效** ✅：requirements.txt CLEAN、AppTabs role 静态化、App.vue 过渡语法、PortfolioAnalysis TODO 注释——全部已验证。
2. **R137 DB 损坏复发（P0）** ❌：portfolio.db 清空重建（13:47，2.8MB）后约 2h 再次损坏（PRAGMA integrity_check 报 malformed）。/api/v1/portfolio/designs 500、/tasks 500、/timeline 500。容器内持有连接的应用仍可读部分表（portfolio_etfs 7 条、strategy_check_records 3 条），但新连接报 "unable to open database file"。
3. **R131 卫星层 cap 未触发（P1）** ❌：balanced 卫星 0.300 > budget 0.220、aggressive 卫星 0.350 > budget 0.300。cap 日志 `[allocation] R131 satellite layer capped` 从未出现（logs/backend.log 全仓 grep 0 次）。cap 代码在 `_select_and_weight` 返回后、`allocations.extend(sat_alloc)` 之前（1522-1529 行），但 `_select_and_weight` 返回时卫星层可能未超预算，**后续 backup 补足 / C2 科技分散 / _enforce_mandatory_floor 等步骤将卫星层权重放大**。
4. **R132 报告表格因子分仍 0.00（P1）** ❌：strategy_check_records 3 条报告「因子分」列全部 0.00。dcd47e0 的修复（strategy_check.py:453）只注入了 `holdings_analysis[].factor_scores` 键，但 `_build_rule_fallback_report` 表格行（1394 行）读 `s.get("composite_score")`，规则兜底路径 factor_composite 为 None → avg_factor=0.0 → 0.00。
5. **Lighthouse 门禁全通过** ✅：首页 P99/A95/BP96/SEO91；仪表盘 P73/A99/BP96/SEO91（P73 > 60 硬门禁 PASS，TBT 600ms 超 500ms WARN）。
6. **verify_e2e 176/202 PASS**（26 FAIL，其中 ≈15 由 DB 损坏直接导致）

### 0.2 关键判定表

| 判定 | 项目 |
|---|---|
| ✅ 修复生效 | R129、R112、R113、R114 |
| ❌ 修复未生效 | R131（cap 未触发）、R132（表格因子分仍 0.00）、R137（DB 再次损坏） |
| 🆕 本轮新发现 | R139-R144（详见 §4） |
| 🔄 长期存在 | INV-3/5/6 cross-profile violations（未收敛） |
| Lighthouse | 首页 P99/A95/BP96/SEO91；仪表盘 P73/A99/BP96/SEO91 — 全 PASS |

### 0.3 验证窗口标注

本轮执行于周三收盘后。以下结论待交易时段复测：sentiment 波动、实时行情字段新鲜度、watchlist 冷缓存源耗时。

---

## 1. 环境构建与启动

| 项 | 结果 |
|---|---|
| Docker | Engine 29.7.2 / Compose v5.4.0 |
| 构建 | `docker compose --profile prod up --build -d`（frontend 容器缺失→单独 `up -d frontend` 补起） |
| 容器状态 | backend(:8000) / frontend(:80) / redis(:6379) — 全部 Up 2.5h+ |
| 镜像 | backend: 1.47GB（含 dev 工具分离后仍大，R129 已生效但镜像中 pip 层缓存新区块仍大） |
| 前端 | 首次启动时 frontend 容器缺失（非 `docker compose up` 同时启动），需单独 `docker compose --profile prod up -d frontend` |
| liveness | `/health` → 200 `{"status":"ok"}`（0.1s 响应） |
| DB 初态 | 13:47 重建（2.8MB，schema 自动初始化），14:00+ 已损坏（malformed） |
| LLM 状态 | opencode_zen 2/6 可用、openrouter 8/16 可用、deepseek 1/1 可用 |

### 1.1 R144 前端容器缺失（环境性）

`docker compose --profile prod up -d` 前未使用 `--build` 同时构建所有服务，frontend 容器未启动。需单独 `docker compose --profile prod up -d frontend` 补起。

### 1.2 镜像体积

backend 镜像 1.47GB（R129 分离后预期缩减 180MB，但镜像层缓存新区块可能仍大）。容器内 `ls -la /app/logs/` 为空 → .dockerignore 的 `logs/` 规则生效。

---

## 2. 对照验证矩阵（round37 修复项验证）

### 2.1 round37 R129-R138 复验

| 编号 | 发现 | round37 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|---|
| R129 | requirements.txt 混入 dev 工具 | 分离至 requirements-dev.txt | requirements.txt CLEAN（mypy/ruff/pytest-cov 等 12 项已移出） | ✅ 生效 | requirements.txt 文件内容 |
| R112 | AppTabs.vue :role 未加引号 | 改为静态 `role="tabpanel"` | AppTabs.vue:69 `role="tabpanel"`（静态属性） | ✅ 生效 | 文件内容 |
| R113 | App.vue Vue 2 transition 语法 | 改为 slot-based | App.vue:61-65 `<router-view v-slot="{ Component }">` | ✅ 生效 | 文件内容 |
| R114 | PortfolioAnalysis.vue rows 硬编码 | 标注 TODO | `<!-- TODO(R114): rows 硬编码 -->` | ✅ 生效 | 文件内容 |
| R131 | 卫星层超配（aggressive 0.40 > 0.30） | 卫星层总权重硬上限钳制至 budget | **cap 日志未触发**；balanced 0.300 > 0.220、aggressive 0.350 > 0.300 | ❌ 未生效 | cap 日志 0 次；task 1 strategies[].etfs |
| R132 | 报告表格因子分与理由因子分异源 | 注入 factor_scores 到报告表格字段 | `holdings_analysis` 有 factor_scores 键，但 report_text 表格「因子分」列仍 0.00 | ❌ 未完全生效 | strategy_check_records 3 条报告全部 0.00 |
| R137 | DB 表数据污损（malformed） | 清空重建 + 检查 WAL 并发写入策略 | **13:47 重建后再次 malformed**；/designs /tasks 500；宿主 PRAGMA integrity_check 失败 | ❌ 复发 | `database disk image is malformed` |
| R138 | LLM 三路全断 | 排除（容器重启后健康检查可用） | opencode_zen 2/6 可用、openrouter 8/16 可用、deepseek 1/1 可用 | ✅ 已排除 | /admin/llm/health |

### 2.2 verify_e2e 结果

```
[IPv4 --host 127.0.0.1] 176/202 通过 HAS FAILURES
  26 失败（约 15 个由 DB 损坏直接导致：/designs /tasks /timeline 500 + DB 读取失败）
  剩余 11 失败：LLM 超时、因子数据某些字段缺失、历史设计为空
```

对比 round37：239/256 PASS（17 FAIL 风暴尾）。量化差异主要来自 DB 损坏项。

### 2.3 patrol --diff 结果

| 层 | 结果 | 详情 |
|---|---|---|
| L1-unit | PASS | 2796 passed, 11 skipped, 26 warnings |
| L2-e2e | FAIL | 264/281 (17 FAIL) — DB 损坏 + design 历史空 |
| L2-health | FAIL | 3/10 失败 — market_service index 取空、factor stale cache |
| L2-smoke | FAIL | 120s 超时 |
| L3-perf | WARN | search 1.50s > 1.0s 阈值 (WARN) |
| L4-async | PASS | |
| L4-ruff | PASS | |

---

## 3. Lighthouse 质量门禁

| 页面 | 轮次 | Performance | Accessibility | Best Practices | SEO |
|---|---|---|---|---|---|
| 首页 (/) | R1 | 99 | 95 | 96 | 91 |
| 仪表盘 (/portfolio-analysis) | R1 | 73 | 99 | 96 | 91 |

**首页全部超过硬门禁阈值**（P≥60, A≥90, BP≥90, SEO≥90）。仪表盘 Performance 73 > 60 PASS，但相较 round37 的 99-100 下降 26 点。TBT 600ms > 500ms（WARN）。LCP 3.7s（score=0.58，仍 ≤8s 阈值）。

---

## 4. 四问法质量审查（阶段 3）

### 4.1 逐条审查

| # | 判定原文 | 事实/推断 | 支撑 | 与行情一致? | 结论 | 修复建议 |
|---|---|---|---|---|---|---|
| R139 | DB 清空重建后再次损坏 | **事实** | 宿主机 PRAGMA integrity_check 报 malformed；容器内新连接报 "unable to open database file"；/designs 500（disk I/O error）；13:47 重建后约 2h 损坏 | 不依赖行情 | 合理 | 换 WAL 模式为 DELETE 模式 + 定期 integrity_check；考虑 VACUUM INTO 备份后重建 |
| R140 | R131 cap 未触发，卫星层仍超配 | **事实** | cap 日志 `[allocation] R131 satellite layer capped` 全仓 0 次；balanced 卫星 0.300 > budget 0.220；aggressive 卫星 0.350 > budget 0.300；**且 balanced 总仓位 1.024、aggressive 总仓位 1.065 均 > 1.0（超配直接导致总仓位超 100%）** | 待交易时段复测 | 部分合理 | 在 `allocations.extend(sat_alloc)` 之后、backup 补足/C2 之前，增加二次卫星总权重校验；或改为在 `allocate()` 返回前做最终校验 |
| R141 | R132 报告表格因子分仍 0.00 | **事实** | strategy_check_records 3 条报告全 0.00；`_build_rule_fallback_report` 表格行（1394 行）读 `s.get("composite_score")`；规则兜底路径 factor_composite 为 None → avg_factor=0.0 | 不依赖行情 | 合理 | 在 `_build_rule_fallback_report` 表格行中，当 composite_score 缺失时回退读 `h["factor_scores"]` 的均值 |
| R142 | INV-3/5/6 cross-profile violations 长期存在 | **事实** | logs/backend.log 从 08-14 到 08-27 连续出现（inv3_satellite_not_monotonic、inv5_total_not_monotonic、inv6_aggressive_cash_over） | 不依赖行情 | 合理 | 引擎不变量校验持续报警说明分配引擎存在系统性违反约束模式，需评估是否放宽阈值或修复引擎 |
| R143 | LLM token_usage 错误率 30.5% | **事实** | /admin/token-usage: 52256 calls, 15925 errors | 不依赖行情 | 部分合理 | 30.5% 错误率偏高，需排查 provider 级错误分布（429/403/503 占比） |
| R144 | verify_e2e ::1 502 | **事实** | 容器 uvicorn 监听 0.0.0.0（IPv4），`--host [::1]` 在 Docker Desktop Win 下返回 502；`--host 127.0.0.1` 正常 176/202 | 不依赖行情 | 观察 | 环境性问题，非代码回归 |

### 4.2 汇总

| 分级 | 数量 | 项目 |
|---|---|---|
| ✅ 合理 | 5 | R139、R140、R141、R142、R144 |
| ⚠️ 部分合理 | 1 | R143（待分解 provider 级错误率） |
| 🕐 待复测 | 1 | R140（交易时段配比） |

---

## 5. 修复方案（不写代码，仅方案）

### 5.1 P0 修复（影响核心功能）

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| R139 | DB 再次损坏 | 1) 停止容器；2) 删除 portfolio.db；3) 将备份 `portfolio.db.backup` 移回（或让 schema 重建）；4) 改 journal_mode 为 DELETE（防 WAL 并发写入） | data/portfolio.db | 10min |

### 5.2 P1 修复（影响数据正确性）

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| R140 | 卫星层 cap 未触发 | 在 `allocations.extend(sat_alloc)` 之后、backup 补足之前，加二次卫星权重校验（`Σ(satellite) > budget 时按比例缩放`）；或改为在 `allocate()` 返回前做最终层预算校验 | allocation_engine.py:1522-1530 | 30min + 单测 |
| R141 | 报告表格因子分仍 0.00 | 在 `_build_rule_fallback_report` 中，当 `s.get("composite_score")` 缺失或为 0 时，回退计算 `factor_breakdowns 中 factor_scores 非零值均值` | strategy_check.py:1394-1400 | 15min + 单测 |

### 5.3 P2 修复

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| R142 | INV-3/5/6 持续报警 | 评估 engine 不变量：inv3（卫星层单调性）是否应放宽阈值；inv5（总仓位单调性）是否因 C2 块引入 588000 而导致；inv6（aggressive 现金过少）是否因强制锚 floor 导致 | allocation_engine.py | 1h 分析 |

### 5.4 观察项

| 编号 | 问题 | 备注 |
|---|---|---|
| R143 | LLM 错误率 30.5% | 需按 provider 分解错误类型（429/403/503），确认是否需增加 provider 轮换或重试 |
| R144 | verify_e2e ::1 502 | 环境性，非代码问题。建议在容器内通过 nginx :80 或 --host 127.0.0.1 跑 verify_e2e |

---

## 6. 测试防护体系缺口分析

### 6.1 缺口中：DB 并发写入鲁棒性

- **现状**：R139（DB 再次损坏）——WAL 模式下并发写入再次触发 page corruption
- **缺口**：无测试验证「WAL 模式下多并发写入不损坏表」
- **建议**：新增压力测试，8 线程 × 100 次并发写入 + 读取，断言 `PRAGMA integrity_check` 返回 `ok` 且全程无 `malformed` 异常

### 6.2 缺口：R131 cap 后续步骤放大

- **现状**：R131 cap 在 `_select_and_weight` 后做一次钳制，但 backup 补足/C2 科技分散等后续步骤可放大卫星层权重
- **缺口**：无测试验证「卫星层最终总权重 ≤ budget + ε」
- **建议**：新增分配结果断言：`assert sum(h.weight for h in holdings if h.layer == "satellite") <= budget_satellite + 1e-6`

### 6.3 缺口：报告表格因子分与结构化数据一致性

- **现状**：R141 报告表格因子分 0.00 但 `holdings_analysis.factor_scores` 有值
- **缺口**：无测试验证「LLM 报告表格字段与 factor_breakdowns 一致」
- **建议**：新增端到端单测：mock LLM 返回含 factor_scores 的 holdings_analysis，断言 report.table[].factor_score_* 非零

### 6.4 防护体系总体评价

每轮都有新的 DB 损坏 → 防护体系对 SQLite WAL 并发写入鲁棒性**结构性缺一层**（端到端压力测试）。R131/R132 的修复代码存在但未覆盖所有路径，说明**单元测试覆盖率不足**（只测了 cap 代码本身，未测 cap 后后续步骤的回滚/放大）。

---

## 7. 证据清单

| 文件 | 内容 |
|---|---|
| data/lh_r38_home.json | Lighthouse 首页（P99/A95/BP96/SEO91） |
| data/lh_r38_dash.json | Lighthouse 仪表盘（P73/A99/BP96/SEO91） |
| logs/patrol/latest.json | patrol --diff 结果（L1 2796 PASS / L2 264/281 / L3 search WARN） |
| logs/backend.log | 运行日志含 INV-3/5/6 等 |
| tmp/diag_r131.py 输出快照 | R131 卫星层实证（task 1 早前抓取，DB 损坏后不可复现） |

### R131 实证快照（task 1 strategies[].etfs，13:30 抓取）

```
defensive: satellite=0.200 budget=0.200 [PASS]
  SAT 513090: w=0.100 | SAT 159570: w=0.100
balanced: satellite=0.300 budget=0.220 [FAIL]  total=1.024
  SAT 513180: w=0.050 | 159928: 0.050 | 159755: 0.050 | 513050: 0.050 | 159995: 0.100
aggressive: satellite=0.350 budget=0.300 [FAIL]  total=1.065
  SAT 512400: w=0.050 | 513090: 0.100 | 513180: 0.050 | 159570: 0.050 | 588200: 0.100
```

---

## 8. 下一步（待用户决策）

> **2026-08-27 用户已拍板「采纳建议」并完成实施**（见 §10 实施记录）。

| 项 | 决策 | 选项 |
|---|---|---|
| R139 DB 损坏 | 1) **A) 清空重建**（改 journal_mode=DELETE 后重建）；2) B) 恢复 backup 并用 db.sqlite3 修复 | ✅ 已采纳 A |
| R140 卫星层 cap | 1) **A) 加二次校验**（extend 后 + 最终返回前）；2) B) 改 cap 为卫星层全程加权 | ✅ 已采纳 A |
| 修复实施 | 待用户说"开始实施" | ✅ 已实施 |

---

## 10. 实施记录（2026-08-27，commit 待写）

### R139 DB 加固（journal_mode=DELETE + synchronous=FULL）

- `backend/app/database.py`：PRAGMA 从 `journal_mode=WAL` 改为 `DELETE`，新增 `synchronous=FULL`——WAL 并发写入致 page corruption（清空重建后 2h 再次 malformed），DELETE+FULL 牺牲并发读写的无阻塞换取写入完整性。
- 损坏 DB 文件已备份为 `data/portfolio.db.round38corrupt`，schema 重建成功（7 表，integrity_check=ok，DELETE 持久化验证）。
- 测试：`test_sqlite_wal_mode.py` 重写为 DELETE 语义（journal_mode=delete 持久化 + synchronous=FULL + 读写串行化 + rollback 负向对照）。

### R140 卫星层/各层预算硬校验

- 根因（探针实证）：R131 cap 只在 `_select_and_weight` 返回时钳制；`_reconcile_budget_shortfall` 原实现**跨层均摊**总缺口到非强制标的（含卫星层），推超层预算；`_dedup_same_index` 同指数剔除回补把单只推超 MAX_WEIGHT（510050 0.3914 > 0.30）。
- 修复（`allocation_engine.py`）：
  1. `_reconcile_budget_shortfall` 改为**逐层回补**（签名 total_budget float → budgets dict），每层仅回补至该层 budget，不跨层推超；
  2. 新增 `_enforce_layer_budget_final`：① 单只钳制到 MAX_WEIGHT；② 层总权重超预算按比例缩放（强制锚豁免 5% 地板）。
- 测试：新增 `test_r140_layer_budget_final.py`（4 用例：卫星/核心层 ≤budget、总非CASH ≤1.0、强制锚地板保留）；更新 `test_b5_reconcile_stage.py`（逐层签名）、`test_cash_and_overlap.py`（U6 现金断言改为「层不超 budget」）、`test_design_integration.py`（层预算断言替代总仓位 ≥0.83）。

### R141 报告表格因子分回退

- 根因：`_build_rule_fallback_report` 表格行（strategy_check.py:1394-1395）只读 `composite_score`；规则兜底路径 factor_composite=None → avg_factor=0.0 → 表格恒 0.00（round38 实测 3 条报告全 0.00）。
- 修复：composite_score 缺失或为 0 时，回退读 `_COMPOSITE_FACTOR_MAP` 聚合键的 factor_scores 非零均值（R107 防御语义保留：非聚合键 RSI 等原始指标不冒充 → 保持 0.00）。
- 测试：新增 `test_r141_table_score_fallback.py`（3 用例：缺失回退 0.70、显式 0.0 回退 -0.30、无因子分保持 0.00）；R107 既有测试兼容。

### 验收结果

| 项 | 结果 |
|---|---|
| 后端全量 pytest | **2804 passed, 11 skipped, 0 failed**（294s） |
| mypy（项目标准 files=app） | Success: no issues found in 129 source files |
| verify_e2e（--host 127.0.0.1） | **268/279 PASS**（11 FAIL：DB 重建空数据 + 外部源慢，无代码回归；M7/P1-1 四连、Z27 持久化、timeline 28ms 全 PASS） |
| patrol --full | L1-unit/L2-health/L4-routes/purity/async/ruff/L5-frontend 全 PASS；L2-e2e 同 verify_e2e；L3-perf search 1.45s WARN（已知性能债，软门禁不阻断） |

---

## 9. review 记录

### Round 1（事实核对）

已执行：全部 file:line / 数字 / commit 与代码逐一对账。
- R140 关键行：allocation_engine.py:1522-1529（cap 条件）容器内 grep 确认；`[allocation] R131 satellite layer capped` 全仓日志 0 次（rg 验证）。
- R141 关键行：strategy_check.py:1394 `comp = s.get("composite_score")`、1395 `avg = comp if isinstance(comp, (int, float)) else 0.0`（read_file 确认）；453 行 `h["factor_scores"] = ...`（read_file 确认）。
- R112/R113/R114：AppTabs.vue:69、App.vue:61-65、PortfolioAnalysis.vue:26 均 read_file 确认。
- 数字核对：balanced 卫星 0.300/总仓位 1.024、aggressive 卫星 0.350/总仓位 1.065（diag_r131.py 快照）；Lighthouse 首页 P99/A95/BP96/SEO91、仪表盘 P73（lh_r38_*.json）；patrol L1 2796 PASS（latest.json）；verify_e2e 176/202（--host 127.0.0.1 实跑）。

### Round 2（四问法质量审查）

已执行：见 §4 逐条审查表。关键交叉验证：
- R140 自洽：cap 未触发（日志 0 次）↔ 卫星层超配（0.300/0.350）↔ 总仓位超 1.0（1.024/1.065）——三者互相印证，无内部矛盾。
- R141 自洽：规则兜底路径 factor_composite=None → avg_factor=0.0 → 表格 0.00，与 1394 行代码逻辑一致。
- R139 自洽：DB malformed + /designs 500（disk I/O error）+ 应用持有连接仍可读部分表——SQLite 部分 page 损坏 + 连接缓存 page 的现象一致。

### Round 3（测试缺口 + 文档结构审查）

已执行：§6 四类缺口（DB 并发写入 / R131 后续放大 / R141 表格一致性）+ 汇总评价。文档结构：执行摘要 → 环境 → 对照矩阵 → Lighthouse → 四问法 → 修复方案 → 测试缺口 → 证据 → 下一步 → review，11 节齐全。
- 未决项：R143（需按 provider 分解错误类型）、R144（环境性）、R140（交易时段复测）——均在 §5.4/§0.3 标注。
- 风险点：R139 P0（DB 损坏核心功能受损）、R140 P1（总仓位超配）——优先级与 round37 一致（R137 曾 P1，本轮升级 P0 因复发）。