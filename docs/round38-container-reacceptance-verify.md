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
| 🆕 专项排查 | 因子无数据 R145-R151（详见 §11） |
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

---

## 11. 专项排查：因子模型中大量因子无数据（R145-R151）

> **背景**：用户反馈「因子模型中还有很多因子没有数据」。本专项在运行中后端
> （/factors/model + /factors/active 实时响应）与 5 只真实 ETF
> （510300/518880/159915/512480/511090）实况因子计算探针双重实证下排查。
> **范围**：只出方案，不写代码（用户明确要求）。
> **验证窗口**：2026-08-27 周三收盘后非交易时段；实时行情类结论待交易时段复测。

### 11.1 三层结构总览（实证数据）

`/factors/model` 实时响应：

```
total=193  implemented=38  planned=155
summary: valid=0  no_data=7  warn=20  static=11
```

`/factors/active` 按类别（valid/warn/no_data/static）：technical 14/0/0、etf_specific 6/4/0、
style 0/2/0、sentiment 0/1/3、macro 0/0/5、china_specific 0/0/3。

实况探针（5 只 ETF，`registry.compute()` 直连）：

- 每 symbol 产出 39 键（38 因子 + 1 聚合孪生），non-zero 24-25、zero 11-12；
- `_data_source_gaps`（F3-4 步骤D 记录）：etf.industry_diversification / institutional_holdings_change /
  shares_change / tracking_error / sentiment.stock_divergence / style.size.ln_mcap / ln_float_mcap
  均 **5/5 标的缺字段**；
- `_constant_factor_codes`（O20 截面常量检测）：china.policy.\*（3）+ etf.industry_diversification /
  institutional_holdings_change / shares_change / tracking_error + sentiment.news_direction /
  stock_divergence（9 个）→ 输出全截面同值，被 z-score std≈0 跳过。

### 11.2 发现明细表（R145-R151）

| # | 判定原文 | 事实/推断 | 支撑（file:line + 实证） | 与行情一致? | 结论 | 方案优先级 |
|---|---|---|---|---|---|---|
| R145 | 155 个因子已定义未实现，永不产出数据 | **事实** | YAML 定义 193（factor_definitions.yaml），`_BUILTIN_COMPUTERS` 仅 38（factor_registry.py:679-722）；`compute()` 只遍历 `_CORE_FACTORS ∩ _computers`=38（factor_registry.py:1438）；/factors/model `planned=155` | 不依赖行情 | 合理（路线图非缺陷） | 观察项（见 11.3-D） |
| R146 | etf.premium_discount 恒 0.0（IOPV 链接入断链） | **事实** | IOPV 三级降级链只在 `_fetch_market_data`（factor_registry.py:1259-1296，标记 DEPRECATED 的 fallback 路径）；hub refresh_pool 调 `compute()` 传 `market_data=cached_kline`（market_data_hub.py:334-337）→ 走 market_data 分支（factor_registry.py:1440-1456）只合并 symbol_extra 7 键、**无 nav** → IOPV 链被整条跳过 → `_compute_premium_discount` 恒 return 0.0（factor_registry.py:462-468）；探针/constant 检测 5/5 同值 | 不依赖行情 | 合理（确定性断链） | **P0** |
| R147 | etf.shares_change / etf.institutional_holdings_change 无数据 | **事实（已实测定案：免费源无份额历史序列，不可修复）** | 依赖 `shares_change_20d`。实测：① `fund_etf_hist_em` 主源经代理 **ProxyError**、no_proxy **ConnectionError RemoteDisconnected**（push2his.eastmoney.com 盘后不可达）；② 降级源 `_fetch_spot_shares()`（fund_etf_spot_em）实测可用（1591 只，510300 最新份额=23481487616.0）；③ **但降级结果 `shares_change_20d=None`（round9 P1-9 已注「份额历史序列无免费公开源」）→ `_enrich_symbol_extra._shares` 因 `shares_change_20d is None` 直接 return 不注入（_kline.py:438-439）→ shares_change 恒 0.0**。免费源只有当前份额、无历史序列 → change_20d 数学上不可算 | 不依赖行情 | 合理（免费源根本无此数据） | **定性：数据源缺失，非代码可修** |
| R148 | etf.industry_diversification 无数据 | **事实（已实测定案：concepts 数据可用，因子计算设计缺陷）** | 真实 refresh_pool 实证：concepts **各不相同**（510300→['沪深300']、159915→['创业板']、511090→['国债','利率债']、518880→['黄金','贵金属']，confidence 0.7-0.85）→ 数据源**可用**。**但 `_compute_industry_diversification`（factor_registry.py:401-419）读 `industry_holdings`（从未注入）→ 回退 `concepts` → 返回 `1.0/max(len(concepts),1)`——只依赖概念数量、不依赖概念内容** → 概念数相同的 ETF 同分（如 510300 与 159915 均 1 概念→均 1.0）→ 截面区分度不足 → 偶发全同值被 O20 判 constant | 不依赖行情 | 合理（数据源可用，计算设计简陋） | **P2（改因子计算逻辑，非接数据源）** |
| R149 | sentiment.news_heat 恒 0.0，漏判 MARKET_LEVEL | **事实** | 从**全市场**新闻缓存计算（market_data_hub.py:360-374），每只 ETF 同值 → 截面恒等；另 3 个 sentiment 因子（panic_greed_diff/stock_divergence/news_direction）已在 MARKET_LEVEL_FACTOR_CODES（factor_status.py:38-49），唯独 news_heat 漏判 → 显示 no_data 而非 static | 不依赖行情 | 合理（归类缺陷） | P1 |
| R150 | style.size.ln_mcap / ln_float_mcap 无数据 | **事实（已实测定案：字段名不匹配确定性 bug）** | `_compute_ln_mcap` 读 `data["total_mv"]`（factor_registry.py:146），**但 refresh_pool 注入的是 `fund_scale`**（market_data_hub.py:317-325）；compute() market_data 分支白名单含 `fund_scale`（factor_registry.py:1454）→ **字段名 `total_mv` vs `fund_scale` 不匹配 → 永远读不到 → 恒 None**。生产路径探针实证：传入 `fund_scale=111688430607.0` 后 ln_mcap 仍 None。且实测 `fetch_fund_scale` 主源 `fund_etf_fund_info_em` 抛 **ValueError: Length mismatch（14 vs 13 列）**（akshare 版本 bug）→ 返回 None；`fund_etf_spot_em` 有 `总市值` 列（510300=111688430607）但无人读取。`ln_float_mcap` 读 `float_mv`（K 线行无此字段）→ 恒 None。**根因=①字段名映射断裂（可修）②akshare 列解析 bug ③float_mv 无源** | 不依赖行情 | 合理（确定性 bug） | **P0（字段映射可修）** |
| R151 | 20 个 warn 因子有数据但未显著 | **事实** | factor_ic_records DB：技术/etf 类 20 因子已有 442-500 个交易日 IC 记录（2024-08 至今），但 t<2 或 \|IR\|<0.5（F25② 判据 factor_status.py:58-105） | 不依赖行情 | 合理（统计积累中，非故障） | 观察项 |

### 11.3 修复方案（P0/P1/P2 + 观察项）

**P0 — etf.premium_discount IOPV 链接入 hub 主路径（R146）**

- 根因：nav 注入（IOPV 三级链 + TTJ 日净值兜底）只存在于 `_fetch_market_data`（factor_registry.py:1259-1296），而生产链路（refresh_pool → `compute(market_data=cached_kline)`）走 market_data 分支、跳过该函数 → nav 永不注入 → premium_discount 恒 0.0（生产路径探针实证 5/5 = 0.0，constant_factor_codes 含 premium_discount）。
- 方案（三选一，推荐 A）：
  - **A（推荐）**：把 nav 注入从 `_fetch_market_data` 提取为独立方法（如 `_inject_nav(market_data, symbols)`），在 `compute()` 的 market_data 分支（factor_registry.py:1448-1456）与 `_fetch_market_data` 两处复用。复杂度低，一处救活。
  - B：在 refresh_pool 的 `_enrich_symbol_extra`（market_data_hub.py:328）内追加 IOPV/nav 获取（与 benchmark_close/shares_change_20d 同点）。改动在服务层，factor_registry 保持纯。
  - C：compute() 的 market_data 分支补 nav 字段合并（把 nav 加入 1452-1454 的 7 键白名单），前提是调用方已注入 nav —— 需确认谁注入。
- 影响文件：factor_registry.py（或 market_data_hub.py）
- 工作量：30min + 单测
- 验证：单测 mock `_fetch_iopv_chain` 返回 nav，断言 compute() 产物 premium_discount 非 0；e2e 用真数据断言 /factors/active premium_discount status 由 no_data → warn/valid。

**P0 — style.size.ln_mcap / ln_float_mcap 字段名映射修复（R150，实测定案后升级）**

- 根因：`_compute_ln_mcap` 读 `total_mv`（factor_registry.py:146），refresh_pool 注入 `fund_scale`（market_data_hub.py:317-325），compute() market_data 分支白名单也是 `fund_scale`（factor_registry.py:1454）——**两边字段名对不上，数据永远读不到**。生产路径探针实证：传 `fund_scale=111688430607.0` 后 ln_mcap 仍 None。
- 方案（推荐 A）：
  - **A（推荐）**：`_compute_ln_mcap` 增加别名读取：`mv = data.get("total_mv") or data.get("fund_scale") or 0`（一处改动，兼容两条注入路径）。`ln_float_mcap` 同理尝试 `float_mv`。
  - B：refresh_pool 注入时改键名为 `total_mv`（改 service 层，同步改白名单）——影响面大，不推荐。
  - C：`fetch_fund_scale` 换 akshare 接口规避 ValueError（fund_etf_fund_info_em 14 vs 13 列 bug）→ 改读 `fund_etf_spot_em` 的 `总市值` 列（实测 510300=111688430607 可用）→ 但需先修 `_fetch_spot_shares` 或新增 `_fetch_total_mv`。可作为 A 之后的补充（拿真实市值而非 0）。
- 影响文件：factor_registry.py（A）或 fundamentals_fetcher.py + factor_registry.py（C）
- 工作量：A=5min+单测；C=30min+单测
- 验证：单测传 `{"fund_scale": 1e9}` 断言 ln_mcap 非 None；生产路径探针断言 ln_mcap 有真实值。

**P1 — 数据源接入（R149）**

| 编号 | 问题 | 方案 | 影响文件 | 工作量 |
|---|---|---|---|---|
| R149 | news_heat 归类 | 将 `sentiment.news_heat` 加入 `MARKET_LEVEL_FACTOR_CODES`（factor_status.py:38-49），与另 3 个 sentiment 因子一致 → 前端显示 static 而非 no_data（待 ETF 级舆情数据源接入后再恢复截面计算） | factor_status.py | 5min + 单测 |

**P1 — 定性结论（R147，已实测定案：免费源无此数据，非代码可修）**

- `shares_change_20d` 需要份额历史序列——`fund_etf_hist_em` 无份额列且盘后不可达（ProxyError/ConnectionError），`fund_etf_spot_em` 仅当前份额（510300=23481487616.0）。免费源**根本没有份额历史**，change_20d 数学上不可算。
- 处置：维持诚实降级（gap 标注「缺 shares_change_20d」），列入「数据源未接入」观察清单。**不强行造数**。若后续接入付费/其他源（如天天基金份额历史）再恢复。

**R147 数据源调研结论（2026-08-27 补充：有免费源，建议接入）**

- **调研结果：两个交易所官方 API 提供免费日频份额序列，可算 20 日变化率**（akshare 1.18.81 内置 + 原始接口均实测）：
  1. **深交所 `ak.fund_scale_daily_szse`**（`www.szse.cn/api/report/ShowReport?CATALOGID=scsj_fund_jjgm`）：一次请求返回一个窗口（≤6 个月）内**全部**深市 ETF 的日频份额（实测 5 日 3599 行，159915 连续 5 天值 1.816e10→1.872e10 份）；覆盖 ETF/LOF/REITS；历史 ≥2019-09；**akshare 封装直接可用**。
  2. **上交所 `fund_etf_scale_sse`**（`query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L`）：按统计日期快照全量沪市 ETF 份额（实测 897 只，含 510300/518880/511090/588000 等）；历史 ≥2019-09；**akshare 封装在本地报 KeyError（列名编码 bug）但原始接口完全可用**——自写 requests 实测 T/T-20 两次请求算出真实 20 日变化率（510300 -5.85%、518880 +7.78%、511090 +0.18%）。
  - 覆盖说明：5xxxxx→沪市、1xxxxx→深市按代码前缀合并；**LOF 型（501xxx）沪市 ETF scale 列表不含**（需单独查 SSE LOF sqlId，边际缺口，候选池影响低）。
  - 成本：免费无认证、官方披露基础设施稳定；每次刷新 SZSE 1 请求 + SSE 2 请求。
  - **建议**：接入（见 P1 新增方案 R147-FIX）。tushare fund_share（¥200/年积分门槛）与天天基金 F10（接口已死 404 + 季度粒度）均不选。

**P2 — industry_diversification 计算逻辑修复（R148，已实测定案：数据源可用，计算简陋）**

- 根因：concepts 数据真实可用（510300→['沪深300'] 等），但 `_compute_industry_diversification` 回退逻辑返回 `1.0/max(len(concepts),1)`——**只依赖概念数量、不依赖内容** → 概念数相同即同分 → 截面区分度不足。
- 方案（推荐 A）：
  - **A（推荐）**：改用 `1.0 / (1 + len(concepts))` 做**单调递减归一**（概念越多越分散），并**优先读 `industry_holdings`**（若 ETF 持仓行业分布数据可接入）；无 holdings 时维持 concepts 长度倒数，但改为 `len(concepts)` 不同即区分——实际上真实池 4 只 concepts 数量是 1/1/2/2，截面区分度仍弱 → 需接受该因子在候选池规模下的天然弱区分度，或在 /factors/active 标注「弱区分因子」。
  - B：接入 ETF 前十大持仓 → 行业聚合 → 真实 HHI（需新数据源，成本高）。
- 影响文件：factor_registry.py（A，改计算函数）
- 工作量：A=15min+单测；B=1-2h+新数据源

**P1 新增 — R147-FIX 接入交易所份额源（2026-08-27 调研定案后补充）**

- 背景：R147 原定性「免费源无数据不可修」已被调研推翻——上交所/深交所官方 API 提供免费日频份额，实测可用。
- 方案：
  - 新增 fetcher（建议 `backend/app/fetchers/fund_share_fetcher.py`）：
    - `fetch_szse_daily_shares(start, end)` → 调 `ak.fund_scale_daily_szse`（akshare 封装可用），输出 {symbol: {date: shares}}；
    - `fetch_sse_shares(date)` → **自写 requests** 调 `query.sse.com.cn`（绕过 akshare 封装 KeyError bug），输出 {symbol: shares}；T 与 T-20 两次请求算 change_20d；
    - 按代码前缀合并（5xxxxx→SSE、1xxxxx→SZSE），统一输出 `shares_change_20d`。
  - 接入点：`_kline.py:_enrich_symbol_extra._shares`（market_data_hub.py:328 调用链）——替换/并行走 `fetch_etf_shares_outstanding`；成功时注入 `shares_change_20d`（现 None-skip 逻辑自动放行）。
  - 缓存：每日份额快照落 SQLite（append-only 日任务，自建份额历史，避免重复回填）；`asyncio.wait_for` ~15-20s + 失败诚实降级（保持 None 不造数）。
- 影响文件：新增 fetchers/fund_share_fetcher.py；修改 _kline.py（_shares 注入点）、market_data_hub.py（可选）
- 工作量：30-60min + 单测（mock akshare/requests）
- 验证：单测 mock SZSE/SSE 返回 → 断言 change_20d 正确；e2e 用真数据断言 510300/518880 shares_change 由 no_data → warn。
- 已知注意：绝对份额值 EM spot 与交易所官方差 ~1.5%（口径/as-of 差异），change_rate 因子对此鲁棒；LOF（501xxx）沪市缺口挂观察清单。

**观察项 / 待决策（R145/R151）**

- R145（155 planned）：**路线图而非缺陷**——/factors/model 已如实标 planned。若要提覆盖，优先 theme.\*（29）/ style 单类，但需上游基本面数据支撑（当前免费源大多无个股财务/ESG/专利数据），成本高、收益低，建议暂缓并保持 honest planned 标注。
- R151（20 warn）：统计积累中（已有 442-500 交易日），按 F25② 需 t≥2 且 |IR|≥0.5，属正常收敛过程，无修复动作。

### 11.4 测试防护缺口

| 缺口 | 现状 | 建议 |
|---|---|---|
| IOPV/nav 注入覆盖 | 仅 `_fetch_market_data` 路径有 nav（无单测覆盖 market_data 分支的 nav 注入） | 新增单测：`compute(market_data=...)` 时 nav 被注入 → premium_discount 非 0（R146 验证） |
| news_heat 归类 | 无测试断言 news_heat 与 MARKET_LEVEL 因子同档 | 新增断言：news_heat 在 MARKET_LEVEL_FACTOR_CODES 中（R149） |
| 因子数据源缺口 | `_data_source_gaps` 有记录但无巡检断言 | data_health_check 增项：assert 关键因子（premium_discount/ln_mcap）gap 数不为全量，捕获「全断链」回归 |

### 11.5 决策记录（2026-08-27 用户确认 + 排查定案）

| 项 | 决策 | 备注 |
|---|---|---|
| R146 IOPV 链接入 | **A（提取 `_inject_nav` 公共方法，两处复用）** | 方案已定，待实施 |
| 修复实施 | **暂不实施** | 方案入档，后续需要时按 round 流程：先失败单测 → 实现 → 补单测 → verify_e2e → commit |
| R145/R151 维持现状 | **采纳建议，不强行填数** | 155 planned 保持 honest 标注，20 warn 正常积累 |
| R147/R148/R150 排查 | **已完成**（2026-08-27 实测定案） | 结论：R147 免费源无份额历史→**不可修**；R148 concepts 数据可用→**因子计算设计缺陷（P2 改逻辑）**；R150 **字段名不匹配确定性 bug（P0 可修）** |
| R147 数据源调研 | **有免费源，建议接入**（2026-08-27 补充调研） | 上交所/深交所官方 API 免费日频份额实测可用（详见 R147-FIX 方案）；tushare 付费不选；待用户确认后并入实施批次 |
| R149 news_heat 归类 | **随 P0 一起做** | 5min 改动，无争议 |