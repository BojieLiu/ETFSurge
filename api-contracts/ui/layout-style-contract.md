# UI/UX Layout & Style Contract — ETF Surge

> **契约驱动开发** | 所有页面布局、组件样式、交互模式必须遵守本契约 | Contract-Driven: All layouts, component styles, and interaction patterns MUST conform to this contract.

---

## 1. 概述 / Overview

| 属性 | 值 |
|------|-----|
| 版本 | 1.0.0 |
| 状态 | Draft |
| 适用范围 | 前端所有页面、组件、样式 |
| 设计系统 | 基于 `theme.css` CSS 变量体系 |
| 响应式策略 | Mobile-first，断点：`sm` 640px, `md` 768px, `lg` 1024px, `xl` 1280px, `2xl` 1536px |

---

## 2. 布局系统 / Layout System

### 2.1 容器宽度 / Container Widths

| Token | 值 | 用途 |
|-------|-----|------|
| `--container-max-xs` | 100% | 全宽移动端 |
| `--container-max-sm` | 640px | 小屏容器 |
| `--container-max-md` | 768px | 平板容器 |
| `--container-max-lg` | 1024px | 桌面标准容器 |
| `--container-max-xl` | 1280px | 宽屏容器 |
| `--container-max-2xl` | 1536px | 超宽容器 |
| `--container-max-full` | 100% | 全屏流体 |

```css
.container {
  width: 100%;
  max-width: var(--container-max-xl);
  margin: 0 auto;
  padding: 0 var(--space-padding-md);
}
.container--narrow { max-width: var(--container-max-lg); }
.container--wide { max-width: var(--container-max-2xl); }
.container--full { max-width: var(--container-max-full); padding: 0; }
```

### 2.2 页面结构 / Page Structure

```
┌─────────────────────────────────────────────────────────────┐
│ AppLayout (min-h-screen, flex-col)                          │
│  ├─ AppHeader (sticky, z-index: 300, h-16)                  │
│  │   ├─ Brand / Logo                                        │
│  │   ├─ NavLinks (desktop)                                  │
│  │   └─ UserActions / Status                                │
│  ├─ main (flex-1, flex-col)                                 │
│  │   ├─ PageHeader (optional, h-auto, py-6)                 │
│  │   │   ├─ Title (text-h2)                                 │
│  │   │   └─ Description (text-body-sm, text-secondary)      │
│  │   └─ PageContainer (flex-1, p-6)                         │
│  │       └─ <router-view>                                   │
│  └─ AppFooter (optional, py-4, border-t)                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 栅格系统 / Grid System

```css
/* 12 列弹性栅格 */
.grid {
  display: grid;
  gap: var(--space-gap-md);
}
.grid-cols-1 { grid-template-columns: repeat(1, 1fr); }
.grid-cols-2 { grid-template-columns: repeat(2, 1fr); }
.grid-cols-3 { grid-template-columns: repeat(3, 1fr); }
.grid-cols-4 { grid-template-columns: repeat(4, 1fr); }
.grid-cols-12 { grid-template-columns: repeat(12, 1fr); }

/* 响应式 */
@media (min-width: 640px) {
  .sm\:grid-cols-2 { grid-template-columns: repeat(2, 1fr); }
  .sm\:grid-cols-3 { grid-template-columns: repeat(3, 1fr); }
}
@media (min-width: 1024px) {
  .lg\:grid-cols-3 { grid-template-columns: repeat(3, 1fr); }
  .lg\:grid-cols-4 { grid-template-columns: repeat(4, 1fr); }
}
```

**断点映射**：
- `< 640px` (xs): 单列
- `640-1023px` (sm-md): 双列
- `≥ 1024px` (lg+): 3-4 列

### 2.4 页面区块间距 / Section Spacing

| Token | 值 | 用途 |
|-------|-----|------|
| `--space-section-xs` | 16px | 紧凑区块间距 |
| `--space-section-sm` | 24px | 标准区块间距 |
| `--space-section-md` | 32px | 舒适区块间距 |
| `--space-section-lg` | 48px | 大区块间距 |
| `--space-section-xl` | 64px | 页面级分割 |

---

## 3. 色彩应用规范 / Color Usage

### 3.1 语义色彩映射 / Semantic Color Mapping

| 语义 | Light Mode | Dark Mode | 用途 |
|------|------------|-----------|------|
| Primary Surface | `neutral-0` (#fff) | `neutral-900` (#0f172a) | 卡片、面板背景 |
| Secondary Surface | `neutral-50` | `neutral-800` | 次级区域、hover 态 |
| Tertiary Surface | `neutral-100` | `neutral-700` | 禁用、分隔区 |
| Border Light | `neutral-200` | `neutral-700` | 标准边框 |
| Border Medium | `neutral-300` | `neutral-600` | 强调边框、输入框聚焦 |
| Text Primary | `neutral-900` | `neutral-50` | 主文本 |
| Text Secondary | `neutral-600` | `neutral-400` | 次要文本、说明 |
| Text Muted | `neutral-400` | `neutral-500` | 占位符、禁用文本 |
| Brand Primary | `brand-600` (#2563eb) | `brand-400` (#60a5fa) | 主要按钮、链接、强调 |
| Success | `success-600` / `success-700` | `success-400` / `success-300` | 正向、盈利(红涨绿跌反向) |
| Danger | `danger-600` / `danger-700` | `danger-400` / `danger-300` | 错误、亏损、危险操作 |
| Warning | `warning-600` / `warning-700` | `warning-400` / `warning-300` | 警告、待处理 |

> ⚠️ **红涨绿跌约定**：国内行情习惯，涨/盈 = 红 (`--color-text-up` = `danger-700`)，跌/亏 = 绿 (`--color-text-down` = `success-700`)。**严禁**使用西方绿涨红跌配色。

### 3.2 数据可视化色板 / Data Viz Palette

```css
/* 分类色板 - 用于图表、饼图、标签 */
--chart-1: var(--color-brand-500);    /* #3b82f6 - 蓝 */
--chart-2: var(--color-success-500);  /* #22c55e - 绿 */
--chart-3: var(--color-warning-500);  /* #f59e0b - 橙 */
--chart-4: var(--color-danger-500);   /* #ef4444 - 红 */
--chart-5: #8b5cf6;                   /* 紫 */
--chart-6: #06b6d4;                   /* 青 */
--chart-7: #f97316;                   /* 橙红 */
--chart-8: #ec4899;                   /* 粉 */

/* 语义色板 - 用于信号、状态 */
--signal-buy: var(--color-success-600);
--signal-sell: var(--color-danger-600);
--signal-hold: var(--color-warning-600);
--signal-neutral: var(--color-neutral-500);
```

---

## 4. 字体系统应用 / Typography Application

### 4.1 标题层级 / Heading Hierarchy

| 元素 | Token | 字号 | 行高 | 字重 | 用途 |
|------|-------|------|------|------|------|
| Page Title | `--text-h1` | 30px | 1.1 | 700 | 页面主标题 (H1) |
| Section Title | `--text-h2` | 24px | 1.2 | 700 | 一级区块标题 (H2) |
| Card Title | `--text-h3` | 20px | 1.2 | 600 | 卡片标题 (H3) |
| Subsection | `--text-h4` | 17px | 1.5 | 600 | 小节标题 (H4) |

### 4.2 正文层级 / Body Hierarchy

| 元素 | Token | 字号 | 行高 | 字重 | 用途 |
|------|-------|------|------|------|------|
| Body Large | `--text-body-lg` | 17px | 1.6 | 400 | 重要正文、导读 |
| Body | `--text-body` | 15px | 1.5 | 400 | 标准正文 |
| Body Small | `--text-body-sm` | 13px | 1.5 | 400 | 辅助说明、表格单元格 |
| Caption | `--text-caption` | 11px | 1.4 | 500 | 标签、元数据、脚注 |
| Mono | `--text-mono` | 13px | 1.5 | 400 | 代码、数字、金额 |
| Mono Large | `--text-mono-lg` | 15px | 1.5 | 500 | 关键数值、价格 |

### 4.3 字体加载策略

```css
/* 在 global.css 中已配置 */
@font-face {
  font-family: 'Inter';
  font-display: swap;
  src: url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-display: swap;
  src: url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');
}
```

---

## 5. 组件设计规范 / Component Design Specs

### 5.1 卡片 / Card

```vue
<!-- 基础卡片 -->
<AppCard variant="default" padding="md" hoverable>
  <template #header>
    <AppCardTitle>标题</AppCardTitle>
    <AppCardDescription>副标题说明</AppCardDescription>
  </template>
  
  <template #content>
    卡片内容区域
  </template>
  
  <template #footer>
    <AppButton variant="ghost" size="sm">操作</AppButton>
  </template>
</AppCard>
```

| Variant | Background | Border | Shadow | 用途 |
|---------|------------|--------|--------|------|
| `default` | `surface-primary` | `border-light` | `shadow-sm` | 标准内容卡片 |
| `elevated` | `surface-primary` | none | `shadow-md` | 悬浮面板、弹层 |
| `outlined` | `surface-primary` | `border-medium` | none | 强调边界的卡片 |
| `filled` | `surface-secondary` | none | none | 背景区块、工具栏 |

**交互状态**：
- `hoverable` → hover 时 `shadow-md` + `translateY(-2px)`
- `clickable` → hover 时 `surface-hover` + cursor pointer

### 5.2 表格 / Table

```vue
<AppTable
  :columns="columns"
  :data="rows"
  :row-key="row => row.id"
  striped
  hoverable
  density="comfortable"
>
  <template #cell:pnl="{ row }">
    <span :class="row.pnl >= 0 ? 'text-up' : 'text-down'">
      {{ formatCurrency(row.pnl) }}
    </span>
  </template>
</AppTable>
```

| Density | Row Height | Cell Padding Y | 用途 |
|---------|------------|----------------|------|
| `compact` | 40px | 8px | 高密度数据、后台管理 |
| `comfortable` | 52px | 12px | **默认**，数据展示页 |
| `spacious` | 64px | 16px | 关键数据、仪表盘 |

**表头固定**：`position: sticky; top: 0; z-index: 10; background: var(--color-surface-primary);`

### 5.3 标签页 / Tabs

```vue
<AppTabs v-model="activeTab" variant="line" full-width>
  <AppTab value="overview" label="概览" />
  <AppTab value="analysis" label="分析" icon="📊" />
  <AppTab value="settings" label="设置" disabled />
</AppTabs>
```

| Variant | 样式 | 用途 |
|---------|------|------|
| `line` | 底部指示器线 | **默认**，页面级导航 |
| `enclosed` | 胶囊包裹 | 工具栏、筛选器 |
| `soft` | 背景填充 | 侧边栏、次级导航 |

**响应式**：`< 640px` 时自动变为可横向滚动的 `flex-nowrap overflow-x-auto`

### 5.4 徽标 / Badge

```vue
<AppBadge variant="success" dot>运行中</AppBadge>
<AppBadge variant="danger" count={5} max-count="99+" />
<AppBadge variant="outline" color="brand">Beta</AppBadge>
```

| Variant | 用途 |
|---------|------|
| `solid` | 状态指示（默认） |
| `outline` | 分类标签、版本标识 |
| `dot` | 状态指示灯（在线/离线） |
| `count` | 计数徽标（通知数） |

---

## 6. 交互与动效 / Interaction & Motion

### 6.1 过渡时长 / Transition Durations

| Token | 时长 | 用途 |
|-------|------|------|
| `--duration-instant` | 0ms | 无动画切换 |
| `--duration-fast` | 100ms | hover、focus、按钮点击 |
| `--duration-normal` | 200ms | **默认**，展开/折叠、模态框 |
| `--duration-slow` | 300ms | 页面转场、抽屉滑入 |
| `--duration-slower` | 500ms | 复杂编排动画 |

### 6.2 缓动函数 / Easing

| Token | 曲线 | 用途 |
|-------|------|------|
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | **默认**，进入动画 |
| `--ease-in-out` | `cubic-bezier(0.4, 0, 0.2, 1)` | 进出同步 |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | 弹性反馈（按钮、Toast） |

### 6.3 关键交互模式 / Key Interaction Patterns

| 交互 | 规范 |
|------|------|
| 按钮点击 | `scale(0.98)` 100ms + `--ease-spring` |
| 卡片悬浮 | `translateY(-2px)` + `shadow-md` 200ms |
| 输入框聚焦 | `border-color: brand-500` + `shadow-focus` 100ms |
| 表格行悬浮 | `background: surface-hover` 100ms |
| 页面转场 | `opacity` + `translateY(8px)` 200ms `--ease-out` |
| Toast 进场 | `slide-in-right` + `fade-in` 200ms `--ease-spring` |
| Toast 退场 | `slide-out-right` + `fade-out` 150ms `--ease-in` |

---

## 7. 响应式行为 / Responsive Behavior

### 7.1 断点策略 / Breakpoint Strategy

```css
/* Mobile First - 基础样式针对 < 640px */
/* sm: 640px+ */
/* md: 768px+ */
/* lg: 1024px+ (桌面主力) */
/* xl: 1280px+ */
/* 2xl: 1536px+ */
```

### 7.2 组件响应式规则 / Component Responsive Rules

| 组件 | < 640px | 640-1023px | ≥ 1024px |
|------|---------|------------|----------|
| `AppHeader` | 汉堡菜单 + 抽屉导航 | 完整导航栏 | 完整导航栏 |
| `PageContainer` | `padding: 16px` | `padding: 24px` | `padding: 32px` |
| `AppCard` | `padding: 16px` | `padding: 20px` | `padding: 24px` |
| `AppTable` | 卡片式列表（堆叠） | 表格（横向滚动） | 完整表格 |
| `AppTabs` | 横向滚动 | 完整显示 | 完整显示 |
| `Grid` | 1 列 | 2 列 | 3-4 列 |
| `Modal` | 全屏抽屉 | 居中弹窗 (max-w-lg) | 居中弹窗 (max-w-2xl) |

---

## 8. 无障碍 / Accessibility (WCAG 2.1 AA)

### 8.1 颜色对比度 / Color Contrast

| 文本类型 | 最小对比度 | 当前实现 |
|----------|------------|----------|
| 正文 (≥14px) | 4.5:1 | ✅ `neutral-900` on `neutral-0` = 16.3:1 |
| 大文本 (≥18px 或 ≥14px bold) | 3:1 | ✅ |
| UI 组件边框/图标 | 3:1 | ✅ `neutral-300` on `neutral-0` = 3.9:1 |

### 8.2 焦点管理 / Focus Management

```css
/* 全局焦点可见样式 */
:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
  border-radius: var(--radius-sm);
}

/* 错误状态焦点 */
:focus-visible[data-error] {
  box-shadow: var(--shadow-focus-error);
}
```

### 8.3 ARIA 模式 / ARIA Patterns

| 组件 | 必需 ARIA 属性 |
|------|----------------|
| `AppButton` | `aria-disabled`, `aria-busy` (loading) |
| `AppInput` | `aria-invalid`, `aria-describedby` (error/help) |
| `AppSelect` | `aria-invalid`, `aria-describedby` |
| `AppTabs` | `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls` |
| `AppModal` | `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby` |
| `AppTooltip` | `role="tooltip"`, `aria-describedby` |
| `AppTable` | `role="table"`, `role="row"`, `role="cell"`, `aria-sort` |

### 8.4 键盘导航 / Keyboard Navigation

| 组件 | 支持的键位 |
|------|------------|
| `AppTabs` | `←` `→` 切换，`Home` `End` 首尾，`Enter` `Space` 激活 |
| `AppModal` | `Esc` 关闭，`Tab` 循环焦点陷阱 |
| `AppTable` | `↑` `↓` 行导航，`Enter` 选中/展开 |
| `AppSelect` | `↑` `↓` 选择，`Enter` 确认，`Esc` 关闭 |

---

## 9. 密度与数据展示 / Density & Data Display

### 9.1 数字格式化 / Number Formatting

```javascript
// 金额：千分位，2 位小数，红涨绿跌
formatCurrency(12345.67) // "+¥12,345.67" (text-up)
formatCurrency(-1234.5)  // "-¥1,234.50" (text-down)

// 百分比：1 位小数，带符号
formatPercent(0.1234)   // "+12.3%" (text-up)
formatPercent(-0.056)   // "-5.6%" (text-down)

// 价格：根据价格区间自适应小数位
formatPrice(3200.5)    // "3,200.50"
formatPrice(0.0034)    // "0.0034"

// 大数字：中文万/亿单位
formatCompact(1500000) // "150.00 万"
formatCompact(250000000) // "2.50 亿"
```

### 9.2 表格数据密度 / Table Density

```css
/* 紧凑模式 - 高频交易、监控面板 */
.table--compact { --table-row-height: 40px; --table-cell-padding-y: 8px; }

/* 舒适模式 - 默认，仪表盘、报表 */
.table--comfortable { --table-row-height: 52px; --table-cell-padding-y: 12px; }

/* 宽松模式 - 关键决策、演示 */
.table--spacious { --table-row-height: 64px; --table-cell-padding-y: 16px; }
```

---

## 10. 契约验证清单 / Verification Checklist

### 10.1 样式契约验证 / Style Contract Verification

- [ ] 所有页面使用 `AppLayout` + `PageContainer` 结构
- [ ] 所有容器使用 `.container` / `.container--narrow` / `.container--wide`
- [ ] 所有间距使用 `var(--space-*)` Token，**禁止**硬编码 px/rem
- [ ] 所有颜色使用语义 Token，**禁止**直接使用十六进制/rgb
- [ ] 所有字体大小使用 `--text-*` 组合 Token
- [ ] 所有圆角使用 `--radius-*` Token
- [ ] 所有阴影使用 `--shadow-*` Token
- [ ] 所有过渡使用 `--transition-*` Token
- [ ] 所有 z-index 使用 `--z-index-*` Token

### 10.2 组件契约验证 / Component Contract Verification

- [ ] `AppButton`：variant/size/loading/disabled 完整实现
- [ ] `AppInput`：label/error/help/clearable/prefix/suffix 完整
- [ ] `AppSelect`：placeholder/multiple/searchable/loading 完整
- [ ] `AppCard`：header/content/footer slot，variant/hoverable/clickable 完整
- [ ] `AppTable`：columns/data/slot/row-key/striped/hoverable/density 完整
- [ ] `AppTabs`：v-model/variant/full-width/lazy 完整
- [ ] `AppBadge`：variant/count/dot/color 完整
- [ ] `AppModal`：v-model/title/size/close-on-overlay/close-on-escape 完整
- [ ] `AppToast`：type/title/message/duration/action/position 完整
- [ ] `AppTooltip`：content/trigger/delay/offset 完整
- [ ] `AppAvatar`：src/alt/size/shape/status 完整
- [ ] `AppSpinner`：size/label 完整
- [ ] `AppSkeleton`：type/rows/animation 完整

### 10.3 交互契约验证 / Interaction Contract Verification

- [ ] 所有按钮有 `:focus-visible` 样式
- [ ] 所有输入框有错误状态样式 + `aria-invalid`
- [ ] 所有模态框有焦点陷阱 + `Esc` 关闭
- [ ] 所有 Toast 有 `role="alert"` + 适当 `aria-live`
- [ ] 所有表格可键盘导航
- [ ] 所有标签页可键盘操作
- [ ] 页面转场有动画且尊重 `prefers-reduced-motion`
- [ ] 加载骨架屏与实际内容布局一致（CLS < 0.1）

### 10.4 响应式契约验证 / Responsive Contract Verification

- [ ] `< 640px`：单列布局，汉堡菜单，卡片式表格
- [ ] `640-1023px`：双列网格，完整导航，表格横向滚动
- [ ] `≥ 1024px`：3-4 列网格，完整表格，侧边栏常驻
- [ ] 容器最大宽度在 `xl` (1280px) 处锁定
- [ ] 触摸目标最小 44×44px (移动端)

---

## 11. 实施路线图 / Implementation Roadmap

| 阶段 | 任务 | 产出物 | 验收标准 |
|------|------|--------|----------|
| 1 | 扩展 `theme.css` 设计令牌 | 完整 Token 体系 | 所有 Token 在 `:root` 定义，Dark mode 覆盖完整 |
| 1 | 创建基础布局组件 | `AppLayout`, `PageContainer`, `PageHeader`, `Section` | 所有页面路由套用统一布局 |
| 2 | 实现 UI 组件库 (14 个) | `components/ui/` 全套 | 单测 100% 覆盖，Storybook 文档化 |
| 3 | 重构 Dashboard 页 | `Dashboard.vue` + 子组件 | 视觉一致，响应式通过，verify_e2e 通过 |
| 3 | 重构 MarketAnalysis 页 | `MarketAnalysis.vue` + market/* | 同上 |
| 3 | 重构 PortfolioAnalysis 页 | `PortfolioAnalysis.vue` + 子组件 | 同上 |
| 3 | 重构 NewsView 页 | `NewsView.vue` | 同上 |
| 3 | 重构 DashboardAiTools 页 | `DashboardAiTools.vue` + design/* | 同上 |
| 4 | 深色模式完善 | CSS 变量切换 + 持久化 | 手动/系统跟随双模式，无闪烁 |
| 4 | 无障碍审计修复 | axe-core 自测 + 人工复核 | WCAG 2.1 AA 全通过 |
| 5 | E2E 契约验证 | `verify_e2e.py` + `npm test` | 全绿 ✅ |

---

## 12. 附录：现有代码映射 / Existing Code Mapping

| 现有文件 | 目标契约组件 | 迁移策略 |
|----------|--------------|----------|
| `AppButton.vue` | `AppButton` | 重构：补全 variant/size/loading/无障碍 |
| `AppInput.vue` | `AppInput` | 重构：补全 prefix/suffix/clearable/字符计数 |
| `AppSelect.vue` | `AppSelect` | 重构：补全 multiple/searchable/无障碍 |
| `Skeleton.vue` | `AppSkeleton` | 重命名 + 扩展 type/animation |
| `theme.css` | 设计令牌源 | 扩展：容器、栅格、密度、图表色板 |
| `global.css` | 基础样式 | 保留 + 补充焦点可见、选择、滚动条 |
| `Dashboard.vue` | 页面模板 | 重构：使用 `AppLayout` + 新组件 |
| `MarketAnalysis.vue` | 页面模板 | 重构：统一 Tab、Card、Table 样式 |
| `PortfolioAnalysis.vue` | 页面模板 | 重构：合并 AnalysisView，统一布局 |
| `NewsView.vue` | 页面模板 | 重构：统一 Toolbar、List、Badge 样式 |
| `DashboardAiTools.vue` | 页面模板 | 重构：Wizard/Loading/Result 统一卡片风格 |

---

**文档状态**：🟡 Draft — 待评审确认后进入实施阶段