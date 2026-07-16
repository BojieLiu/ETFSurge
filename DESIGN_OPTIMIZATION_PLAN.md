# ETF Surge 智能组合设计链路优化方案

> **版本**：v2.0（2026-07-16）
> **状态**：已完工 3 轮提交，待开工 2 项

---

## 一、现状诊断

### 当前链路

```
用户点击"开始设计"
  → 前端 POST /portfolio/design?mode=standard   (timeout: 180s)
  → 后端 analyze.py: generate_full_design()
      ├── generate_design("standard")     (timeout: 90s)
      │   └── scan_full_pipeline()        (~5-15s, 调 fund_etf_spot_em)
      │   └── classify_assets() + optimize_layer()  (<1s)
      ├── fetch_market_sentiment()         (timeout: 20s, 3线程各15s)
      └── fetch_benchmark_stocks()         (timeout: 20s)
  → 降级: 若任意超时 → fallback to fast mode (固定候选池)
```

### 已知问题

| # | 问题 | 根因 | 优先级 |
|---|------|------|--------|
| 1 | 三种方案雷同（都偏好创业板/中证500） | external API 超时 → 降级到 fast mode → change_pct=0 → 纯按 beta 排序 | **P0** ✅ 已修复 |
| 2 | 数据采集太慢 | akshare 接口网络不稳定 | P1 |
| 3 | 完整报告简略 | 前端 generateDesignReport() 只做了数据表转储，缺 LLM 叙事 | **P1** |
| 4 | 报告排版不佳 | 缺少 .markdown-body 样式 | **P1** |
| 5 | 无历史记录 | 后端无持久化表，前端无列表入口 | P2 |
| 6 | 完整报告无分析思路 | LLM 异步报告推送未实现 | P2 |

---

## 二、已完工（3 轮提交）

### 第 1 轮：数据采集层

| 提交 | 文件 | 内容 |
|------|------|------|
| `2cde4f5` | `fetchers/etf_scanner.py` | 全市场 ETF 扫描 + 硬性过滤 + 三层自动分类 + 层内排序 |
| `2cde4f5` | `fetchers/sentiment_fetcher.py` | 市场情绪指数（涨跌比+北向+两融），7 级标签 |
| `2cde4f5` | `fetchers/benchmark_stocks.py` | 10 固定 + 5 动态核心指标股追踪 |
| `2cde4f5` | `fetchers/fundamental_fetcher.py` | 新增 fetch_fund_flow_detailed() 四类资金流拆解 |

### 第 2 轮：集成 + LLM Prompt + 前端卡片

| 提交 | 文件 | 内容 |
|------|------|------|
| `f851fda` | `services/strategy_design.py` | 集成全市场扫描、generate_full_design() 入口 |
| `f851fda` | `prompts/v1/portfolio_design.md` | 从"从零设计"改为"从 45 只候选精选" |
| `f851fda` | `DashboardAiTools.vue` | 卡片升级：方案名+图标+三层色块+关键指标显示 |

### 第 3 轮：全链路集成 + 超时修复

| 提交 | 文件 | 内容 |
|------|------|------|
| `3531923` | `routers/portfolio.py` | `/design` 端点用 generate_full_design()，响应增情绪+指标股 |
| `3531923` | `routers/analysis.py` | `/portfolio-design` 响应追加情绪+指标股 |
| `ea49df2` | `strategy_design.py` | 超时：20→90s(策略), 10→20s(情绪+指标股) |
| `ea49df2` | `sentiment_fetcher.py` | 内部线程超时 8→15s |
| `ea49df2` | `api/index.js` | 前端超时 60→180s |

---

## 三、待开工

### P1：完整报告升级

**目标**：让"完整报告"tab 展示有分析思路、有数据引用的专业报告。

**方案**：两阶段

**阶段 A（改前端 generateDesignReport，~2h）：**
- 完善 Markdown 报告模板，包含：
  - 市场环境概览（从 market_context 提取）
  - 三层设计逻辑说明
  - 每个方案的完整分析（引用具体数据）
  - 三方案对比表
- 为 `.markdown-body` 添加专业 CSS 样式（表格边框、颜色标识、层级标题）

**阶段 B（LLM 异步报告推送，~4h）：**
- LLM 不是"从头生成方案"，而是**基于已有方案数据撰写报告**
- LLM 收到的上下文：方案数据 + 市场情绪 + 指标股 + 当日新闻
- LLM 撰写内容：市场判断、每只 ETF 入选理由的叙事化表达、风险提示
- 通过 WebSocket `/ws/design-report/{session}` 异步推送
- 前端 tab 切换时：先展示阶段 A 的 Markdown，LLM 报告到达后替换

**涉及文件：**
- `DashboardAiTools.vue`（generateDesignReport + CSS）
- `llm.py`（新增 generate_design_report() 函数）
- `routers/ws.py`（新增 design-report 频道）
- `prompts/v1/portfolio_design.md`（新增报告润色 prompt）

### P2：历史记录

**目标**：能浏览之前生成的设计方案。

**方案：**

```sql
CREATE TABLE portfolio_designs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    capital DECIMAL(15,2),
    risk_profile VARCHAR(20),
    strategies JSONB,          -- 完整方案数据
    market_snapshot JSONB      -- 生成时的市场快照
);
```

| API | 功能 |
|-----|------|
| `GET /portfolio/designs?limit=10&offset=0` | 分页列出历史 |
| `GET /portfolio/designs/{id}` | 查看某次设计的详情 |
| `DELETE /portfolio/designs/{id}` | 删除某次记录 |

**前端**：方案卡片页加"历史记录"入口，以列表形式展示（日期/资金/方案摘要），点击可查看详情或应用历史方案。

**涉及文件：**
- `database.py`（新增模型）
- `routers/portfolio.py`（新增 3 个端点）
- `api/index.js`（新增 3 个方法）
- `DashboardAiTools.vue`（新增历史列表组件）

### P2：数据缓存

**目标**：解决外部 API 不稳定导致 standard 模式频繁超时的问题。

**方案：**
- 在 `fetchers/etf_scanner.py` 中增加 `@lru_cache` 或文件级缓存
- `fund_etf_spot_em` 结果缓存 60s
- 重仓股数据缓存 3600s（季频数据）
- 情绪/北向数据缓存 120s

---

## 四、性能预算

### 正常网络（akshare 响应正常）

| 步骤 | 耗时 | 说明 |
|------|------|------|
| `fund_etf_spot_em` | ~5-8s | 全量 ETF 基础数据（一次调用） |
| 过滤+分类+排序 | <50ms | 纯本地 |
| 情绪采集（3 线程并行） | ~5-8s | 涨跌比+北向+两融 |
| 指标股采集 | ~5-8s | 10 只并行 |
| 约束优化 | <1s | SLSQP |
| **总计** | **~10-20s** | |

### 弱网络（必须超时降级）

| 降级路径 | 耗时 | 方案质量 |
|---------|------|---------|
| `sentiment` 超时 → 默认中性 | +0s | 情绪数据缺失 |
| `benchmark` 超时 → 空列表 | +0s | 指标股数据缺失 |
| `scan` 超时 → fallback fast mode | ~2s | 固定候选池，change_pct=0 → 三个方案相似 |

---

## 五、约束规则

### 已实现（代码强制）

| 规则 | 值 | 执行位置 |
|------|-----|---------|
| 三层结构 | core + satellite + defense，每层至少 1 只 | `optimize_layer()` |
| 核心层必需 | 510300(沪深300) + 560600(中证A500)，各≥5% | `_enforce_name_count()` |
| 权重范围 | 每只 1%~30% | `optimize_layer()` SLSQP bounds |
| 标的数量 | 8~15 只 | `_enforce_name_count()` |
| 权重和 | 恰好 100% | SLSQP equality constraint |

### 层预算（建议值，非强制）

| 层 | 防御型 | 平衡型 | 进攻型 |
|----|--------|--------|--------|
| 核心(宽基) | 55% | 55% | 50% |
| 卫星(行业主题) | 25% | 30% | 40% |
| 防御(避险) | 20% | 15% | 10% |

---

## 六、核心决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 方案生成方式 | 算法做骨架 + LLM 做润色 | 约束可编码、可验证；LLM 只做叙事判断 |
| 三层分类方式 | 规则（关键词+排除法） | 分类是确定性问题，LLM 不可靠 |
| ETF 代码来源 | 候选池硬编码（已验证真实代码） | 避免 LLM 输出"代码待核实" |
| 完整报告 | 前端自生成 Markdown + 异步 LLM 润色 | 不阻塞卡片展示，用户先看到数据方案 |
| 情绪/指标股降级 | 超时返回默认值，不阻塞主流程 | 方案是第一优先级 |
| 超时兜底 | fallback 到 fast mode（静态候选池） | 绝对不返回空结果 |
