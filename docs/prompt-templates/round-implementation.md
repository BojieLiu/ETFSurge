# 实施轮提示词模板（round-implementation）

> 用于「按方案文档实施 → 验收 → commit + push」的一整轮工作流。复制到对话中，
> 替换第 1 行的方案文档路径与编号即可。参照 `container-fullchain-diagnosis.md` 的触发词惯例。

## 触发词

```
round实施 <round文档路径>
```

## 提示词正文

```text
【实施轮】按方案文档实施 + 验收 + commit + push

1. **方案文档**：`docs/roundXX-xxx.md`（本次为 R85-R92，编号/锚点以文档为准）
   - **实施前拍板状态核对（round53 教训，强制）**：先读文档决策节 + memory 拍板记录，
     **只实施已拍板项**——暂缓/待解禁项即使列在方案节也**跳过并在实施记录注明**
     （round53 后小批清单 4 项仅 2 项获批，R179/R180 为暂缓登记；不核对会越权实施）。
   - **file:line 漂移核对**：方案文档到实施可能隔多轮 commit，动手前抽查文档引用的
     file:line 与当前 HEAD 是否一致，漂移先修文档锚点（或按当前代码重新定位）再实施。
   - **R 编号双锚引用**：R 系列编号在不同 round 文档间可复用（各文档都有自己的方案 A/B），
     实施记录/commit/communication 中引用发现一律「`docs/roundXX-xxx.md` RYY」双锚
     （文档路径 + 编号），裸 RYY 有歧义。
   - **实施范围超限熔断（round53 教训：诊断可推翻既定结论）**：实施中发现——
     文档方案与当前代码事实不符 / 方案依赖的前提被推翻 / 环境不支持方案假设——
     **停下向用户报告（现象 + 证据 + 选项），不自行修改方案、不硬实施**。
     方案文档是拍板产物，变更方案的权力在用户；实施者的边界是把已批准的方案正确落地。
2. **工作流**（遵循 AGENTS.md「反假完成机制」+「TDD」+「性能软门禁」）：
   - 先读文档对应章节（问题/根因/方案/验收/负向断言），只实现文档列出的项，不扩大范围
   - 每个改动项：先写能抓住问题的单测（含**能失败的负向断言**）→ 再实现 → 跑该文件测试
   - 实现要求：精确 `file:line` 定位、不改无关代码、不引入脚手架/死代码
   - **数据契约变更（如因子值可 None）必须 `rg` 全库扫消费方**（abs/sum/f"{v:.2f}"/
     isinstance 守卫），防止改动只在测试绿、运行期炸
   - **API 契约先行（AGENTS.md 强制，round52 实操确认）**：接口/字段语义类 R
     （加字段、改响应语义）先改 `api-contracts/` 再实现，契约含字段级断言；
     ⚠️ 域总契约（如 news/all.md 含多端点定义）**只能追加段，不可整文件重写**
     （会丢其它端点定义触发 check_routes FAIL——round52 实测）
   - **测试基建坑（round52 实操，mock/fixture）**：hub 同步方法经 run_sync 包装 →
     mock 用 **MagicMock** 非 AsyncMock；同 symbol 集合用例共享 cache_key
     （_PRICE_MAP_CACHE 类）→ autouse fixture 清缓存；fixture with-item 嵌套
     ~20 个撞 CPython compile 上限（ExitStack 累加同样撞）→ 拆分 fixture
3. **验证节奏（关键优化：避免全量套件重复跑）**：
   - **开发期**：只跑受影响测试文件 + mypy（<1min），**不跑全量**。⚠️ 引擎/分配器/约束类
     改动时，「受影响测试文件」**必须包含不变量/结构测试全家桶**（如 test_cash_and_overlap.py
     总标的数单调、test_allocation_engine_fixes.py、test_large_cap_wide_basis_exclusion.py、
     test_risk_controls.py 等），不能只跑直接相关的单测——否则约束语义变化会拖到全量
     14min 才发现，被迫全量跑 2 次（round32 教训：R101 改宽基语义 → INV-5 单调回归）。
   - **验收期**：全量只跑一次（`python -m pytest` 或 `patrol.py --full` 二选一，
     patrol L1 就是全量 pytest）；跑完 patrol 会自动写全量测试凭据
     （`backend/scripts/tests_ok_marker.py --mark`，由 patrol L1 通过时写入）。
     若用 `python -m pytest` 则全量通过后**手动** `tests_ok_marker.py --mark`。
     （若开发期受影响测试集覆盖充分，全量第一次应即绿；万一暴露回归，修复后重跑一次
     属正常，不算「全量跑 2 遍」违规。）
   - **运行时验证**：按文档验收口径**预先写成脚本/清单一次跑完**。后端生命周期**一次性
     管理**：把「起后端 → 等 warmup（~35-40s，先 `curl /health` 确认在线）→ 跑全部验证/
     verify_e2e → 杀后端」放进**单个自包含 bash 任务**（`(python -m uvicorn ... &) &&
     sleep 60 && verify_e2e; kill`），不因单个检查失败反复重启。⚠️ 不要 kill 用户正在
     跑的后端来验证——先起独立实例（换端口或复用 8000 前先确认）；要留持久后端用
     `nohup ... & disown`（Git Bash）或 `start.ps1 -Silent -NoOpen` 且**之后别再
     TaskStop 它的父任务**（TaskStop 会连坐杀整个进程树，曾误诊为「后端崩溃」）。
     撞外部源限流时接受降级并标注「待交易时段复测」，不要无限重试。
     ⚠️ **验证窗口标注（与诊断模板同规）**：涉及外部数据源/盘中行为的验收项
     （如 off-exchange 盘中 ti 估值）盘后无法真验时，验收口径收口到可测子集，
     未测项标「待交易时段复测」——不得把窗口外结果当 PASS 证据。
   - **启动命令钉死（round34 实施轮教训，勿现场实验）**：
     `python -m uvicorn app.main:app --host :: --port 8000`（start.ps1 同款）。
     ⚠️ Windows 上 `::` 为 v6only——只监听 ::1，不覆盖 127.0.0.1；verify_e2e 的
     `BASE=http://localhost` 依赖本机 ::1 优先解析，改绑 127.0.0.1 会制造
     「后端挂死」假象（两个模块误报 FAIL）。长任务等待用「detached 启动 +
     单次短状态查询」（每次 shell 调用 ≤60s），不要单次 sleep>120s 长轮询。
   - **特殊批次前置程序**：
     * *回填内容变更*（扩列/扩窗等）与 skip 门禁同批时：skip 判据是「总 distinct
       交易日」，感知不到 per-factor 覆盖缺口——须一次性强制重放
       `ETF_SURGE_FORCE_IC_BACKFILL=1` 启动（upsert 幂等，重放完即关）；若该开关
       不存在，用 rename 表法并注意 SQLite RENAME **保留索引名**，须先 DROP 该表
       全部索引再启动（否则 create_all 撞名崩溃），验证通过后 DROP 备份表。
     * *存活类修复*（锚/标的不得被移除）：实施前先普查**全部剥除点**
       （`rg -n "remove|filter|pop|dedup|merge" engine/ services/<域>/` 逐点确认豁免）
       ——只修 doc 列出的 top-N 嫌疑不够（round34 实证第三层剥除器在前两层修复后才
       显形）；守卫必须覆盖到 generate_enhanced_design 端到端，不能只测 allocate 层
       （剥除器多在其后的管线中）。
   - **verify_e2e**：提交前跑一次（AGENTS.md 要求），结果对照 round 文档既有基线
     （如 round32 264/280，16 FAIL 为环境性），**归类确认无新回归**即可，不要求全 PASS。
   - **commit 时**：若刚跑过全量（凭据有效），pre-commit 会自动跳过重复全量、
     只跑受影响测试（方案 B，2026-08-19 落地）。⚠️ **凭据纪律**：全量通过后立即
     `tests_ok_marker.py --mark`，且之后**不再增删改 backend/ 下任何文件**
     （指纹覆盖 app+tests+scripts，新增/删除/修改都令凭据失效）；提交被拦时先
     `tests_ok_marker.py check` 定位（exit code 取 python 的，勿被管道 `head` 的
     exit 误导），失效就重跑受影响测试 + 重 mark 再 commit；临时调试脚本一律放 /tmp，
     只有正式交付物才进 `backend/scripts/`（round32 教训：scripts/ 下建调试文件 →
     凭据失效 → pre-commit 连跑 3 次全量）。无凭据或代码已变更则正常跑全量。
4. **commit + push**：
   - **选择性 git add 白名单（强制，AGENTS.md「多会话并行」约定）**：逐个列文件
     `git add <file>...`，**严禁 `git add -A` / `git add .`**——并行会话（工具链升级等）
     的半成品会混入提交（round42 主 commit 内容错位/丢失，f5ed47d 补救教训）。
     commit 前必看 `git status` 逐项确认 staged 清单。
   - commit message 用**英文**（标题 + 正文，commit-msg 钩子硬拦截中文字符），格式遵循
     **AGENTS.md「Commit message 规范」（2026-08-29 强制）**：
     * 标题 ≤72 字符：`<模块>: <动词> <对象>`（如 `Round52: implement plans A-F for R170-R178 fixes and enhancements`）；
     * 正文 4-7 段：`## Implementation`（file:line + 关键函数）/ `## Verification`
       （pytest 行数 + 实测数据）/ `## Risk` / `## Out of scope` / `Refs: <doc path> (commit)`；
     * ⚠️ **commit 必须经 Git Bash 执行**：PowerShell 直接 `git commit` 报
       `cannot spawn .githooks/pre-commit`（pre-commit 是 sh 脚本）。命令模板见 AGENTS.md。
   - push 到远程
5. **收尾**：用 `remember` 更新 memory（round 实施轮结论 + commit 号 + 验收口径）
   **并回写 round 文档决策节**（已实施项标 commit 号、暂缓项保持登记）——
   round52 先例：docs 收口 commit `2cd9e1d` 随实施 commit 同批完成。
   回写落点：**决策节状态列**（拍板→已实施/已闭环）为主；若文档有独立验证矩阵，
   同步把对应行结论列更新为「✅ 实施确认（commit XXXX）」——两处都改，防止
   「决策节说做了、矩阵还挂着 FAIL」的状态分裂。
```

## 预期行为对照（反假完成）

| 检查 | 怎么做 | 假完成的信号 |
|---|---|---|
| 真实调用 | `rg` 调用点（前端/路由/任务/其它模块） | 0 调用 = 脚手架 |
| 非兜底 | 运行时验证走真实端点、断言关键字段**实际值** | 全默认/全"暂无" = 假实现 |
| 负向断言 | 测试含「全兜底时不得报 N/M 正常」类用例 | 恒绿宽松断言 = 抓不住假 |
| 契约一致性 | 接口变更项 `rg`/对照 api-contracts/ 契约文件已同步更新（契约先行） | 实现改了契约没改 = 断裂潜伏 |
| 拍板范围 | 实施清单 = 文档决策节已拍板项；暂缓项跳过并注明 | 越权实施暂缓项 = 违背用户决策 |
| 全量只跑一次 | 开发期跑受影响测试（引擎改动含不变量全家桶）；验收期全量 1 次 + 立即 mark | 同一套件跑 2-3 遍 = 流程没遵守 |
| 凭据纪律 | 全量后 `tests_ok_marker.py --mark`，之后不再动 backend/ 文件；被拦先 `check` 定位 | 凭据失效还在反复全量 = 没查指纹 |
| 后端生命周期 | 单自包含任务起→验→杀；验证前先 `curl /health`；不杀用户后端 | 反复起停/误诊崩溃 = 过程混乱 |
| 环境性失败 | 限流/fork/新闻源 0 条等复跑确认非回归，对照既有基线归类 | 直接放过或无限重试 |

## 关联

- 巡检：`cd backend && python scripts/patrol.py --full`（L1-L5）
- 全量测试凭据：`backend/scripts/tests_ok_marker.py`（mark/check）
- 反假完成机制：AGENTS.md「反假完成机制」章节
