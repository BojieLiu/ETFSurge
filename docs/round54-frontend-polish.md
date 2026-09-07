# Round54 — 前端 UI 打磨轮（纯静态、不动业务）

> **状态**：设计稿 / 待 review
> **范围**：纯前端 UI 静态调整，不改业务逻辑、不改 API、不动后端
> **触发**：上一会话完成对前端的整体审阅，输出 11 条建议（P0×3 / P1×5 / P2×3），本轮选高 ROI 子集落地
> **设计阶段**：所有改动已在用户浏览器实测截图（既有运行实例）基础上设计；探针命令附 §6

## 1. 目标与边界

### 1.1 目标（用户视角三条硬收益）
1. **路由页头不再重复**：进「组合分析」不再看到「组合分析 → 组合管理 → 持仓」三层标题
2. **Dashboard 首页不再空**：进首页能看到自选股 + 今日热点 + 重要资讯，与"市场概览"meta 描述对齐
3. **手机端可导航**：≤768px 不再"只能回首页"，汉堡菜单提供 5 主页可达

### 1.2 边界（不做）
- 不引入图标库（emoji 维持现状；icon 替换另起 round 评估）
- 不重写 Dashboard 数据流（复用现有 store/composable，不新增 API）
- 不动后端；不改业务路由；不改 i18n（项目当前全中文 UI）

## 2. 设计（必查 8 项）

### 2.1 可行性探针（D1）✅
- 改动前的实测证据：上一会话已读取 11 个文件（App.vue / Dashboard.vue / PortfolioAnalysis.vue / PortfolioManager.vue / AnalysisView.vue / ConfigView.vue / CapitalInputBar.vue / PortfolioSummaryStrip.vue / AiDesign.vue / MarketAnalysis.vue / NewsView.vue / theme.css），并通过 `rg` 跑了 page-header 重复声明、`@media` 断点散点等静态扫描
- 探针命令（§6 复现）：
  ```bash
  rg -n "page-header" frontend/src --type vue
  rg -n "@media \(max-width" frontend/src --type vue
  rg -n "<h1|<h2" frontend/src/components/portfolio/PortfolioManager.vue frontend/src/views/AiDesign.vue
  ```
- 探针结果：见上一会话回复的证据矩阵（11 条建议 + file:line）

### 2.2 证据链（D2）✅
所有结论的 file:line 已在上一会话回复列出。本文档不复述；下面 §3 每条实施项的回查路径附 file:line。

### 2.3 验证窗口（D3）
- 本轮**纯前端静态改动**（CSS + 模板 + 少量 v-if 状态），不依赖交易时段
- 验证窗口：本机浏览器实测 + `npm run build` + `npm test` + `verify_e2e`
- **非交易窗口兜底**（review 意见 #4）：Dashboard 3 区块复用 `useDashboardData` / `market store` / `useNewsWS`，非交易时段各区块可能落入空态——验收口径为「空态有 CTA（去组合页/去资讯页），非白屏/非报错」，不影响纯静态改动验收
- 非窗口限制：不影响；行情字段未动

### 2.4 非兜底数据（D4）✅
- P0-3 Dashboard 扩充的 3 个区块（自选/板块/资讯）复用现有 `useDashboardData` / `stores/market` / `stores/news`，**不引入新 API、不写 mock**
- 探针：grep 新增组件的引用路径，确保接到现有数据源（见 §3.3）

### 2.5 真实调用点（D5）✅
- 大部分改动是「在已有调用链上做 UI 收敛」，0 新增端点/0 新组件外部入口
- Dashboard 扩充 3 个区块的组件（`WatchlistPanel` / `SectorHeatMap` / `NewsDigestList`）都是 Dashboard 唯一 mount
- `NewsDigestList` 是本轮唯一新增小组件（理由与权衡见 §3.2），仅 Dashboard 使用

### 2.6 四态 UI（D6）✅
- 现有 `PortfolioSummaryStrip` 已是四态标杆（loading skeleton / error / empty / ready）
- 现有 `WatchlistPanel` / `SectorHeatMap` 自身有完整四态（设计稿已确认）
- Dashboard 扩充复用时直接继承其四态
- `NewsDigestList` 新组件**自带四态**（loading / empty / error / ready），不引用旧组件
- 汉堡菜单：按钮 `aria-expanded` + `<nav role="menu">` drawer（**不用** `aria-modal`——menu 模式，见 §3.3），开/关二态

### 2.7 复杂度审计（D7）✅
- 0 新增 API 端点；Dashboard 挂载期间 `/ws/news` 连接 +1（`NewsDigestList` 内联 useNewsWS，见 §3.2 权衡），已知可接受
- 0 新增 DB / 文件 IO
- 汉堡菜单纯客户端 state（`ref(false)`），无外部依赖

### 2.8 已知问题模式（D8）✅
- 不触"格式断言 / mock 理想输入 / 契约盲区"——本轮无契约改动
- 不触"CSS 零覆盖"——所有 CSS 走 `theme.css` 令牌或 scoped
- 不触"降级无门禁"——无降级路径变化
- **新盲点自查**：汉堡菜单在 `<768px` 时替代完整 nav——确认 `aria-controls`、`aria-expanded`、`Esc` 关闭、点击外部关闭、焦点陷阱（Tab 在菜单内循环）全部就位

## 3. 实施清单

### 3.1 P0-A：去除重复页头（影响 3 文件）

**改动**：
- `frontend/src/components/portfolio/PortfolioManager.vue:4-7` —— 删除内嵌 `<header class="page-header">`（含 `<h1>组合管理</h1>` 与 `<p class="page-description">`）
- `frontend/src/components/portfolio/PortfolioManager.vue:929` —— 删除对应 `.page-header { margin-bottom: var(--space-2); }` 单行 CSS（`.page-title` / `.page-description` 类保留，grep 确认无其他引用后再决定）
- `frontend/src/components/portfolio/AnalysisView.vue:4-7` —— 同上删除 `<header class="page-header">`
- `frontend/src/components/portfolio/AnalysisView.vue:589` —— 删除对应 `.page-header { margin-bottom: var(--space-2); }` 单行 CSS
- `frontend/src/views/system/ConfigView.vue:3-6` —— 改写为 AppCard 风格：
  ```vue
  <AppCard class="config-header-card">
    <template #header>
      <h2 class="config-title">系统配置</h2>
      <p class="config-subtitle">{{ description }}</p>
    </template>
  </AppCard>
  ```
  并删除 line 169 的 `.page-header h1` CSS

**测试断言同步核查**：执行删除前必须跑 `rg "\.page-header" frontend/src/test/` 确认断言仍命中 App.vue 全局页头（本轮所有改动删的是子组件内嵌，不动 App.vue，断言应继续命中）。如有任何断言失效则同步更新（已知 `frontend/src/test/App.spec.js:232-233` 是 App.vue 全局页头断言，本轮不影响）。

**验证**：
- 路由「/portfolio-analysis」进入「持仓」tab：只剩 App.vue 全局页头「组合分析 / 组合数据持久化…」
- 路由「/portfolio-analysis」切到「技术分析」tab：只剩 App.vue 全局页头（不再出现"技术分析"局部标题）
- 路由「/system/config」：AppCard 风格标题，样式与全局页头呼应（去重）

**回退**：每文件单 commit；删除即恢复

### 3.2 P0-B：Dashboard 信息密度扩充（影响 1 文件）

**改动**（`frontend/src/views/Dashboard.vue`）：
- 保持现有 GlobalIndicesStrip + PortfolioSummaryStrip 不动
- 新增 3 个区块（每个区块最小骨架 + 接入现有组件）：
  1. **自选股快表**（Top 5）—— 复用 `<WatchlistPanel>` 但加 `compact` prop 控制为 5 行；`compact` prop 在 `WatchlistPanel.vue` 加，内部用 `v-if="compact"` 跳过多余行
  2. **今日热点板块 Top 10** —— 复用 `<SectorHeatMap>` 但加 `compact` prop 改为单行 chip 列表
  3. **重要资讯 Top 3** —— **新建**小组件 `<NewsDigestList>` ~100 行（见下方权衡）。

  **为何新建而非复用**（回应 review 意见 #1 的三选一，选 (a)）：
  - `NewsView.vue` 的列表渲染与 tab/筛选/WS 状态强耦合，抽出子组件需重写 NewsView（影响面扩大到现有稳定页面，违背本轮「只增不改」原则）
  - 项目无 `stores/news.js`（数据仅存于 NewsView 局部 state），跨组件复用需新建 store——影响面同样扩大
  - **权衡结论**：接受 §4 例外「允许新建 1 个最小展示组件」，代价是 Dashboard 挂载期间新增 1 条 `/ws/news` WS 连接（`useNewsWS` 每次调用独立建连，已读源码确认）。已知轻微副作用：WS +1（后端 `/ws/news` 为广播型单连接开销可忽略）
  - **约束**：仅 Dashboard 引用；不触碰 NewsView；组件内部自带四态，不引用旧组件逻辑


**反假完成自检**：
- 真实调用：Dashboard 顶部 + 这 3 区块的 4 处 vue 引用
- 非兜底：复用现有数据源；不写 mock
- 内容非空：每区块 `loading` 态有骨架、`empty` 态有「暂无」+ CTA、`error` 态有重试
- 引用同步：旧 Dashboard 内容保留（只增不改）
- 交互四态：每个区块独立 loading/error/empty

**验证**：浏览器加载 Dashboard：
- 首屏：GlobalIndices → 摘要条 → 自选 → 板块 → 资讯
- 「数据为空」时（如未添加自选）：每个区块独立显示空态，不互相干扰

**回退**：删除新组件 + Dashboard.vue 新增模板即可

### 3.3 P1-C：移动端导航汉堡菜单

**改动**（`frontend/src/App.vue`）：
- `<768px` 时：`.nav-links { display: none }`（已有） + 显示汉堡按钮
- 关闭条件：
  - 点击任意链接后 `menuOpen=false`
  - 按 `Esc` 关闭
  - 点击 drawer 外部关闭（document click）
  - 路由切换自动关闭（watch route）
- 焦点管理：菜单打开时第一个 link focus；菜单关闭时焦点回汉堡按钮（按钮常驻 header 不随路由重挂载，路由切换后焦点回汉堡可达）

**a11y 清单**（回应 review 意见 #6）：
- 按钮属性：`aria-label="打开导航"`、`aria-expanded`、`aria-controls="nav-menu"`、`aria-haspopup="menu"`
- drawer 语义：**`<nav id="nav-menu" class="nav-drawer" role="menu" aria-label="移动端导航">`**（不用 `role="dialog"` + `aria-modal` —— 抽屉导航是 menu 模式，dialog 模式的焦点陷阱语义与之冲突）。**权衡说明**：WAI-ARIA 惯例上站点导航通常用 nav landmark 即可，此处用 `role="menu"` 是为获得 menuitem 的方向键导航语义，属少数派但合法选择；如 review 持保留意见可降级为 `<nav>` + 常规链接（功能等价，仅少方向键导航）
- 焦点陷阱：drawer 打开时监听 `onFocusin`，焦点离开 drawer 即拉回第一个 menuitem（比 `@keydown.tab.prevent` 可靠，兼容 Shift+Tab）
- body scroll lock：drawer 打开时 `document.body.style.overflow = 'hidden'`，关闭恢复
- drawer 动画 `@media (prefers-reduced-motion: reduce) { transition: none }`

**验证**（手动 + vitest）：
- 768px 时正常显示全部 nav-link
- ≤767px 显示汉堡；点击展开抽屉；点击链接跳转并关闭
- Tab 循环在 drawer 内（onFocusin 拉回）；Esc 关闭
- aria-expanded / aria-controls / aria-haspopup 正确
- vitest 断言 drawer 的 a11y 属性与 Esc 关闭逻辑

**回退**：删除 `.nav-burger` / `.nav-drawer` 块 + 移动端允许竖排 nav-links（**不退化到 `<details>`**——`<details>` 无焦点陷阱/Esc/键盘导航，属 a11y 退化，review 意见 #5）

### 3.4 P1-D：响应式断点收敛（无新代码，仅命名常量）

**改动**：
- `frontend/src/styles/theme.css:301-306` 已有 `--breakpoint-*` 变量但未在 `@media` 里用
- **本轮不重写**——仅文档化「下一轮起新增 `@media` 引用变量」（避免大批量改动引入回归）
- 在 `global.css` 顶部加一行注释指引：
  ```css
  /* 媒体查询断点规范：未来新增请用 var(--breakpoint-*) 而非硬编码 px
     当前硬编码点：480/600/639/640/768/1024 (本轮不统一) */
  ```

**验证**：grep `@media` 命中数不变（仅注释新增）

**回退**：删除该注释即可

### 3.5 P1-E：体验细节（无业务影响）

**搜索下拉键盘可达（ARIA Combobox 模式，回应 review 意见 #3/#7）**：
- 真实行号（已复核）：`PortfolioManager.vue:71-78` 是热门 ETF 按钮区，**搜索结果 `<li>` 是 `PortfolioManager.vue:64-78`**（搜索结果 `<li>` 渲染处，含 `.result-symbol` / `.result-name` / `.result-tag`）
- 完整 Combobox 模式：
  - 搜索输入框：`role="combobox"` + `aria-expanded`（下拉开/关） + `aria-controls="search-listbox"` + `aria-activedescendant`（指向当前高亮项）
  - 下拉容器：`role="listbox"` + `id="search-listbox"`
  - 下拉项 `<li>`：`role="option"` + `id="opt-{symbol}"` + `aria-selected="{i===searchIndex}"`
  - 键盘：`@keydown.down/up` 循环高亮、`@keydown.enter` 选中当前项、`@keydown.esc` 关闭下拉
  - 热门 ETF 区同理（键盘可达，`<button>` 天然可达无需改造）
- `.active` 与 `:hover` 背景相同（line 980）问题：给 `.active` 加 `outline: 1px solid var(--color-brand-300)` 使键盘高亮可见

**其他细节**：
- `PortfolioManager.vue` `.form-error` 包外层加 `aria-live="polite"`（review 意见 #8：`role="alert"` 在 v-if 切换时重复播报，`aria-live="polite"` 更合适）
- `ConfigView.vue` `.alert-success` 加 `role="status"`
- 不动颜色 / 文字 / 布局

**验证**：浏览器手动 Tab 键测试搜索下拉键盘可达；读屏测 `aria-live=polite` 朗读

**回退**：单文件改动，逐项 revert

## 4. 不做（明确写出避免后人误解）

- ❌ 不引入 icon 库（emoji 维持）
- ❌ 不重写 tabs（`PortfolioManager` 内 tabs 与 `AppTabs` 风格差异保留 — 下一轮评估 `AppTabs variant="soft"` 方案）
- ❌ 不动主题 token、不改色板
- ❌ 不拆 PortfolioManager（1201 行，下一轮评估拆分）
- ❌ 不重写 NewsView / 不新建 news store（例外见 §3.2：仅允许新建 `NewsDigestList` 1 个最小展示组件）

## 5. 验证 / 验收口径

### 5.1 开发期（每 P 完成后立刻跑）
- `cd frontend && npm test` —— 仅跑受影响的 vitest 文件（≤5 个用例即可，本轮不写新业务测）
- 单文件改动后 `npm run build` 必须绿（pre-commit 门禁）

### 5.2 验收期（全部 P 完成后跑一次）
- `cd frontend && npm test`（全量，方案 B 凭据：上一会话已写全量凭据，本轮跳过重复）
- `cd frontend && npm run build`
- 后端 `verify_e2e`（确认没动后端契约，但按惯例跑）
- 浏览器手动走查 5 个路由 + 移动端模拟（Chrome DevTools 切到 iPhone 12 Pro）

### 5.3 反假完成（硬门槛）
按 AGENTS.md「反假完成机制」逐项：
- 真实调用：Dashboard 新区块 4 个 template 引用、汉堡按钮 1 个 + drawer 1 个 = 6 个新 template 引用 ✅
- 非兜底：复用现有数据源，0 mock ✅
- 内容非空：每个新区块有 loading/empty/error 三态骨架 ✅
- 引用同步：旧 Dashboard 模板保留；旧 nav-links 768+ 行为不变 ✅
- 交互四态：Dashboard 3 区块 + 汉堡菜单 2 态 ✅

### 5.4 DoD
- 测试绿（vitest + build + verify_e2e）
- 浏览器手动走查通过
- 提交 commit message 英文（commit-msg 钩子已拦截）
- push 后 round54 完成

## 6. 探针命令（复现本会话证据）

```bash
# 1. 重复页头
rg -n "page-header" frontend/src --type vue

# 2. 路由 meta vs 内嵌 h1 文案差异
rg -n "<h1" frontend/src/components/portfolio/PortfolioManager.vue
rg -n "title.*组合分析" frontend/src/router/index.js

# 3. Dashboard 当前组件清单
rg -n "<template>|<script setup>" frontend/src/views/Dashboard.vue

# 4. 移动端导航断点
grep -n "max-width: 768" frontend/src/App.vue
grep -n "display: none" frontend/src/App.vue

# 5. 响应式断点散点
rg -n "@media \(max-width" frontend/src --type vue
```

## 7. 风险与回退

| 风险 | 概率 | 影响 | 回退 |
|---|---|---|---|
| 删除 page-header 影响某个 hidden 用例 | 低 | 局部 | 单文件 revert |
| WatchlistPanel/SectorHeatMap 加 `compact` prop 破坏现有用法 | 中 | 中 | 用 `v-bind` 默认 false 兼容；测试覆盖 |
| 汉堡菜单焦点管理出错 | 低 | a11y | 删除 `.nav-burger`/`.nav-drawer` 块 + 移动端竖排 nav-links（**不用 `<details>`**，a11y 退化） |
| Dashboard 扩充引入首屏渲染阻塞 | 中 | 性能 | 三区块用 `v-if="inited"` 懒加载 |

## 8. Out of scope

- 不动后端 API / 不写新单测业务用例（仅 vitest 烟雾验证）
- 不引入图标库（下一轮独立评估）
- 不拆 PortfolioManager / AnalysisView 单文件（下一轮评估）
- 不统一响应式断点（仅文档化指针）

## 9. 关联

- AGENTS.md「设计流程」「反假完成机制」节
- `docs/design-checklist.md` 8 项已逐条对照
- 上一会话的审阅回复为本方案的 input（11 条建议 → 本轮选 P0×3 + P1×2 = 5 条实施）