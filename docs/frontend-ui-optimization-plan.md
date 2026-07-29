# Frontend UI Optimization Plan (v2)

> 核心目标：页面美观、协调、专业性强。
> 实施策略：分阶段渐进，每步可独立验证，最终达到完整设计系统覆盖。
> 版本：**v2 — 2026-07-27 代码审计后重写**。原方案 v1 写于 Phase 2.2 前，基于旧代码状态。
> 本次 v2 基于 8 个路由页面的实际代码审计，重写实施路径。
> **2026-07-29 跟进审计**：验证了 Step 3 (TokenMonitor→AppTabs) 已实施，但 TokenMonitor.vue 中仍有旧 `tab-group`/`tab-btn` CSS（387-406 行），属死代码不影响功能。Step 6(chartColors.js)、7(Skeleton 统一)、8(响应式断点统一) 仍未实施。

---

## 1. 当前代码审计结果

### 设计系统基础设施（已就绪）

| 基础设施 | 状态 |
|---------|:----:|
| `theme.css` 设计令牌（品牌色/语义色/中性色/图表色、排版、间距、圆角、阴影、动效） | ✅ 已定义 |
| CSS 变量后向兼容别名（`--color-primary` 等 5 个） | ✅ `theme.css:121-124` |
| 13 个 UI 组件（AppButton/Card/Input/Tabs/Table/Modal/Toast/Badge/Avatar/Select/Pagination/Tooltip/Skeleton） | ✅ 已实现 |
| 布局组件（AppLayout/PageContainer/PageHeader） | ✅ 已实现 |
| SVG 图标组件（SvgIcon.vue） | ✅ 已存在 |

### 页面现状（8 个路由）

| 路由 | 组件 | Tab 使用情况 | Card 使用情况 |
|------|------|:------------:|:-------------:|
| `/` Dashboard | views/Dashboard.vue | **AppTabs** ✅ | AppCard 部分使用（PieChart/BarChart）；SummaryCards/CapitalInputBar 手工 card |
| `/portfolio-analysis` | components/PortfolioAnalysis.vue | **AppTabs** ✅ | 各子组件自行管理 |
| `/market-analysis` | views/MarketAnalysis.vue | **手工 market-tabs** ❌ | `section-card` wrapper + 手工 `card` 类名 |
| `/news` | components/NewsView.vue | 无 tabs | 手工 `card` + `card-header` + `card-title` |
| `/token-monitor` | components/TokenMonitor.vue | **手工 tab-btn** ❌ + 手工 `card` | 手工 `card` + `card-header` + `card-title` |
| `/source-monitor` | components/SourceMonitor.vue | 无 tabs | 手工 `stat-card` ❌ |
| `/factor-ic` | components/FactorICView.vue | 无 tabs | 手工 `stat-card` ❌ |
| `/admin/config` | views/ConfigView.vue | 无 tabs | 手工 `config-card` ❌ |

### v1 方案中已自然解决的问题

| v1 问题 | v1 描述 | 实际状态 |
|---------|--------|:--------:|
| `--color-primary` 等 4 变量未定义 | 25+ 处引用渲染为 undefined | ✅ `theme.css:121-124` 已追加别名（可能是向后兼容补丁） |
| section-card 嵌套双层边框 | 6 个市场组件嵌套 `section-card > card` | ✅ `.section-card` 仅定义 `margin-bottom`，无边框/阴影，双层边框不存在 |
| Dashboard Tab 为自绘 | Tab 五套独立 | ✅ `Dashboard.vue:20` 已使用 **AppTabs** |
| PortfolioAnalysis Tab 为自绘 | 同上 | ✅ `PortfolioAnalysis.vue:16` 已使用 **AppTabs** |
| plugins/echarts.js 残留 | 文件未删除 | ✅ `src/plugins/` 已为空目录 |
| task.js localStorage 高频写 | 性能问题 | ✅ task store 已改为 API 驱动 |

### 仍存在的真实问题

| # | 问题 | 所在页面 | 严重度 |
|---|------|---------|:------:|
| 1 | **MarketAnalysis 使用手工市场切换 tabs**（`market-tabs` class），未用 `AppTabs` | market-analysis | 🟡 中 |
| 2 | **TokenMonitor 使用手工粒度切换 tabs**（`tab-group` / `tab-btn` class），未用 `AppTabs` | token-monitor | 🟡 中 |
| 3 | **NewsView 手工 card 类名**（`card` + `card-header` + `card-title`），未用 `AppCard` | news | 🟢 低 |
| 4 | **TokenMonitor 手工 card 类名**，未用 `AppCard` | token-monitor | 🟢 低 |
| 5 | **Emoji 图标散落多处**（基于 v1 统计约 40+ 处），各平台渲染不一致，而 `SvgIcon.vue` + `icons.js`（20 个 SVG 图标）已存在但未充分使用 | 全部 | 🟡 中 |
| 6 | **图表颜色硬编码**（8 处 hex 值），与 theme.css `--chart-1` ~ `--chart-8` 不互通 | Dashboard 子组件 | 🟢 低 |
| 7 | **加载状态不统一**：Skeleton / spinner / loading text 混用 | 全部 | 🟢 低 |
| 8 | **响应式断点碎片化**：部分使用 480px，全局使用 640/768/1024 | 部分页面 | 🟢 低 |
| 9 | **部分页面的 card hover 效果不一致**（SummaryCards 有 translateY，其他无） | 全部 | 🟢 低 |

---

## 2. 优化方案（分阶段）

### Phase 1 — 低风险模式统一（✅ 已完成）

| Step | 内容 | 状态 | 说明 |
|------|------|:----:|------|
| Step 1 | theme.css 变量补齐 | ✅ 已完成 | `theme.css:121-124` 已追加 `--color-primary` 等 5 个别名 |
| Step 2 | section-card 嵌套消除 | ✅ 已自然解决 | `.section-card` 已无边框/阴影，嵌套视觉噪音不存在 |

### Phase 2 — 核心组件统一替换（1 步已完成）

| Step | 内容 | 风险 | 状态 |
|------|------|:----:|:----:|
| **Step 3** | TokenMonitor 粒度选择器 → AppTabs | 🟢 低 | ✅ **已完成**（Phase 10.3） |
| **Step 4** | MarketAnalysis 市场切换 → AppTabs | ⛔ **不适用** | MarketAnalysis 的「市场选择」是 filter/selector（所有区块同时响应），非内容切换 tab。AppTabs 是为「只显示一个 tab 内容」设计的，不适合此场景。**不做迁移。** |
| **Step 5** | NewsView 手工 card → AppCard | 🟡 中 | ⛔ **建议推迟**。NewsView 的手工 `card` 结构与列表渲染紧密耦合（`section.card.news-card > ul.news-list > li`），替换为 AppCard 需重构 HTML 结构，且现有 12 条单测需全部通过。收益有限（视觉差异小）。**待 UI 重新设计时再做。** |

**验证方式**：
- Step 3: TokenMonitor 粒度切换功能正常
- npm test 全绿
- E2E smoke test 通过

### Phase 3 — 跨页面统一（3 步，中度风险）

> **2026-07-29 状态**：Steps 6-8 均**未实施**。建议在下次 UI 优化 sprint 中优先处理。

| Step | 内容 | 风险 | 预估工时 | 当前状态 |
|------|------|:----:|:--------:|:--------:|
| **Step 6** | **图表颜色抽象**：创建 `src/utils/chartColors.js`，替换 Dashboard/TokenMonitor/NewsView 中的硬编码色值 | 🟡 中 | 1h | ❌ 未实施 — `chartColors.js` 不存在 |
| **Step 7** | **统一加载状态**：各页面使用 Skeleton 组件替代零散 spinner 和 loading text | 🟢 低 | 1h | ❌ 未实施 |
| **Step 8** | **统一响应式断点**：全局使用 640/768/1024 三级断点，替换 480px | 🟢 低 | 1h | ❌ 未实施 |

**验证方式**：截图对比 + 移动端走查

### Phase 4 — 可选优化（需评估）

> 以下条目收益不明确或成本较高，**建议先评估再决定是否进入实施**。

| Step | 内容 | 收益评估 |
|------|------|:--------:|
| **Step 9** | Emoji 替换为 SvgIcon（利用已存在的 `SvgIcon.vue` 组件） | ⚠️ 收益中等，工作量 40+ 处替换 |
| **Step 10** | 统一 card hover 效果（translateY + shadow） | 🟢 低工作量，纯 CSS |
| **Step 11** | AppCard 替换 TokenMonitor/SourceMonitor/FactorIC 手工 card | 🟢 低工作量、低风险 |

---

## 3. 验证方法

```
Phase 2 验证：
├─ Step 3: TokenMonitor 粒度切换功能正常
├─ Step 4: MarketAnalysis 市场 Tab 切换 + 快速栏功能正常
├─ Step 5: NewsView 渲染/筛选/WS 推送正常
├─ npm test 全绿（含 ChartComponents.spec.js）
└─ npm run build 无编译错误

Phase 3 验证：
├─ Step 6: 图表颜色保持视觉一致，无颜色异常
├─ Step 7: Skeleton 替换后 loading 态视觉正确
├─ Step 8: 640/768/1024 断点下布局正确
└─ 全页面截图对比

Phase 4 验证：
├─ emoji 替换后页面专业感提升
├─ hover 效果统一
└─ card 结构统一
```
