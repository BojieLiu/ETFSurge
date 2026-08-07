# 前端界面「字级放大 + 内容铺满 + 视觉协调」优化方案（评审稿，未实施）

> 目标：解决「字体偏小」「内容未铺满」「视觉不够协调」三类观感问题。
> **本稿只出方案，不实施**。已确认决策：**中等字号档位（base 15→16px）**、
> **写死字号组件统一改为 var()**、**本轮只出方案不动代码**。
>
> 依据：`frontend/src/styles/theme.css` + `global.css` + explore 子代理审计
> （写死字号组件清单 / 收窄容器清单）已核实，见下文附 A。

---

## 0. 三个根因（为什么现在"小、挤、不满"）

| 症状 | 根因 |
|------|------|
| **字体偏小** | 主题基准 `--font-size-base:0.9375rem=15px`、`sm=13px`、`xs=11px` 保守；且**十几处组件把字号写死成 px/rem**（不用 var），部分比主题还小 |
| **内容没铺满** | 4 个 view 用独立 `max-width`（960~1200px）而非全局 `.container`(1400px)；全局容器 1400px 在宽屏下仍有边距 |
| **不协调** | 变量组件会随主题缩放、写死组件不缩放 → 放大后字号**不一致**；卡片内边距手写各处不一 |

---

## 二、变更总表（按文件）

### 2.1 主题令牌核心变更 `theme.css`（基准放大）

| 令牌 | 现值 | 目标值 | 说明 |
|------|------|--------|------|
| `--font-size-xs` | `0.6875rem`(11px) | `0.75rem`(12px) | 最小标注字 +1px |
| `--font-size-sm` | `0.8125rem`(13px) | `0.875rem`(14px) | 次要正文/按钮/输入 |
| `--font-size-base` | `0.9375rem`(15px) | `1rem`(16px) | **核心**：正文基准 16px |
| `--font-size-lg` | `1.0625rem`(17px) | `1.125rem`(18px) | 标题/大正文 |
| `--font-size-xl` | `1.25rem`(20px) | `1.375rem`(22px) | h3 |
| `--font-size-2xl` | `1.5rem`(24px) | `1.625rem`(26px) | h2 |
| `--font-size-3xl` | `1.875rem`(30px) | `2rem`(32px) | h1 |

> `--font-size-4xl/5xl`（36/48px）暂不动（仅 display 大标题，非主体）。
> 组合令牌 `--text-*`、`--btn-font-size-*` 引用上述变量，**自动跟随**，无需改。
> `root font-size` 保持浏览器默认 16px（无需额外设），rem 即 %16。

**间距/密度微调（呼吸感，同一文件）：**
| `--space-4/5/6` | 16/20/24px | **不变** |
| `--card-padding` | `--space-5`(20px) | 保持 |
| 新增 `root {}` | — | `letter-spacing: 0.01em` 常态（Increase 可读性），标题 `-0.02em` 已有 |

### 2.2 布局铺满 `theme.css / global.css / App.vue`

- 全局 `.container`：`max-width: 1400px → 1600px`，左右 padding 适度（`space-4→space-6`）
- 4 个收缩容器对齐提升（省下行）：
  - `FactorICView.vue:202` `1200px → 1440px`
  - `SourceMonitor.vue:346` `1100px → 1400px`
  - `TokenMonitor.vue:344` `1100px → 1400px`
  - `views/ConfigView.vue:140` `960px → 1280px`
- 若某 view 内用 `grid-cols-*` 固定列（`auto-fit/auto-fill` 已自适应，见审计），放大容器后自动铺开、无溢出。`Dashboard.vue:245/253` `1fr 1fr` 文案在宽容器下自动扩容。

### 2.3 写死字号 → 统一为 var()（避免缩放后不一致）

原则：**凡是与"正文/标题/说明"语义对应的写死字号，改用 `var(--font-size-*)`**；图标尺寸（px 的 icon）、极小的纯装饰（如 tab 角标）不改。

按语义映射（**实施时逐个用，不改功能**）：

| 文件 | 行号(现值) | 改为 |
|------|-----------|------|
| `GlobalIndicesStrip.vue` | 236 12px、243 12px、241 15px | `--font-size-xs` / `--font-size-xs` / `--font-size-base`（保护红/绿不变） |
|  | 150 1rem、176 11px、235 12px、245 8px | `--font-size-base` / `--font-size-xs` ... 装饰并入 |
| `FactorICView.vue` | 249 0.8rem、255 1.3rem、277 1rem、302/308 0.85rem、331 0.8rem、339/355 0.75rem、380 0.85rem、395 0.8rem | 对应 `--font-size-*`（0.8rem→sm、1.3rem→xl、0.75→xs...） |
| `FactorModelView.vue` | 494/571/667 10px、749 0.8rem | `--font-size-xs`/`--font-size-sm` |
| `SourceMonitor.vue` | 509 11px | `--font-size-xs` |
| `PortfolioManager.vue` | 966 11px | `--font-size-xs` |
| `TaskIndicator.vue` | 104 1.1rem、118 0.7rem、168 0.75rem、185 0.85rem、189 0.75rem | `--font-size-*` |
| `TaskProgress.vue` | 71/123/149 2rem（进度%大字号） | 保留（属强调）或 `--font-size-xl` |
| `views/ConfigView.vue` | 146 1.5rem、152/163/208/276 0.9rem、179 1.1rem、212/241 0.78rem、227 0.85rem、256 0.7rem | 逐条映射 `--font-size-*`（重灾区 ~10 处） |
| `DesignLoading.vue` 133 3em、`DesignWizard` 94 2em、`StrategyCheckModal` 81 1.5em | **em 相对**会随 root 放大，可不动；若求一致可改 var |
| `DesignResult.vue` / markdown(theme 803-838) | **都是 em**，随放大自动比例一致 | 不改 |

> **em 关键字**：`em` 百分比继承 font-size，本就随 root/父级放大，无需改。审计里 em 系列保持不变即可，风险集中在**写死的 px + 非 em rem**。

---

## 三、验证步骤（实施后）

1. **前端单测**：`cd frontend && npm test`（vitest，组件无重构不新增用例，仅保证不破）
2. **构建门禁**：`cd frontend && npm run build`（pre-commit 门禁同）
3. **视觉走查**（关键页）：
   - Dashboard 全局、行情条 GlobalIndicesStrip（迷你 8-15px 放大后是否换行）
   - 因子 FactorModel / FactorIC（表格高密度页：字号变大是否挤）
   - 设置 ConfigView（920px→1280px 铺满 但确认表单不拉太宽）
   - 设计工具 DashboardAiTools 三态 + 策略结果
   - 新闻/资讯、自选、组合管理、行情分析
   - 4 个收缩容器页宽度变化后网格是否溢出
   - 移动端（如有响应式）：窄屏下加大字号是否有换行破版
4. **Lighthouse**（可选，主题字号不影响性能分，仅作为回归）

---

## 附A：影响面审计（explore 子代理结论，只读）

见上一轮 `explore`（subagent sa_20260807_031502）：
- **无全局 `.card`**；`.app-card`（AppCard.vue）走 `--card-padding`=20px，会跟主题 ；
- 写死字号重灾区：`GlobalIndicesStrip`(~8 处)、`ConfigView`(~10 处)、`FactorICView`(~12 处)、`FactorModelView`、`SourceMonitor`、`TaskIndicator`、`TaskProgress`；
- 独立窄容器 4 处：`FactorIC 1200` / `Source 1100` / `Token 1100` / `Config 960`；
- 其余 `Design*` 多用 `em`（随放大自动协调）。