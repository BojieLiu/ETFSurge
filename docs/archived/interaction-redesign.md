# 组合设计 / 策略检查 / 任务历史 交互状态机重构设计（评审稿）

> 目标：消除「失败界面无法退出」「失败任务在历史列表隐形」「WS/轮询双写竞态」三类
> 问题。**本稿只设计，不实施**。
>
> 前提约定（沿用现状，不扩范围）
> - 同**时容错**一次提交（后端 `design_semaphore` 已串行，前端同样只允许一个 running design task）。
> - 任务与方案记录是**两个持久化实体**：`tasks` 表（任务生命周期，含失败）和
>   `portfolio_designs`/`strategy_check_records`（成功产物）。
> - 不改后端交互契约（`design-async / tasks/{id} / timeline / ws`），只改前端组装与状态呈现。

---

## 1. 问题清单（现状→目标）

| # | 现状问题 | 根因 | 目标行为 |
|---|---------|------|---------|
| P1 | 失败后无法从失败界面二次触发；进去还是上次失败卡 | `designStep` 反复用 `''` 表示失败、exit 把 loading 当 loading 持久化、重进靠 onMounted 猜 | 失败是否入 `terminal` 状态，可一键重试/重开 |
| P2 | 失败任务在历史列表隐形 | timeline 只查 designs/checks，不查 tasks；taskStore 失败即 removeTask | 历史列表能看到 failed 设计任务（含错误文案） |
| P3 | WS完成 与轮询 双写 progress/result，竞态重复 fetch | 两个监听器同时写同一 ref | 单一「derive 完成」函数做幂等收尾 |
| P4 | 退出即持久化 loading，语义错 | 把运行态当终态持久化 | 只持久化可恢复的「完成(result)」与「退出时可续(loading)」；failed/pending 不复位 |
| P5 | enterDesignMode 里 60 行「查重 running+猜后端重启」 | on 用 age 猜 | 统一收敛：进来自读一次 /tasks/{id} 确认真实状态 |
| P6 | loading 文案「3秒后返回」是假承诺 | 纯文本 | 真倒计时 or 只有按钮；失败必返回可操作态 |
| P7 | 策略&设计两套 timer（designPoll/Timeout、strategyPoll/Timeout）+ 双监听 | 散落 timer | 单一驱动 + 兜底（见 §3） |

---

## 2. 单一状态机设计（设计工具）

**不**再用 `designStep + designFailed + ...` 散碎 ref，收敛为一个**不可变快照**：

```ts
type DesignUiStatus =
  | { kind: 'idle' }                        // 未开始（= 工具列表）
  | { kind: 'drafting' }                    // wizard：填参数
  | { kind: 'running';  taskId: number; designId?: number; progress: number; stage_label: string }
  | { kind: 'result';   result: DesignResult }          // 成功产物（可持久化）
  | { kind: 'failed';   taskId: number; errorLabel: string; canRetry: boolean }
```

- `activeCoreFeature` 保留（决定顶层显示 design/strategy/history/tools-list）。
- `DesignLoading` 的 `failed` prop 来自 `kind==='failed'`，**不再**用 `designFailed` 字符串。
- 一切复位 = `setDesign({ kind:'idle' })`。不再有 `designFailed.value=''` 散点。

### 状态转移

> 决策（已拍板）：
> - **_D1 失败行为_**：失败卡直接带「重试一次」按钮，同时保留「返回」——失败是终态、可停留查看原因，也可一键重试/返回。
> - **_D2 失败历史可见性**：后端 `/portfolio/timeline` join `tasks` 表，失败 design 任务在历史列表**永久可见**（跨刷新）。（动后端契约，属 O12 实施范围）
> - **_D3 running 退出续跑**：设计运行中退出工具 → 持久化 `{kind:'running',taskId}` → 再进入恢复 loading 续看同任务进度（任务不丢）。

```
idle ──点击「智能设计」──▶ drafting
drafting ──提交 capital──▶ running{taskId}
running ──task completed──▶ result{designId}
running ──task failed(超时/后端)──▶ failed{message, canRetry:true}
running ──长时间无响应(180s兜底)──▶ failed{message:'方案生成时间过长…', canRetry:true}
result ──点击「重新生成」──▶ running{新taskId}
failed ──点击「重试一次」(D1)──▶ running{新taskId, 复用参数}
failed ──点击「返回」/`drafting`──▶ idle（=退出工具列表）
result ──点击「返回/关闭」──▶ idle（=退出工具列表）
running ──退出工具──▶ 持久化 {kind:'running',taskId}（D3）→ 再进入 ├─ running 恢复续 loading
```

### 关键不变量
1. **一次最多一个 running design**。`running{taskId}` → 只有它自己的终态回调能推进到 result/failed。
2. **失败是终态，且必带 canRetry（D1）**。可从 failed 直接「重试一次」（重新走 running，复用参数），也可「返回」退出到 idle。
3. **持久化的只有 `result` 与运行中的 `running{taskId}`（D3）**。failed/idle **不持久化**——失败不复位（不进 localStorage）。

---

## 3. taskStore：任务生命周期收敛

问题本质是「任务生命周期」与「组件 UI 状态」纠缠。建议把 taskStore 收敛成可靠单一来源：

- `taskStore.tasks` 保持（被 TaskIndicator / 历史列表共用），但**只增不改写终态**：
  - 新建 → `add`
  - 后端 `completed` → 转向 completed，但**保留 record_id**
  - 后端 `failed` → 转向 failed，`errorMessage` 原样保留 → 失败任务**不再是"隐形的 running"**，历史列表能显示。
  - 移除只由显式清理（用户/超限/prune）触发，**不因失败而 removeTask**。
- WS 回调与轮询**收敛到一个 `finalizeTask(task)`**：
  - WS 来了就发 finished 事件；轮询只兜底，看得到则 `finalizeTask`，看不到则连续 N 次错误才判 `failed`。
  - 用 `taskId` 防重复 finalize（finalizedSet）。

---

## 4. 历史列表数据源（P2/P2+ 修复设计）

`/portfolio/timeline` 后端 join `tasks` 表（**D2**），让失败/运行中的 design 任务在历史列表**跨会话可见**：

```
历史列表 = 后端 timeline（designs+checks+tasks的设计任务，按 created_at desc）
         ∪ taskStore.tasks（本会话仍 running / 近 N 分钟内的 failed）
```

- **D2 后端**：`/portfolio/timeline` 从 `tasks` 表并入 `task_type='design'` 的任务，失败项带 `status='failed'` + `error_message`；已成功且有 design 记录的按现有走（不重复）。
- 展示分层：**运行中**显示「生成中…」+进度；**失败**显示「❌ 失败 + error_message」（点击弹错误详情的现有 modal），并提供「重试」入口；**成功**可点击看方案（现状）。

### 运行中退出续跑（D3）
- 退出时持久化 `{kind:'running', taskId}`；再进入 onMounted 自读一次 `/tasks/{taskId}`，若仍 running → 恢复 loading 续看；若已完成 → 走 `finalizeTask` 直达 result；若失败 → 转 failed 卡（可重试）。三者都不再"凭空猜"（替代现状用 age 猜后端重启）。

---

## 5. 定时器与资源清理

- 单一 `designTick` 由 poll interval 驱动；WS 优先。
- `beforeUnmount` / `exitCoreFeature` 统一 `clearAllTimers()`。
- 移除「180s 后 exitCoreFeature」这种「把用户踢回列表」的行为——改为 180s 推不到 result 则转 `failed(canRetry)`，**不改变顶层 feature**，用户停留看失败原因。

---

## 6. 测试防护缺失（新增用例）

| 用例 | 断言 |
|------|------|
| failed 态 → 点击重试 → 重新 running（不再回退 loading) | `kind==='running'` 且带新 taskId |
| failed → 关闭 → idle → 再次进入 → 回到 idle（不再残留失败） | on 进入不恢复 failed |
| WS 完成 + 轮询同时到 → 仅 finalize 一次 | fetchDesignDetail 只调一次（mock 计数） |
| 失败任务在历史列表可见（含 error_message + 可点错误详情） | timeline∪running 含 failed 项 |
| running 退出后可恢复续跑（同任务） | 持久化为 {kind:'running', taskId}，onMount 恢复 loading |

---

## 7. 是否改动构造函数 / 破坏项

- Props `active`（O15 用）保持不变，仍复位到 idle。
- `regenerateDesign`/`retryReport`/`applyPlan` 与 `emit('applied')` 契约不变。
- 后端 API 契约不变（只是前端不再依赖 `designFailed` 字符串）。
- 破坏面局限在 `DashboardAiTools.vue` 内部状态机 + `task.js` 的小调整。

---

## 8. 交付边界（本次只设计）

以下**不实施**，仅作评审：
- §2-§5 状态机与数据流重构（前端核心改动）
- §6 三组关键单测
- §3 taskStore 生命周期收敛

请评审：这套设计是否覆盖了你遇到的「失败无法重置 /历史隐形 / 双竞态」三个痛点；状态机拆得是否够；`running 持久化续跑` 是否有必要（可降级为「退出即丢 running 提示」）。