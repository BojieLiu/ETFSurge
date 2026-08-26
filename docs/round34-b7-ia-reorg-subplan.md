# Round34-B7 全域 IA 重组子方案 v2（实施标准 · 待最终批准）

> **状态**：v2 修订完成——已并入用户六项批复（2026-08-26）、三轮代码取证纠错、
> 重大修改项细化设计、回滚预案与分批提交边界。对照 `docs/design-checklist.md`
> 八项自查见 §8。**批准后按 §5 三段提交边界实施，预计 1 天。**
>
> 上游依据：round34 §9.18 方案 A / §10.2-B7 前置条件；round35 FE5 随本批执行。

## 0. v1 → v2 修订记录

| # | 类型 | 内容 |
|---|---|---|
| 1 | **事实纠错** | FactorModelView 并非「不可达死功能」——它被 DashboardAiTools 内嵌为默认首屏（`v-if="!activeCoreFeature"`，:119），唯一消费者即 AiTools |
| 2 | **事实补全** | DashboardAiTools 的宿主是 PortfolioAnalysis 的 `'tools'` 标签页（非独立页面）：`:active="activeTab==='tools'"` + `@applied="refreshData"`；组件内部**零 router 依赖**（纯 props/events，路由化无内部导航迁移成本） |
| 3 | 事实补全 | AnalysisView / PortfolioManager 是 PortfolioAnalysis 的内嵌分区组件（非死代码） |
| 4 | 决策落定 | 六项批复写入：组合摘要条 / 重定向兜底 / FactorModelView 挂 `/system/factors` 且 AiDesign 内嵌改跳转 / 子分组归位 / catch-all 404 / meta.title 修复 |
| 5 | 新增细化 | §4.1 组合摘要条完整设计（数据源/props/四态）；§4.2 AiDesign 路由态拆分细则；§4.3 完整路由表与重定向矩阵；§4.4 回滚预案；§4.5 三段提交边界 |
| 6 | 新增发现 | TaskIndicator 存在 `/?designId=` 深链推送，但**全库无 `route.query.designId` 消费者**（死查询参数）——本批顺带迁移修正 |

## 1. 现状盘点（v2 全部经代码取证）

### 1.1 路由表（router/index.js，7 条）

| 路径 | 组件 | 目录 | 备注 |
|---|---|---|---|
| `/` | Dashboard | views/ | 内容越界（持仓/盈亏混入，§2 迁出）|
| `/portfolio-analysis` | PortfolioAnalysis | **components/** ✗ | meta.title 空串；内含 holdings/tools/analysis 三 tab |
| `/market-analysis` | MarketAnalysis | views/ | 不变 |
| `/news` | NewsView | **components/** ✗ | — |
| `/token-monitor` | TokenMonitor | **components/** ✗ | — |
| `/source-monitor` | SourceMonitor | **components/** ✗ | — |
| `/admin/config` | ConfigView | views/ | 路径分组不符 IA 目标 |

### 1.2 组件消费图（rg 实测）

```
views/Dashboard.vue ──→ GlobalIndicesStrip（唯一消费者，减负后仍保留指数条）
components/PortfolioAnalysis.vue ──┬→ DashboardAiTools（tools tab，:25）
                                   ├→ AnalysisView（分区）
                                   └→ PortfolioManager（分区）
views/DashboardAiTools.vue ──→ FactorModelView（默认首屏 :119，唯一消费者）
App.vue ──→ TaskIndicator（全局任务指示器）
```

- **AiTools 零 router 依赖**：`useRoute/router/router-link` 全无——提升为路由页无内部导航迁移。
- **死深链**：TaskIndicator `router.push({ path:'/', query:{ designId } })`，但 `route.query.designId` 全库零消费者（任务详情实际经 taskStore 状态传递）。

### 1.3 基建现状（无需动）

- nginx.conf:15 已有 `try_files $uri $uri/ /index.html`——history 深链回退就绪，**服务端零改动**。
- PWA：vite-plugin-pwa `autoUpdate` + `globPatterns:['**/*.{js,css,html,...}]`——文件改名/新增自动再生 precache manifest，**无需手工维护 sw**；验收含一次 sw 更新确认。
- 受影响 spec 实测 7 文件（§5 逐文件列明）。

## 2. 页面职责矩阵（定稿 · 含批复结论）

| 页面 | 路由（目标） | 职责边界 | 迁入 | 迁出 |
|---|---|---|---|---|
| **市场概览** | `/` Dashboard | 指数条 + 自选摘要 + AI 快捷卡 + **组合摘要条（新）** + 任务指示器 | ← 摘要条新组件 | → 持仓卡片/分配饼图/现金卡片/盈亏明细表/CRUD（全部移交组合页）|
| **组合分析** | `/portfolio-analysis` | 持仓 CRUD + 分配/盈亏/历史全权；tabs 收敛为 holdings/analysis | ← Dashboard 迁出的持仓+盈亏区块 | → tools tab 移除（AiDesign 独立）|
| **行情分析** | `/market-analysis` | 不变 | — | — |
| **AI 设计** | `/ai`（新一级导航） | 设计向导/历史/策略检查；默认首屏改为**功能导航卡网格**（替代原 FactorModelView 占位）；因子模型入口改 `router-link` 跳系统分组 | ← DashboardAiTools 升级（改名 AiDesign.vue）| → FactorModelView 移交系统分组 |
| **资讯** | `/news` | 不变 | NewsView 归位 views/ | — |
| **系统·Token** | `/system/token` | 不变 | TokenMonitor → views/system/ | — |
| **系统·数据源** | `/system/sources` | 不变 | SourceMonitor → views/system/ | — |
| **系统·因子模型** | `/system/factors`（新挂） | FactorModelView 独立可达（批复 3A） | FactorModelView → views/system/ | AiDesign 内嵌改跳转链接 |
| **系统·配置** | `/system/config` | 不变平迁 | ConfigView → views/system/ | — |

## 3. 迁移清单（文件级）

### 3.1 git mv（保历史）

| 源 | 目标 |
|---|---|
| components/NewsView.vue | views/NewsView.vue |
| components/PortfolioAnalysis.vue | views/PortfolioAnalysis.vue |
| components/SourceMonitor.vue | views/system/SourceMonitor.vue |
| components/TokenMonitor.vue | views/system/TokenMonitor.vue |
| components/FactorModelView.vue | views/system/FactorModelView.vue |
| views/DashboardAiTools.vue | views/AiDesign.vue（改名）|
| components/AnalysisView.vue | components/portfolio/AnalysisView.vue（子分组）|
| components/PortfolioManager.vue | components/portfolio/PortfolioManager.vue |

### 3.2 components/ 根终态（FE5 验收口径）

仅剩全局共享件：`GlobalIndicesStrip.vue`、`TaskIndicator.vue`、`TaskProgress.vue` + 目录 `ui/ dashboard/ design/ market/ analysis/ portfolio/`。**rg 断言：根目录 .vue 文件数 ==3。**

## 4. 重大修改项细化设计

### 4.1 组合摘要条 PortfolioSummaryStrip.vue（新组件，批复①）

- **位置**：Dashboard 指数条之下、自选摘要之上；`components/dashboard/` 分组（页面局部件不入根）。
- **数据源**：复用 useDashboardData 既有 `fetchPnl()` 响应——**零新增网络请求**。Props：`{ pnlOn: number, pnlOff: number, weightedChange: number, totalAmount: number, loading: boolean }`（全部来自现有 computed）。
- **展示**：一行四段式 `总资产 ¥X · 当日盈亏 ±¥Y (+Z%)`，红涨绿跌用 theme token（`.text-up/.text-down`）；整条可点击 → `router.push('/portfolio-analysis')`。
- **四态**：
  - loading：骨架灰条（高度固定防 CLS）
  - error（daily-pnl 失败）：灰行「盈亏数据暂不可用 · 点击重试」→ 触发 fetchPnl 重跑
  - empty（两仓 allocations 均空）：「还没有持仓 · 去组合页添加」引导跳转
  - slow：随主 loading 态，不单独计时（数据源同源）
- **负向验收**：接口失败时不得渲染 ¥0.00 冒充成功（沿用 R29/R45 诚实降级口径）。
- **vitest**：四态各一 + 点击跳转断言（mock router）。

### 4.2 AiDesign 路由态拆分（批复③关联）

现状耦合：`<DashboardAiTools @applied="refreshData" :active="activeTab==='tools'" />`（PortfolioAnalysis :25）。

| 耦合点 | 迁移方案 |
|---|---|
| `:active` 门控 | 删除 prop——路由挂载即激活；组件根 `v-if="active"` 外壳随之移除 |
| `@applied="refreshData"` | 应用方案成功后需刷新组合——改为组件内直调 `usePortfolioStore().fetchEtfs('on_exchange'/'off_exchange')`（store 是唯一真相源，无父组件可回调）；`defineEmits(['applied'])` 同步删除 |
| 默认首屏 | 原 `v-if="!activeCoreFeature"` 渲染 FactorModelView——改为**功能导航卡网格**（设计向导/历史方案/策略检查/因子模型跳转卡四张，复用既有卡片风格）；`activeCoreFeature` 各分支不变 |
| FactorModelView 入口 | 内嵌移除 → 导航卡 + 页内说明位均改 `<router-link to="/system/factors">` |
| meta | `meta:{ title:'AI 设计', description:'AI 组合设计、历史方案与策略检查' }` |
| PortfolioAnalysis | tabs 数组移除 tools 项（剩 holdings/analysis）；import 与 `<DashboardAiTools/>` 行删除；`refreshData` 若无其它调用者一并清理 |

### 4.3 路由表与重定向矩阵（完整目标态）

```js
// router/index.js 目标态（节选）
{ path: '/',            name: 'dashboard',          component: () => import('../views/Dashboard.vue'), meta: { title: '市场概览' } },
{ path: '/portfolio-analysis', name: 'portfolio-analysis', component: () => import('../views/PortfolioAnalysis.vue'), meta: { title: '组合分析' } },   // 修空 title
{ path: '/market-analysis', /* 不变 */ },
{ path: '/ai',          name: 'ai-design',           component: () => import('../views/AiDesign.vue'), meta: { title: 'AI 设计' } },
{ path: '/news',        name: 'news',                component: () => import('../views/NewsView.vue') },
{ path: '/system/token',   name: 'system-token',     component: () => import('../views/system/TokenMonitor.vue') },
{ path: '/system/sources', name: 'system-sources',   component: () => import('../views/system/SourceMonitor.vue') },
{ path: '/system/factors', name: 'system-factors',   component: () => import('../views/system/FactorModelView.vue') },
{ path: '/system/config',  name: 'system-config',    component: () => import('../views/system/ConfigView.vue') },
// 重定向（保书签）
{ path: '/token-monitor',  redirect: { name: 'system-token' } },
{ path: '/source-monitor', redirect: { name: 'system-sources' } },
{ path: '/admin/config',   redirect: { name: 'system-config' } },
// 兜底（批复⑤）
{ path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFound.vue'), meta: { title: '页面不存在' } },
```

- 新增 `views/NotFound.vue`（极简：图标 + 文案 + 回首页按钮，≤30 行）。
- TaskIndicator 深链修正：`router.push({ path:'/portfolio-analysis' })` 不变；`{ path:'/', query:{designId} }` → `{ path:'/ai' }`（死查询参数消除，登记于 commit message）。
- App.vue 导航分组：`市场概览 / 组合 / 行情 / AI 设计 / 资讯 / 系统▾(Token·数据源·因子·配置)`；active 态按 `route.name` 前缀匹配（`system-*` 高亮「系统」组）。

### 4.4 回滚预案

- 纯前端结构变更，零数据迁移、零 API 变更、零服务端配置——回滚 = `git revert` 对应段 commit（逆序 C3→C1，见 §5）。
- 每段 commit 独立可 revert：C1 归位后若发现漏网引用，revert 即恢复原路径；C2 先行时 AiDesign 仍在原 tab 可独立运行，C3 抽离后 PortfolioAnalysis 无 tools tab 亦可独立运行——三段互不依赖对方存在性。
- PWA autoUpdate 用户侧自动跟随，无缓存回滚负担。

### 4.5 提交边界（三段，每段独立可验收）

| Commit | 内容 | 独立验收 |
|---|---|---|
| **C1 结构归位** | §3.1 全部 git mv（含 AiDesign 改名——仅改文件名，路由仍走原 tools tab 内嵌）+ 路由表重写（**不含 /ai 行**）+ import 路径批量更新（rg 每个移动文件名全库扫，含 spec；**被移文件自身的相对导入同步修正**——入 views/system/ 者深 +1 层）+ 3 条重定向 + 404 + meta.title | build 绿；vitest 全绿；手查 8 条路由可达（无 /ai）+ 3 条重定向生效；tools tab 仍正常工作 |
| **C2 Dashboard 减负** | 持仓/盈亏区块迁组合页 + PortfolioSummaryStrip 新增 + 四态 | Dashboard 首屏请求数不增（R110 守卫测试继续绿）；摘要条 vitest ×5；组合页功能回归 |
| **C3 AiDesign 升路由** | 路由表追加 /ai 行 + tools tab 移除 + applied→store 化 + 默认首屏导航卡 + /system/factors 路由行 + TaskIndicator 深链修正 | /ai 直达且 tools tab 不复存；应用方案后组合列表刷新（store 化实证）；因子页直达；TaskIndicator 两跳转实测 |

依赖说明：C1 是 C2/C3 的地基（文件已在新路径）。**防双挂载关键约束：`/ai` 路由行与 tools-tab 移除必须同在 C3 原子完成**——C1 只改名不挂路由，杜绝过渡期双入口。C2 与 C3 相互独立。

## 5. 回归测试范围（逐文件）

| 文件 | 改动 | 断言要点 |
|---|---|---|
| router.spec.js | 主战场：路由表快照重写 | 10 条路由 name/path/component 断言 + 3 条重定向 + 404 兜底 + meta.title 非空 |
| NewsView.spec.js | import 路径 `../components/`→`../views/` | 原断言不动 |
| TokenMonitor.spec.js | 同上（views/system/） | 原断言不动 |
| SourceMonitor 相关 spec | 同上 | 原断言不动 |
| PortfolioAnalysis.spec.js | import 路径 + tools tab 用例移除/改写 | tabs 收敛断言 |
| DashboardAiTools.spec.js | 改名 AiDesign.spec.js；active-prop 用例删除；applied 用例改 store 断言 | 应用后 fetchEtfs 双仓被调 |
| TaskIndicator.spec.js | 深链断言更新 | push('/ai') 替代旧 query 写法 |
| changeClass.spec.js | 仅 import 路径 | 不动 |
| **新增** NotFound.spec.js / PortfolioSummaryStrip.spec.js | 新组件四态 | 见 §4.1 |

Playwright smoke specs：URL 常量批量更新（16 spec 扫一遍，仅路径字符串替换）。

## 6. 总验收口径

1. `rg` 结构断言：components/ 根 .vue==3；路由表全部指向 views/；
2. 手工走查：9 路由直达 + 3 重定向 + 404 任意乱径 + 导航分组高亮正确；
3. 行为回归：应用方案后组合刷新、任务指示器两跳转、摘要条四态、R110 单飞守卫测试继续绿；
4. 三件套：vitest 全绿 / npm run build 绿 / patrol --diff 全绿（后端零改动）；
5. PWA：构建产物 precache manifest 含新文件名，控制台无 sw 更新报错。

## 7. 工作量与顺序

- C1 ≈ 0.5d（移动+路由+spec 批量）→ C2 ≈ 0.25d → C3 ≈ 0.25d；合计 ~1 天。
- 实施窗口不限交易时段（纯前端结构）；perf 对照（Dashboard 首屏）建议盘中复测一轮作 C2 附注。

## 8. design-checklist 八项自查（v2 结论）

| # | 项 | 结论 |
|---|---|---|
| 1 | 可行性探针 | 全部关键假设已经代码取证闭合（消费图/router 依赖/dead-query/nginx/PWA），无遗留未探假设 |
| 2 | 证据链 | §1 每条含 file:line 或 rg 结果；v1 两处错误事实已在 §0 声明纠正 |
| 3 | 验证窗口 | 结构变更无时段依赖；perf 对照注明盘中 |
| 4 | 非兜底数据 | 摘要条四态显式定义，失败态禁止 ¥0 冒充 |
| 5 | 真实调用点 | 移动组件均有实测消费者；删除的内嵌/prop 在 §4.2 逐点交代去向 |
| 6 | 四态 UI | 新组件 §4.1 全定义；存量组件仅移动不改行为 |
| 7 | 复杂度审计 | 零新增网络调用（摘要条复用既有响应）；零新增端点 |
| 8 | 已知问题模式 | round14 五类盲区过筛：契约盲区 N/A（无 API 变更）、CSS 随 scoped 文件走、降级门禁沿用 R29/R45 口径 |

## 9. 开放问题（均已给推荐，实施前需一句确认）

| # | 问题 | 推荐 |
|---|---|---|
| 1 | AiDesign 默认首屏导航卡的具体卡片集合 | 四张：新建设计/历史方案/策略检查/因子模型——如需增删请在批准时注明 |

## 10. 评审记录（多轮收敛轨迹）

| 轮次 | 方式 | 发现 → 处置 |
|---|---|---|
| R1 | design-checklist 八项对照 + 全库代码取证（消费图/router 依赖/dead-query/nginx/PWA/spec 清单） | v1 两处错误事实（FactorModelView「不可达」实为内嵌；AiTools 宿主是组合页 tab 非 Dashboard）→ §0 纠错；新增 §4 细化设计与 §5 逐文件清单 |
| R2 | 实施者模拟走查（逐 commit 可执行性） | C1/C3 阶段矛盾（改名在 C1 但 /ai 在 C3 → 过渡期双挂载窗口）→ §4.5 补「防双挂载原子约束」；TaskIndicator 死深链发现 → 纳入 C3 |
| 收敛判据 | 无 P0（不可实施项）/P1（高危遗漏）遗留；开放问题仅剩 1 个 P2 级（导航卡集合），已给默认推荐 | **达标** |
