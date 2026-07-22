# Frontend UI Optimization Plan

> 核心目标：页面美观、协调、专业性强。
> 实施策略：分阶段渐进，每步可独立验证，最终达到完整设计系统覆盖。

---

## 1. 现状摘要

### 设计令牌（已就绪）
`theme.css` 定义了完善的设计系统：色彩（品牌色/语义色/中性色/图表色）、排版（字号/字重/行高/组合令牌）、间距（4px 基准）、圆角、阴影（6级）、动效（时长/缓动）、z-index 层级。

### 基础组件库（已就绪）
13 个 UI 组件：`AppButton`, `AppCard`, `AppInput`, `AppTabs`, `AppTable`, `AppModal`, `AppToast`, `AppBadge`, `AppAvatar`, `AppSelect`, `AppPagination`, `AppTooltip`, `Skeleton`。

### 布局组件（已就绪）
`AppLayout` 提供 header + sidebar + main 三区域骨架，含 sticky header、响应式 sidebar、页面标题插槽。
另有 `PageContainer`、`PageHeader` 等辅助布局组件。

### 页面现状（5 个路由）

| 路由 | 构成 | 当前质量 |
|------|------|---------|
| `/` Dashboard | GlobalIndicesStrip + CapitalInputBar + SummaryCards + AllocationPieChart/Table ×2 + PnLDetailTable + PnLBarChart | 功能完整，7 个区块的卡片/标题/间距各自为政 |
| `/portfolio-analysis` | AI 工具 / 持仓管理 / 技术分析 三 tab | 三套子页样式分离，Tab 为自绘 |
| `/market-analysis` | 6 个区块（MarketReport / WatchlistPanel / AiAdvisor / SectorAnalysis / SymbolAnalysis / IndexAnalysis） | 全部使用 `section-card` 包裹，内层再套 `card`，双层边框视觉噪音 |
| `/news` | 资讯流 + AI 影响分析面板 | 独立样式，整体尚可 |
| `/token-monitor` | 统计卡 + 趋势图 + 功能调用表 + 失败记录表 | 统计卡可用，表格分 CSS-grid 和 data-table 两套 |

---

## 2. 需要解决的问题

### 🔴 高优先级

| # | 问题 | 状态 | 影响 |
|---|------|------|------|
| 1 | `--color-primary` / `--color-border` / `--color-text-muted` / `--color-primary-dark` **被引用但未在 theme.css 中定义** | 25+ 处引用，渲染为 undefined | 颜色偏离预期，多个组件显示异常 |
| 2 | **卡片视觉碎片化**：3 种模式混乱并存 | | |
| | a) `AppCard` 组件（有，但未充分利用） | 仅少数场景使用 | |
| | b) 手工 `card` + `card-header` + `card-title` 类名 | Dashboard 全部子组件 | |
| | c) `section-card` + `section-header` + `section-title` | 6 个市场组件 | 嵌套双层卡片边框 |
| 3 | **Tab 控件五套独立实现**，均未使用 `AppTabs` | Dashboard / PortfolioAnalysis / MarketAnalysis / TokenMonitor / DesignResult | 样式不统一，间距/下划线/高亮各有差异 |

### 🟡 中优先级

| # | 问题 | 影响 |
|---|------|------|
| 4 | Emoji 图标散落 40+ 处，各平台渲染不一致，缺乏专业感 | 全局美观度 |
| 5 | 排版复合令牌（`--text-h1` ~ `--text-h4`, `--text-body` 等）未被充分利用，15-20 处仍在手写 `font-size + font-weight` | 代码冗余，不一致 |
| 6 | 图表颜色在多个组件中硬编码，与 theme.css 的 `--chart-1` ~ `--chart-8` 不互通 | 改色板需改多处 |
| 7 | 加载状态不统一：Skeleton vs spinner 混用 | 体验碎片化 |
| 8 | 响应式断点不连贯：Dashboard 在窄屏下不切换单列，Market tabs 移动端溢出 | 移动端体验 |

### 🟢 低优先级

| # | 问题 | 影响 |
|---|------|------|
| 9 | WatchlistPanel 手工实现 Modal，未使用 `AppModal` | 代码复用不足 |
| 10 | 部分页面 section header 与 AppLayout 的 page-header 功能重叠 | 冗余结构 |
| 11 | 各页面 hover 效果不一致：SummaryCards 有 translateY + shadow，其他卡片没有 | 交互不统一 |

---

## 3. 完整优化方案（最终目标）

### 3.1 变量补齐 — 一步到位

**改动**：`theme.css` 追加向后兼容别名变量。

```css
/* === 向后兼容别名 === */
--color-primary: var(--color-brand-600);
--color-primary-dark: var(--color-brand-700);
--color-primary-light: var(--color-brand-400);
--color-border: var(--color-border-light);
--color-text-muted: var(--color-text-tertiary);
```

**为什么这样解决**：不改任何组件代码，25+ 处引用立即正确。现有代码的自由变量引用全部被兜底。

### 3.2 卡片模式统一

**最终目标**：所有卡片区块使用 `<AppCard>` 组件。

- `AppCard` 预制了 `header` / `content` / `footer` 三区域结构
- 支持 4 种 variant（default / elevated / outlined / filled）
- 内置 hover / click / disabled 状态

**实施路径**：从 Dashboard 开始逐个组件迁移，每个完成后视觉验证。

### 3.3 Tab 控件统一

**最终目标**：所有页面使用 `<AppTabs>` 组件。

- `AppTabs` 支持 line / enclosed / soft 三种 variant
- 支持图标、badge、懒加载、键盘导航、滚动
- 有动画指示器

**实施路径**：从简单页面（Dashboard → TokenMonitor）到复杂页面（PortfolioAnalysis → MarketAnalysis）。

### 3.4 SVG 图标系统引入

**最终目标**：所有 emoji 图标替换为 SVG 图标。

- 推荐 [Lucide](https://lucide.dev)（轻量、树摇支持、Vue 官方组件库风格）
- 或使用 SVG sprite，保持与品牌色一致的颜色控制
- 每个图标可设置 `currentColor`，自动跟随文本色

### 3.5 排版令牌迁移

**最终目标**：不再手写 `font-size + font-weight`，全部使用组合令牌。

```css
/* ❌ 当前 */
font-size: var(--font-size-xl);
font-weight: var(--font-weight-semibold);

/* ✅ 目标 */
font: var(--text-h3);
```

### 3.6 图表颜色抽象

**最终目标**：所有 ECharts 颜色引用统一来源。

新建 `frontend/src/utils/chartColors.js`：

```js
export const chartColors = [
  '#3b82f6', '#22c55e', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#f97316', '#ec4899'
]
```

各组件 import 使用，未来换色板只改一处。

### 3.7 其余统一

- 加载状态全部使用 `Skeleton` 组件
- Modal 全部使用 `AppModal`
- 统一响应式断点策略：目前 global.css 使用 640px / 768px / 1024px，但部分组件（SummaryCards、CapitalInputBar）使用 480px。应在全系统内统一使用 640 / 768 / 1024 三级断点
- 统一卡片 hover 效果（`translateY(-2px) + shadow-md`）

---

## 4. 分阶段实施路线图

```
Phase 1 — 基础修复（安全，零破坏）
├── Step 1: theme.css 变量补齐 ── 5 行 CSS
├── Step 2: section-card 嵌套消除 ── 3 行 CSS（不改 HTML）
└── 验证：
    ├─ 浏览器打开所有 5 个路由，检查原先灰色文字/边框是否恢复品牌色
    ├─ Console 无 "Undefined CSS variable" 类警告
    ├─ MarketAnalysis 页面各区块不再显示双层卡片边框
    └─ npm test 全绿

Phase 2 — 核心组件统一
├── Step 3: Dashboard 手工 card → AppCard（7 个区块：CapitalInputBar、SummaryCards、AllocationPieChart×2、AllocationTable×2、PnLDetailTable、PnLBarChart）
├── Step 4: Dashboard 手工 tab → AppTabs
├── Step 5: PortfolioAnalysis 手工 tab → AppTabs
├── Step 6: TokenMonitor 手工 tab → AppTabs
├── Step 7: MarketAnalysis 手工 tab → AppTabs
└── Step 8: DesignResult 手工 tab → AppTabs
    每步独立验证：
    ├─ npm test 全绿
    ├─ 该页面 Tab 点击切换内容正确
    ├─ 该页面 Card 区块 padding / 边框 / 标题层级与 AppCard 默认样式一致
    └─ 浏览器 Console 无 Vue 警告或未定义 CSS 变量警告

Phase 3 — 视觉深化
├── Step 9: 引入 SVG 图标系统，替换 emoji
├── Step 10: 排版令牌迁移（可批量或渐进）
├── Step 11: Chart 颜色抽象
├── Step 12: 统一加载状态（Skeleton）
├── Step 13: WatchlistPanel Modal → AppModal
└── 验证：全页面截图对比

Phase 4 — 精细化打磨
├── Step 14: 响应式补齐（全局统一 640/768/1024 断点，替换零散的 480px 断点）
├── Step 15: 统一 hover/transition 效果
├── Step 16: 统一空状态样式
└── 验证：移动端/桌面端全流程走查
```

每 Phase 完成后可单独合并/发布。
