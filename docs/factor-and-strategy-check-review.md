# 因子模型 0 有效 与 策略检查质量问题分析

> 审查日期：2026-08-01
> 审查对象：因子模型页面（0 有效）+ 策略检查（场内组合流程 + id=210 报告）
> 证据：`data/portfolio.db`（strategy_check_records id=208/209/210）+ 前后端代码链

## 一、问题 1：因子模型页面 0 有效，是否合理？

### 1.1 现象

- 因子模型页面顶部 `summary.valid = 0`（"有效 0"），`no_data` 30 左右，仅 china_specific 3 个 static 因子有计数；
- 各分类 `valid_count` 全 0，avg_ic 为 `--`；
- 用户疑问：33 个因子全部无效，是否合理？

### 1.2 结论：不合理，但非"因子失效"，而是 IC 数据管道缺陷

**状态判定逻辑（factors.py:140-154）**：
- `ic_value is None` → `no_data`（"IC 未累积（样本<3）"或"数据源未接入"）；
- `abs(ic_value) >= threshold(0.02)` → `valid`；
- 页面"有效"数 = `status == 'valid'` 的因子数（factors.py:200 `valid_count`，:220 `total_valid` 汇总）。

**根因链（与 `round2-unfixed-fix-plan.md` U3/U4 同源）**：

1. **`_last_ic_batch` 只在带 `market_data` 的 compute 时更新**（factor_registry.py:1216-1219）——`ic_batch = ic_tracker.compute_periodic_ic(result, market_data, window=1)`，`market_data is None` 时**整个 IC 更新被跳过**；
2. **compute_periodic_ic 前置返回**（ic_tracker.py:142-148）：`not factor_values or not market_data` → `{}`；`len(forward_rets) < 3` → `{}`（forward_returns 需 3+ 标的的日频收益序列）；**容器刚启动/数据源熔断时 market_data 缺失或样本<3 → 返回空**；
3. **全 0 批次覆盖**（ic_tracker.py:173-181）：即使有样本，`len(common) < 3` 的因子被硬编码 `ic_results[code] = 0.0`；`_last_ic_batch` 被全 0 dict 覆盖后，factors.py `abs(0) >= 0.02` 为 False → **全部判为 `warn` 而非 `valid`**（等等——0.0 应该判 warn 不是 no_data。但页面显示 0 有效+30 no_data，说明 `_last_ic_batch` 为空 dict 或缺失 key → `ic_val=None` → no_data）。两种状态都导致 valid=0；
4. **IC 计算仅请求驱动**：`GET /factors/active` 只**读取** `registry._last_ic_batch`（factors.py:128），不触发计算；只有带 market_data 的 compute（策略检查/设计/预热）才可能更新——**后台 120s 循环不调 compute**（main.py 的 IC 持久化循环只读 `_last_ic_batch`）；
5. **数据源可达性**：etf_specific 类因子（premium_discount 等）依赖 IOPV/NAV/份额数据，熔断期（sina/tencent/dongfang open）注入失败 → `_data_source_gaps` 标记 → `no_data`（factors.py:146-149）。

**是否合理的判断**：
- **不合理**。33 因子中 30 个被判 no_data、valid=0，是"IC 未累积/数据源不可达"的表现，不是因子本身无预测力。真实因子模型（factor_registry 的 33 维计算）在数据就绪时能产出有效 IC（round3 验证时 factor-health 曾 23/33 live）；
- 页面无任何"数据未就绪/等待累积"的引导文案（只有数字 0），用户无从判断是"因子失效"还是"系统未跑起来"。

### 1.3 修复方案

- **R1（后台周期计算）**：main.py 的 120s 循环内新增 `await factor_registry.compute(...)`（带 market_data 缓存），使 `_last_ic_batch` 周期更新而非仅请求驱动——见 `round2-unfixed-fix-plan.md` U3 R3；
- **R2（防全 0 覆盖）**：ic_tracker.py:177 `len(common) < 3` 时跳过该因子（不写 0.0）；factor_registry.py:1218 的 `if ic_batch:` 守卫**当前已存在**（空批次不覆盖），**真正未实现的是 ic_tracker.py:177 的零填充**——只需修 :177 一处，勿重复加守卫——见 U3 R1/R2；
- **R3（前端空态引导）**：FactorModelView.vue 在 `summary.valid === 0` 时显示"因子 IC 正在累积中（需 ≥3 个交易日样本），当前显示历史计算状态"横幅，并链接到 `sources/health` 排查数据源；
- **R4（验收）**：数据源可用且运行 ≥1 个周期后 `valid ≥ 10`；e2e `section_factor_ic` 断言 valid>0（不再请求驱动）。

## 二、问题 2：策略检查进度"先显示已完成，然后变成加载持仓数据"

### 2.1 现象

- 选择场内组合提交策略检查后，进度页面**先弹出"策略检查已完成"提示**，然后进度条仍显示"加载持仓数据"等中间 stage，最后才进入结果页。

### 2.2 结论：前端 WS 完成通知与轮询 UI 状态脱节

**代码证据**：

1. **checkStrategy 只注册轮询，未注册 WS 完成回调**（DashboardAiTools.vue:437-474，`:456` 才置 `checkingStrategy=false`）——对比 design 流程有 `registerTaskCompletion`（:352），check 流程没有；
2. 后端完成时**同时**推送 WS 与更新任务状态（strategy_check_worker.py:173-181：`update_task(completed)` + `_notify(completed)`）；
3. WS 消息到达 App.vue:203-230 → `taskStore.updateTask(taskId, {status:'completed'})` → **toast"策略检查已完成"**（task.js:126-129）——这是用户看到的"先显示已完成"；
4. 但组件 `checkingStrategy` 仍为 `true`（只有轮询分支 :456 才置 false）→ `StrategyCheckResult` 的 `v-if="loading"` 分支继续渲染 `TaskProgress`（stage 来自 strategyStage，轮询 :447-448 更新）→ 显示"加载持仓数据/数据采集完成"等中间 stage；
5. 直到下一次轮询（3s 后）`task.status === 'completed'`（:449-457，:456 置 false）→ 才真正结束 loading、拉取结果。

**根因**：WS（即时、全局）与轮询（3s 间隔、组件局部）双通道状态不同步——WS 先到的 `completed` 只触发了 toast，没有驱动组件退出 loading 态。

### 2.3 修复方案

- **R1（check 也注册 WS 完成回调）**：`checkStrategy` 中调用 `taskStore.registerTaskCompletion(taskData.task_id, callback)`，回调内拉取 `getStrategyCheckResult` 并置 `checkingStrategy=false`——与 design 流程对称（DashboardAiTools.vue:352 模式）；
- **R2（toast 延迟或由组件控制）**：task.js:126-129 的"已完成"toast 改为**组件进入结果页后**由组件触发（或 WS completed 到达时同时更新组件状态而非仅 toast）；
- **R3（WS 驱动组件状态）**：App.vue 的 WS 处理在 `status==='completed'` 时除了 `taskStore.updateTask`，广播一个 store 事件（如 `task_completed`），`DashboardAiTools` 监听并立即结束 loading；
- **R4（验收）**：策略检查全流程无"先提示完成再停留 loading"现象；toast 与结果页同步出现。

## 三、问题 3：策略检查报告 LLM 超时兜底 + 操作建议无理由

### 3.1 现象（id=210 记录实证）

```
summary: LLM 分析超时（20s 未返回，已用规则引擎兜底）（市态：震荡；因子数据10/10正常）
操作建议（10 条）：
  恒生科技ETF易方达  increase 0.03→0.036 | 因子评分优+技术买入信号，建议增仓
  其余 9 只（中证A500/红利/恒生红利低波/半导体设备/创新药/港股创新药/券商/游戏/黄金）
            hold | 维持现状
risk_warnings: general/info "当前组合风险指标正常，未触发自动警告。"
```

用户疑问：
1. LLM 超时兜底是否合理？（20s 超时太短？）
2. 操作建议除恒科增配外全部"维持现状"且无理由，是否合理？

### 3.2 结论：兜底机制合理（诚实降级），但兜底质量不足

**3.2.1 LLM 超时兜底本身合理**：
- portfolio_service.py:524-541（Z26）内层 20s 显式预算，超时走规则引擎——这是**正确的降级设计**（避免无限等待），且 summary 明确标注"LLM 分析超时…已用规则引擎兜底"（诚实，无伪装）；
- 但 **20s 预算过紧**：设计任务 LLM 预算 240s、免费模型高峰排队常 >90s（task_manager.py:417-418 注释自述），策略检查 20s 与之一致性差——**20s 内 LLM 基本必超时**（本轮 3 条记录 208/209/210 全部 LLM 超时，其中 209 还是"因子数据0/10正常"——LLM 根本没机会跑）。

**3.2.2 操作建议质量不足（核心问题）**：
- `_rule_based_suggestion`（portfolio_service.py:710-753）决策表**只有 2 个动作分支**：
  - `avg_factor > 0.5 && sig=='buy' && !bearish` → increase；
  - `avg_factor < -0.5 && sig=='sell'` → decrease；
  - **其余一律 hold**（:741）；
- **hold 的 reason 恒为"维持现状"**——不解释"为什么维持"（因子分区间、信号中性、regime 约束、与 target 的偏离度）；
- 结果：10 只持仓里 9 只 hold，唯一 increase（恒科）是因为它恰好 `avg_factor>0.5 && buy`——**规则引擎的区分度极低**，几乎退化为"默认持有"；
- **rule fallback 未生成本应作为正文的 report_text**（portfolio_service.py:675-690 的 result dict 无 report_text 键）——见 `round2-unfixed-fix-plan.md` U2。

**3.2.3 风险提示"正常"误导**：
- `_combine_risk_warnings`（:756-764）：LLM 超时无警告 + 规则 `_compute_risk_warnings` 未触发 → 兜底输出 info"当前组合风险指标正常，未触发自动警告"；
- **在 LLM 超时场景下这是误导**——不是"系统评估过风险且正常"，而是"没来得及评估"。用户可能据此放松警惕；
- 且 209 记录"因子数据0/10正常"（因子全空）时也照样输出"风险正常"——**数据缺失与风险正常混为一谈**。

### 3.3 修复方案

- **R1（超时预算对齐）**：策略检查 LLM 预算 20s → 60s（对齐设计任务 240s 的下限），`wait_for` 外包装重试，避免 CancelledError 取消整个 fallback 链（见 `round2-unfixed-fix-plan.md` U2 R3）；
- **R2（rule 决策表增强）**：`_rule_based_suggestion` 增加分档：
  - `avg_factor ∈ (0.2, 0.5)` + buy → "hold（偏多，因子分 0.3x 未达增仓阈值 0.5）"；
  - 相对偏离度：`|current_weight - target_weight| > 20%` → 建议向 target 回归（increase/decrease + 理由"偏离目标权重"）；
  - hold 时 reason 带**具体依据**：`因子分 {avg_factor:.2f}（中性区间），信号 {sig}，维持现状`——不再裸"维持现状"；
- **R3（风险兜底诚实化）**：LLM 超时或因子数据缺失时，`_combine_risk_warnings` 输出 `warning` 级"LLM 分析超时，风险提示基于规则引擎部分数据"而非 info"正常"；因子全空（如 209）时输出"因子数据不可用，风险提示完整性受限"；
- **R4（rule fallback 正文）**：rule 兜底生成 report_text（市态+逐标的建议表+风险）而非仅 suggestions 数组（见 U2 R1）；
- **R5（验收）**：
  - LLM 超时场景下操作建议含 ≥2 种动作（非清一色 hold）、每条 reason 含因子分/信号依据；
  - LLM 超时时风险提示为 warning 级且标注降级；
  - 数据可用时策略检查 10 条建议中 hold 占比 < 80%。

## 四、汇总：三个问题与既有修复文档的关系

| 问题 | 根因 | 关联文档 |
|------|------|---------|
| 因子 0 有效 | IC 请求驱动 + 全 0 覆盖 + 数据源不可达 | `round2-unfixed-fix-plan.md` U3/U4（已含修复方案） |
| 策略检查进度异常 | WS 完成通知与轮询 UI 脱节 | 本文 2.3（新增，前端） |
| 策略检查报告质量 | 20s 超时过紧 + rule 决策表过简 + 风险兜底误导 | `round2-unfixed-fix-plan.md` U2 + 本文 3.3 |

**实施顺序建议**：因子 0 有效（U3 防覆盖）→ 策略检查报告质量（U2 超时对齐 + rule 增强）→ 进度状态机（前端独立小修，可与 U2 并行）。
