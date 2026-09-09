# 项目冗余 / 过度设计 / 过度测试评审

日期：2026-09-07 ｜ 范围：`backend/app`、`frontend/src`、`backend/tests`、`backend/scripts`、`.githooks/pre-commit`、`api-contracts`、`docs`
方法：本地静态排查（行数统计 + 符号/grep + 入口阅读）。三路后台语义扫描因额度失败未执行，
凡“死代码”判定均标为**待核实**——删除前必须先跑 `audit_unused_symbols.py` / `check_api_usage.py` 实证，
不得凭本报告直接删除。

## 0. 结论先行（TL;DR）

1. **没有全局性冗余灾难**。分层（engine 纯函数 / services 编排 / hub mixin / portfolio 包拆分）是过去多轮
   还债的结果，不是过度设计，**建议保留**。
2. **真正的膨胀在测试与门禁侧**：测试行数 47,716 > 业务代码 34,425（1.39×），测试文件 320 对业务 142（2.25×）；
   `verify_e2e.py` 2,319 行、`patrol.py` 611 行、pre-commit 432 行/16 段门禁——这是本轮最值得动刀的地方。
3. **确认的冗余只有 2 处**：`async_utils` 5 个包装函数含 2 个已标注 deprecated 的透传别名；
   `_fetch_market_data` DEPRECATED 大函数体仍驻留 `factor_registry.py`（约 200+ 行，含 R146/R150 收口桥接）。
   其余（mocks、archive 脚本、probe_ 结果 json）均为**小体量、低风险**，可批量清理但期望收益小。
4. **架构总体合理**，6 个关键决策中 5 个成立；唯一的结构性风险是 `allocation_engine.py`（1,721 行/30+ 函数）
   的“纯函数大文件”，以及 `main.py`（1,058 行）lifespan 聚合过多启动逻辑——两者都是**可维护性债**，
   不是正确性问题，按 P1/P2 排期即可。
5. **不建议做的事**：合并 hub/portfolio 已拆分包、删 contract-first 契约、为“减行数”而压测试总量。
   本报告的建议是“收敛增量 + 设上限”，不是“大扫除”。

## 1. 基线数据（实测）

| 对象 | 规模 | 备注 |
|---|---|---|
| `backend/app` | 142 py / 34,425 行 | engine + services + factors + fetchers + core + tasks + routers |
| `backend/tests` | 320 py / 47,716 行 | 测试/业务行数比 **1.39×**，文件数比 **2.25×** |
| `frontend/src` | 124 文件；45 spec | 组件/视图最大 1,112 行（PortfolioManager.vue） |
| `docs` | 139 md / 37,180 行 | 顶层仅 ~15 个活跃文档，其余在 `archived/` + `prompt-templates/`，属历史归档非膨胀 |
| `api-contracts` | 59 md | 8 个业务 router 对 59 份契约（含 internal 拆分契约） |
| `backend/scripts` | verify/check/audit/probe/sync 共 19 个 + archive/evals 子目录 | `verify_e2e.py` 2,319 行最突出 |
| `.githooks/pre-commit` | 432 行，16 段门禁 | AGENTS.md 自述“不再新增同类” |
| `backend/app/main.py` | 1,058 行 | lifespan + warmup + loops 聚合 |
| `engine/allocation_engine.py` | 1,721 行，30+ 函数 | 全仓最大业务文件 |
| `factors/factor_registry.py` | 1,511 行 | 含 DEPRECATED fallback |
| `services/market_service.py` | 1,659 行 | 全仓第二大 |
| `services/strategy_design.py` | 1,185 行 | 编排器偏大 |

最大文件 Top（业务侧）：allocation_engine 1721 > market_service 1659 > factor_registry 1511 > strategy_design 1185 >
market_data_hub 664（另有 hub/ 9 个 mixin：_kline 343 / _common 278 / _news 189 / 其余 48–156）。
前端 Top：PortfolioManager.vue 1112 > FactorModelView 1039 > SourceMonitor 967 > App.vue 770。

测试主题分布（`test_` 前缀计数）：factor 21、llm 20、design 18、market 8、sector 8、v7 8、warmup 6、
watchlist 6、engine 6、news 6、round51 5、strategy_check 4、ic 4。最小测试文件 23–41 行（约 20 个），
`__init__.py` 0 行。

## 2. 冗余代码排查

### 2.1 确认冗余（可直接排期）

- **R1. `core/async_utils.py` 包装函数 5 个，2 个是零逻辑透传别名**（`async_utils.py:93,124,138,169,182`）。
  `safe_call` → `run_in_thread`、`safe_call_async` → `run_sync`，文件内注释自述“标记 deprecated 别名…
  后续轮次移除”（round23 §10.2 D1）。调用方已收敛到 `run_sync/run_in_thread` 即可，别名保留越久，
  新代码误用概率越高。建议：全仓替换后删除 2 个别名（P1，约 30 分钟 + 全量 pytest）。
- **R2. `_fetch_market_data` DEPRECATED 大函数体仍在线**（`factors/factor_registry.py:1236-~1470`）。
  注释写明 fallback 定位、“Will be removed in Phase 20”，但函数内仍有 R146 nav 注入、R150 total_mv/
  float_mv 桥接、R148 industry 桥接等**生产仍依赖的逻辑**。现状 = “名义 deprecated、实际关键路径”，
  风险在于后来者误以为可删。建议：先把 3 处桥接抽成独立小函数并补单测，再把本函数缩为 thin-fallback（P1）。
  注意 round38 R146/R150 的生产链路结论仍有效，动这块必须带探针验证。

### 2.2 待核实（有嫌疑，不得直接删）

- **S1. `frontend/src/mocks/`（handlers.js 22 行、server.js 5 行）**：体量极小，疑似 MSW 残留或仅被单测引用。
  需 `rg "from.*mocks|import.*mocks" frontend/src` 确认调用点后再定（0 调用则删，P2）。
- **S2. `backend/scripts/archive/`**（`_diagnose_factor.py`、`_test_design_api.py` 等）+ `probe_*_results.json`
 （design_pipeline / fm3 / openrouter / zen）：探针产物，归档性质。确认无引用即可移出或注明只读（P2）。
- **S3. fetchers 与 services 的 sync_* 重名**：`fetchers/sync_indices*.py`、`services/indices_meta_sync.py`、
  `services/instruments_sync.py`、`scripts/sync_*` 四处同名不同层。可能是“管道/编排/入口”有意分层，
  也可能是历史复制。需逐文件确认职责后再定是否合并文档说明（P2，只加注释也算修）。
- **S4. 后端 `__pycache__` 多版本并存**（cpython-312/313/314）：构建/解释器混用痕迹，非源码问题，
  加 `.gitignore` 或清理即可（P2，5 分钟）。
- **S5. `/ws/market/{symbol}` 后端存在、前端主消费走 `/ws/portfolio`**（AGENTS.md conventions 已记载）。
  WS 三件套（`utils/wsBase.js` + `useNewsWS.js` + `useTaskWS.js` + `stores/market.js`）经 grep 确认
  均复用 `WS_BASE`，**无重复实现**，不算冗余。但 `/ws/market/{symbol}` 若长期零消费，应在契约中标
  deprecated 或补一个最小消费方，避免“有端点无调用”的脚手架观感（P2，见 §5.4）。

### 2.3 已排除（看起来多、实际合理）

- hub 9 mixin + portfolio 8 模块 + facade 135 行：是 round15–round41 的拆分还债成果，**禁止合回去**。
- `aggregate_factor_scores` 委托 `core/factor_aggregate`（`factor_registry.py:1181-1195`）：兼容垫片，
  有明确下沉注释，保留。
- `fund_fetcher / fund_share_fetcher / fundamentals_fetcher`：份额 vs 基本面 vs 场外净值，职责不同，保留。
- docs 139 个：顶层活跃文档少，大头在 `archived/`，属“审计数据源”设计（AGENTS.md 会话记忆惯例），不删。

## 3. 过度设计排查

| # | 观察 | 判定 |
|---|---|---|
| D1 | async 双池（shared 64 + long 8）+ 有界提交（128）+ 饱和快速拒绝 +  spike 计数 | **合理**。mootdx 空转/R6 饱和是有案可查的故障驱动，不是预设过度。保留，勿调参。 |
| D2 | SourceRegistry 熔断 + miss≠failure + 指数退避 600s 上限 | **合理**。免费源 flaky 是本项目的核心约束，README 数据源表即其契约化。保留。 |
| D3 | engine AST 纯度门禁 + audit_async_blocking 门禁 | **合理且高价值**。正是这两道门禁保证了“计算可复现”，删掉等于自废武功。保留。 |
| D4 | agentic/（loop/executor/trace/cost）+ mcp_servers/（4 stdio）+ scripts/evals（64 golden + ci_gate 95%） | **基本合理，边际偏重**。与 README “生产级 agent 栈”叙事一致；代价是新增一套 loop/预算/评估维护面。若团队不再演进 agent 能力，它就是全仓最贵的“可选件”。建议：冻结功能增量，只修 bug；evals 阈值不动。（P2 决策，不动代码） |
| D5 | allocation_engine 1,721 行 30+ 函数（_select_draft/_size_allocations/多 reconcile/enforce/cap/dedup/substitute…） | **结构性坏味道，唯一的 P1 设计债**。纯函数+无 I/O 是对的，但 30+ 私有函数同文件已接近“上帝模块”。建议按“选择/定尺寸/约束/替代/校验”拆 3–4 个模块，`allocate` 保持入口不变；先补 golden 用例再拆。（P1，大改，需单独 round） |
| D6 | main.py 1,058 行（profiling 开关 + warmup 分段计时 + 4+ 后台 loop + holdings/sector 预热） | **轻度臃肿**。lifespan 做编排是 FastAPI 常规做法，但 warmup 计时/分段标签与业务启动逻辑混排。建议只抽 `_warmup_*` 与 loop 启动到 `tasks/startup.py`，main 留装配。（P2） |
| D7 | market_service 1,659 行 vs market_data_hub(+mixin) | **嫌疑，未定级**。本次只看了行数，未逐函数判定“行情编排”与“数据管道”边界。建议下轮对 market_service 做一次函数级归属审查，再决定是拆还是加注释。（P2，先审计后动手） |

## 4. 冗余测试排查（本次重点）

### 4.1 定量结论

- 测试 320 文件 / 47,716 行 vs 业务 142 文件 / 34,425 行：**行数比 1.39×、文件数比 2.25×**。
  对“免费数据源 + 纯函数引擎 + LLM 不可复现”三重风险的项目，这个比例**方向正确但绝对值偏高**。
- 主题扎堆：llm 20、factor 21、design 18（合计 59，占 18%）。三者恰好是“最不可复现 × 最关键”的交叉点，
  扎堆本身合理；问题在**粒度**：20+ 个 23–41 行小文件（annotation/path/persist/status 类）说明存在
  “一行为一文件”的 round 驱动测试膨胀。
- 前端 45 spec 对 124 源码文件，覆盖面完整；最大 spec（NewsView 531 / AiDesign 505 / UnifiedAnalysis 423）
  与被测组件规模成正比，无“为覆盖而覆盖”痕迹。**前端测试不定为过度**。

### 4.2 具体问题

- **T1. `verify_e2e.py` 2,319 行**：已从“链路验证脚本”长成“第二测试套件”。它与 pytest（单测）、
  patrol（编排）、pre-commit（门禁）四层之间必然存在重叠断言。建议：冻结其增量（新链路只加 pytest），
  存量按“端点级冒烟”精简到 ≤800 行，其余下沉为 pytest。（P1，分 2–3 批做）
- **T2. “一行为一文件”小测试**：约 20 个 23–41 行文件（`test_sector_prompt_annotation`、`test_kline_cache_path`、
  `test_engine_config`、`test_commodity_signature` 等）。单个看都有理由，合在一起就是每次全量多付
  320 次收集/导入成本。建议：按主题合并为 4–6 个聚合文件（如 `test_warmup_*` 6 个 → 1 个），
  合并时保留用例名不变以便追溯。（P1，机械合并，风险低）
- **T3. 门禁 16 段 / pre-commit 432 行 + patrol 611 行**：AGENTS.md 已自我约束“不再新增同类、死代码审计保留 3 个”。
  现状可接受，但**必须设上限**：新增门禁走“替换制”（加一段必须说明替代哪段），patrol `--full` 超时预算写死。
  另：`tests_ok_marker` + `check_test_baseline` + P3-6 基线三件套做的是同一件事（“全量太贵所以做凭据”），
  建议合并为一套凭据机制。（P2）
- **T4. round/v7 历史用例**（`test_v7_*` 8、`test_v5_*` 2、`test_round51_*` 5、`test_r1*` 7）：与功能用例按轮次双重覆盖。
  这是 TDD 留痕的正常代价，**不建议删除**（删了就丢回归网）；控制增量即可：新 round 用例必须归入主题文件，
  不再开 `test_roundXX_*` 新文件。（P2，约定的事，不动代码）
- **T5. `check_test_baseline.py` 仅 50 行却独立成门禁**：功能上可并入 patrol，建议合并。（P2）

### 4.3 测试策略建议（设上限，不搞大扫除）

1. 冻结 `verify_e2e.py` 行数（只减不增），新断言一律写 pytest。
2. 小文件合并 4–6 个聚合文件；全量 pytest 行数目标：47,716 → 40,000 以内（约 -15%），不追求更低。
3. 门禁替换制 + 凭据机制三合一。前端 vitest（~10s）与 16 Playwright E2E 保持不动——它们是当前性价比最高的网。

## 5. 架构合理性评审

总评：**合理，7.5/10**。分层清晰、约束显式、降级诚实；扣分项全在“大文件”与“可选件重量”，不在方向。

### 5.1 分层（成立）

Browser → FastAPI routers → tasks workers → agentic(可选) → services 编排（hub mixin / portfolio 包）→
engine 纯函数 → factors/fetchers → L1 内存 / L2 Redis / SQLite。调用方向单向（engine 零 I/O 有 AST 门禁背书），
`market_data_hub` 被 11+ 调用方复用且“无测试直挂”是**复用成功**的表现（测试挂在调用链上），不是缺失。
hub 9 mixin + portfolio 8 模块的拆分是正确的，禁止回滚。

### 5.2 数据流与降级（成立，加分项）

多源降级链（mootdx→腾讯→Sina→TickFlow 等）+ SourceRegistry（miss≠failure）+ 诚实降级字段
（`data_available/estimate_source/degraded/{data,as_of,source,degraded}` 信封）是全仓最强的一环。
README 把“flaky 免费源”写进设计约束是对的——这不是防御性编程过度，而是领域本质。

### 5.3 异步模型（成立，注意一条红线）

双线程池 + `run_sync` 收编 + audit_async_blocking 门禁，方向正确。红线（AGENTS.md 已有）重申一次：
`run_in_thread/safe_call` 是同步阻塞等待，async 上下文误用即冻结事件循环——R1 删除别名后，
这条红线只剩 `run_sync/run_sync_long` 两个正确入口，误用面减半。

### 5.4 前后端契约（成立，偏重但自洽）

59 份双语契约对 8 个 router，看似倒挂，但 `check_routes.py` 把“契约↔路由一致”做成了硬门禁，
且 internal（engine-pure-functions、market-data-hub-split、portfolio-split、llm-split）四份正是拆分还债的
说明书。契约-first 是团队自选的流程税，有门禁收租就不算过度。唯一动作：S5 的 `/ws/market/{symbol}`
零消费问题，在契约里标 deprecated 或补消费方（P2）。

### 5.5 可观测性（成立）

token_usage / source_events / probes / warmup 状态端点 + 线程池/连接池统计：对“LLM 花钱 + 免费源 flaky”
的项目是必要成本，不是装饰。保留。

### 5.6 风险清单（按优先级）

1. `allocation_engine.py` 上帝模块化（§3 D5，P1）。
2. `main.py` lifespan 聚合（§3 D6，P2）。
3. `market_service.py` 1,659 行边界未审计（§3 D7，P2 先审计）。
4. agentic/evals 維護面（§3 D4，冻结增量）。
5. 测试/门禁增量无上限（§4.3，三条冻结规则）。

## 6. 行动清单

| ID | 动作 | 规模 | 验收 |
|---|---|---|---|
| P1-1 | 删 `safe_call/safe_call_async` 别名，全仓切 `run_sync/run_in_thread` | 30 分钟 | grep 零命中 + pytest 全量绿 |
| P1-2 | `_fetch_market_data` 瘦身：3 处桥接抽函数+单测，本体留 thin-fallback | 半天 | 探针（R146/R150/R148 路径）+ verify_e2e 全 PASS |
| P1-3 | `verify_e2e.py` 冻结增量并启动精简（2319→800 行目标，分批） | 2–3 批 | 每批 e2e 全 PASS + 被迁移断言在 pytest 中存在 |
| P1-4 | 小测试文件合并（20→4–6 聚合文件，用例名不变） | 半天 | pytest 全量绿 + 总行数 < 44,000（第一刀） |
| P1-5 | `allocation_engine.py` 拆分（选择/定尺寸/约束/替代/校验） | 单独 round | golden 回放一致 + pytest 全量绿 |
| P2-1 | mocks/archive/probe 产物确认后清理 + pycache 忽略 | 1 小时 | rg 零引用实证 |
| P2-2 | `/ws/market/{symbol}` 契约标注或补消费方 | 1 小时 | 契约更新 + check_routes 绿 |
| P2-3 | main.py 抽 `tasks/startup.py`；market_service 函数级归属审计 | 半天 | 启动行为一致（smoke_startup） |
| P2-4 | 门禁替换制 + 凭据三合一 + `check_test_baseline` 并入 patrol | 半天 | pre-commit 行数不增 |
| 不做 | 合并 hub/portfolio 包、删契约、删 round/v7 回归用例、调线程池参数 | — | — |

## 7. 附录：复核命令

```powershell
# 行数基线
(Get-Content -Recurse backend/tests/*.py | Measure-Object -Line).Lines
(Get-Content -Recurse backend/app/*.py | Measure-Object -Line).Lines
# 别名残留（P1-1 验收：零命中）
Select-String -Pattern "safe_call[^_]|run_in_thread" backend/app --include *.py
# mocks 引用（P2-1 实证）
Select-String -Pattern "mocks" frontend/src
# 小文件清单（P1-4 范围）
Get-ChildItem backend/tests/*.py | ForEach-Object { $l=(Get-Content $_.FullName | Measure-Object -Line).Lines; [pscustomobject]@{Lines=$l; Name=$_.Name} } | Sort-Object Lines | Select-Object -First 20
```
