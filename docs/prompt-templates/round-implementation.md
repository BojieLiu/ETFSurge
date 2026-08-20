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
2. **工作流**（遵循 AGENTS.md「反假完成机制」+「TDD」+「性能软门禁」）：
   - 先读文档对应章节（问题/根因/方案/验收/负向断言），只实现文档列出的项，不扩大范围
   - 每个改动项：先写能抓住问题的单测（含**能失败的负向断言**）→ 再实现 → 跑该文件测试
   - 实现要求：精确 `file:line` 定位、不改无关代码、不引入脚手架/死代码
   - **数据契约变更（如因子值可 None）必须 `rg` 全库扫消费方**（abs/sum/f"{v:.2f}"/
     isinstance 守卫），防止改动只在测试绿、运行期炸
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
     管理**：把「起后端 → 等 warmup（~60s，先 `curl /health` 确认在线）→ 跑全部验证/
     verify_e2e → 杀后端」放进**单个自包含 bash 任务**（`(python -m uvicorn ... &) &&
     sleep 60 && verify_e2e; kill`），不因单个检查失败反复重启。⚠️ 不要 kill 用户正在
     跑的后端来验证——先起独立实例（换端口或复用 8000 前先确认）；要留持久后端用
     `nohup ... & disown`（Git Bash）或 `start.ps1 -Silent -NoOpen` 且**之后别再
     TaskStop 它的父任务**（TaskStop 会连坐杀整个进程树，曾误诊为「后端崩溃」）。
     撞外部源限流时接受降级并标注「待交易时段复测」，不要无限重试。
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
   - commit message 用**英文**，格式：`feat(scope): RXX-RXX ...` + 每个 R 的英文描述
     （做了什么/为什么）+ 测试与验收结果摘要
   - push 到远程
5. **收尾**：用 `remember` 更新 memory（round 实施轮结论 + commit 号 + 验收口径）
```

## 预期行为对照（反假完成）

| 检查 | 怎么做 | 假完成的信号 |
|---|---|---|
| 真实调用 | `rg` 调用点（前端/路由/任务/其它模块） | 0 调用 = 脚手架 |
| 非兜底 | 运行时验证走真实端点、断言关键字段**实际值** | 全默认/全"暂无" = 假实现 |
| 负向断言 | 测试含「全兜底时不得报 N/M 正常」类用例 | 恒绿宽松断言 = 抓不住假 |
| 全量只跑一次 | 开发期跑受影响测试（引擎改动含不变量全家桶）；验收期全量 1 次 + 立即 mark | 同一套件跑 2-3 遍 = 流程没遵守 |
| 凭据纪律 | 全量后 `tests_ok_marker.py --mark`，之后不再动 backend/ 文件；被拦先 `check` 定位 | 凭据失效还在反复全量 = 没查指纹 |
| 后端生命周期 | 单自包含任务起→验→杀；验证前先 `curl /health`；不杀用户后端 | 反复起停/误诊崩溃 = 过程混乱 |
| 环境性失败 | 限流/fork/新闻源 0 条等复跑确认非回归，对照既有基线归类 | 直接放过或无限重试 |

## 关联

- 巡检：`cd backend && python scripts/patrol.py --full`（L1-L5）
- 全量测试凭据：`backend/scripts/tests_ok_marker.py`（mark/check）
- 反假完成机制：AGENTS.md「反假完成机制」章节
