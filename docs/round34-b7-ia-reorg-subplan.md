# Round34-B7 全域 IA 重组子方案（方案 A 细化 · 评审稿）

> 状态：**待评审**——本文档为 round34 §10.2-B7 要求的子方案（页面职责矩阵 +
> 迁移清单 + 回归测试范围）。按 B7 前置条件，**评审通过前不实施**；
> 批准后单独开轮执行，不与其它批次混批。
>
> 上游依据：round34 文档 §9.18 方案 A（方向已定）、§10.2-B7 前置条件条款。
> 关联：round35 FE5（views/components 归位）随本批同步执行。

## 1. 现状盘点（2026-08-26 实测）

### 1.1 路由表（router/index.js，7 条）

| 路径 | 组件 | 所在目录 | 违例 |
|---|---|---|---|
| `/` | Dashboard | views/ ✓ | 内容越界（见 §2 矩阵）|
| `/portfolio-analysis` | PortfolioAnalysis | **components/** ✗ | 路由级组件不在 views/ |
| `/market-analysis` | MarketAnalysis | views/ ✓ | — |
| `/news` | NewsView | **components/** ✗ | 同上 |
| `/token-monitor` | TokenMonitor | **components/** ✗ | 同上 |
| `/source-monitor` | SourceMonitor | **components/** ✗ | 同上 |
| `/admin/config` | ConfigView | views/ ✓ | 路径分组与 IA 目标不符 |

### 1.2 目录现状

- `views/`（4）：ConfigView、Dashboard、DashboardAiTools、MarketAnalysis —— DashboardAiTools 是 AI 设计主入口但无独立路由（嵌在 Dashboard 内）；
- `components/` 根散落 **10 个文件**：其中 6 个是路由级/页面级组件（NewsView、PortfolioAnalysis、SourceMonitor、TokenMonitor、FactorModelView、AnalysisView），4 个真共享组件（GlobalIndicesStrip、PortfolioManager、TaskIndicator、TaskProgress）。

## 2. 页面职责矩阵（方案 A）

| 页面（目标） | 路由（目标） | 职责 | 迁入 | 迁出 |
|---|---|---|---|---|
| **市场概览** | `/`（Dashboard） | 指数条 + 自选摘要 + 板块热力 + AI 快捷卡 + 任务指示器 | ← AI 快捷卡精简版 | → 持仓卡片、盈亏明细表、分配饼图（全部移交组合页）|
| **组合分析** | `/portfolio-analysis` | 持仓 CRUD + 分配/盈亏/历史全权 | ← Dashboard 的持仓+盈亏区块 | — |
| **行情分析** | `/market-analysis` | 研判/板块/标的深读（不变） | — | — |
| **AI 设计** | `/ai`（新一级导航） | 设计向导 + 历史方案 + 策略检查（现 DashboardAiTools 全量） | views/DashboardAiTools 升级为路由页 | ← 从 Dashboard 抽离嵌入态 |
| **资讯** | `/news` | 不变 | components/NewsView → views/ | — |
| **系统·Token** | `/system/token` | 不变 | components/TokenMonitor → views/system/ | — |
| **系统·数据源** | `/system/sources` | 不变 | components/SourceMonitor → views/system/ | — |
| **系统·因子模型** | `/system/factors`（新挂路由） | FactorModelView 已是页面级却不可达（事实死功能风险） | components/FactorModelView → views/system/ | — |
| **系统·配置** | `/system/config` | 不变（路径从 /admin/config 平迁） | views/ConfigView → views/system/ | — |

导航分组（App.vue）：`市场概览 / 组合 / 行情 / AI 设计 / 资讯 / 系统▾(Token·数据源·因子·配置)`。

## 3. 迁移清单

### 3.1 文件移动（FE5 归位，git mv 保历史）

| 源 | 目标 | 说明 |
|---|---|---|
| components/NewsView.vue | views/NewsView.vue | 路由级归位 |
| components/PortfolioAnalysis.vue | views/PortfolioAnalysis.vue | 同上 |
| components/SourceMonitor.vue | views/system/SourceMonitor.vue | 系统分组 |
| components/TokenMonitor.vue | views/system/TokenMonitor.vue | 系统分组 |
| components/FactorModelView.vue | views/system/FactorModelView.vue | 新挂路由使其可达 |
| views/DashboardAiTools.vue | views/AiDesign.vue（改名） | 升一级导航；内部分区不变 |

### 3.2 留在 components/ 的共享组件（不动）

GlobalIndicesStrip、PortfolioManager、TaskIndicator、TaskProgress、ui/*、dashboard/*、design/*、market/*、analysis/*。

### 3.3 代码改动点

| # | 文件 | 改动 | 风险 |
|---|---|---|---|
| 1 | router/index.js | 路由表重写（§2 目标列）；旧路径 301 重定向（/token-monitor→/system/token 等 4 条）保书签 | 低 |
| 2 | App.vue 导航 | 分组菜单 + active 态判定改 name 匹配 | 低 |
| 3 | Dashboard.vue | 移除持仓/盈亏区块与相关 props 接线；保留指数条/自选摘要/AI 快捷卡 | 中（接线最多）|
| 4 | PortfolioAnalysis.vue | 吸收 Dashboard 迁出的持仓+盈亏区块（含 capital 输入联动） | 中 |
| 5 | AiDesign.vue | 嵌入态→路由态：去掉父容器假设，补 onMounted 首屏数据守卫 | 中 |
| 6 | 各页 router-link 引用 | grep `/portfolio-analysis\|/token-monitor\|/source-monitor\|/admin/config` 全量替换 | 低 |
| 7 | Playwright specs | 页面选择器/URL 常量更新（16 spec 扫一遍） | 低 |

**不做**：组件内部逻辑重构、store 变更、API 层变更——本批纯 IA 归位，行为零变化（黄金口径）。

## 4. 回归测试范围

| 层 | 范围 | 通过标准 |
|---|---|---|
| vitest | 受影响 spec 的 import 路径批量更新（NewsView/TokenMonitor/SourceMonitor/PortfolioAnalysis 相关 ~8 文件）+ 新增路由表快照测试（7+重定向条目断言） | 全绿 |
| npm run build | 构建门禁 | exit 0 |
| Playwright smoke | 7 页走查：每页 console 0 error + 核心元素存在断言（沿用既有 spec 改 URL） | 全绿 |
| 手工走查 | 导航分组渲染 / 旧路径重定向 / Dashboard 减负后首屏（perf 对照：期望 ≥round33 基线） | 截图留档 |
| verify_e2e | 后端零改动 → 仅回归确认不低于当轮基线 | 无新增 FAIL |

## 5. 工作量与顺序

- 文档评审（本步）→ 实施约 **1 天**：①移动+路由重写+重定向（0.5d）②Dashboard/组合页区块迁移接线（0.5d）③spec 更新+三件套验证（并入各步）。
- 实施窗口建议交易日盘中外（不依赖行情时段）；perf 对照需交易日盘中复测一轮。

## 6. 风险与开放问题

1. Dashboard 减负后信息密度下降是否可接受？（方案 A 已拍板方向，本批不改设计只挪位置）
2. `/admin/config` → `/system/config` 是否有外部书签依赖？重定向已兜底。
3. FactorModelView 挂路由属「顺路救活死功能」，若不想扩范围可退为仅归位不挂路由（评审拍板）。
