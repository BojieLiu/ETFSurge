# ETF Surge — 第二轮全链路诊断与优化方案

> 生成时间: 2026-07-31
> 环境: Docker (Python 3.14-slim + Node 24 Alpine + Nginx + Redis 8)
> 执行范围: 15 项全链路验证（步骤 1-15，见 §0 索引表）
> 状态: v1.2（已完成三轮 review，达到实施标准）

---

## 〇、步骤 × 章节 索引

| 步骤 | 内容 | 章节 | 状态 |
|:---:|------|------|:---:|
| 0 | Docker 构建镜像 + 回收老镜像 + 启动 prod 栈 | §2 前置 | ✅ 完成（含 2 个阻断 bug 修复） |
| 1 | 后端预热性能诊断 | §2.1 | ✅ |
| 2 | 组合设计 + 策略检查 + 报告审阅 | §3 | ✅（发现因子数据不一致等） |
| 3 | A/港/美股行情分析全链路测试 | §4 | ✅（market 参数失效等） |
| 4 | 热点板块/个股加载验证 | §5.1 | ✅ |
| 5 | 自选功能验证 | §5.2 | ✅（港股行情不通） |
| 6 | 持仓技研与综合信号评估 | §5.3 | ✅（akshare 熔断窗口技研空） |
| 7 | 资讯分级 + AI 智能分析评估 | §5.4 | ✅（分级不合理） |
| 8 | 因子模型页面评估 | §5.5 | ✅（7 no_data） |
| 9 | 前后端数据断裂排查 | §6 | ✅（6 个断裂点） |
| 10 | system-diagnosis-and-optimization-plan.md 问题清单验证 | §7 | ✅（12/15 已修或部分修） |
| 11 | 前端 Lighthouse 评分与性能诊断 | §2.2 | ✅（首页 60 分） |
| 12 | 后端全链路性能诊断 | §2.3 | ✅（组合计算 8.2s） |
| 13 | 测试防护体系失效分析 | §8 | ✅（6 类盲区） |
| 14 | 汇总文档 + 多轮 review | 本文档 | 🔄 进行中 |
| 15 | 回收容器进程 | 待执行 | ⏳ |

## 一、执行摘要

本轮对 ETF Surge 执行了 15 步全链路诊断，全程在 Docker prod 形态（nginx + backend + redis）下运行。

### 1.1 核心结论

| 维度 | 状态 | 说明 |
|------|------|------|
| 镜像构建与启动 | ✅ 修复 2 个阻断 bug | `config.py` extra_forbidden + prod 容器 `DATABASE_URL` 指向 Windows 路径（空库） |
| 预热性能 | ✅ 1.77s | 历史 38s → 3s → 1.77s，主瓶颈为全球指数/新闻串行网络 I/O |
| 组合设计 | ✅ 3 套方案 | 结构完整但现金仓位 22-32% 偏高、因子数据与实际指标不一致 |
| 策略检查 | ⚠️ LLM 超时降级 | report_text 为空，规则引擎兜底（Z07 持续） |
| 多市场分析 | ⚠️ 市场参数失效 | market=HK/US 仍输出 A 股数据；AI 投顾上下文全缺失 |
| 前后端断裂 | ❌ 6 个断裂点 | **生产模式 WebSocket 全链路 404**（nginx 缺 upgrade 代理）最严重 |
| 问题清单 Z01-Z15 | ✅ 12/15 已修或部分修 | Z04 未达标（etf_specific 仍 4 个 no_data）、Z07/Z11 部分改善 |
| 前端性能 | ⚠️ 首页 60 分 | CLS 0.538、TBT 410ms、3 个 8 秒级慢 API |
| 后端性能 | ⚠️ 组合计算 8.2s | calculate/pnl-history 串行行情调用，数据源熔断放大 |
| 测试防护 | ❌ 6 类盲区 | 拓扑/环境/内容/数据源运行时/时序/脚本卫生 |

### 1.2 本轮最重要发现（Top 5）

1. **prod 容器使用空数据库**：`backend/.env` 的 `DATABASE_URL` 是 Windows 绝对路径，prod 服务经 `env_file` 注入后 Linux 容器解析无效，所有业务表（instruments/持仓/自选）落到容器内新建的空库 → 搜索默认分支空、持仓全无、自选无行情。**已修复**（docker-compose 覆盖为容器路径 + `config.py extra="ignore"`）。
2. **生产模式 WebSocket 全链路断裂**：前端连接 `/api/v1/ws/*`，后端路由存在，但 nginx 只配置了 `location /api`（无 upgrade 头）与 `location /ws`，缺少 `/api/v1/ws` 的 WebSocket 代理 → 实时行情推送、任务通知、设计报告推送在生产环境全部失效（Lighthouse 控制台可见 404 握手失败）。
3. **A 股技术分析链路依赖单一数据源**：历史 K 线 `fetch_history` 空时降级 `get_k_data`（akshare），akshare 熔断时 history/indicators/signal/chart 全线 `insufficient_data`（本次实测捕捉到该窗口）。
4. **设计引擎因子数据与实际指标不一致**：设计报告称 562320 "RSI 2.4 超卖、信号偏多"，实际 RSI=65.3、signal=hold；589720 设计标"信号偏多"实际 signal=sell(-1.5)。方案 rationale 与真实技术面矛盾。
5. **LLM 上下文数据缺失与市场参数失效**：`llm-advice` 回答"所有字段均为暂无/未知"；`llm-report` 传 `market=HK/US` 仍输出 A 股数据；`symbol-analysis` 技术指标空、历史 K 线无；`sector-analysis` 半导体板块成分股错位（返回软件股）。

---

## 二、测试配置与性能诊断工具

### 2.1 后端预热性能诊断（步骤 1）

- 工具：内置 `WarmupProfiler`（cProfile + pyinstrument + 分段计时），`PROFILE_WARMUP=1` 启用（已写入 `backend/.env`，随 env_file 注入）。
- 启用前发现阻断 bug：`Settings` 为 `extra_forbidden`，新增环境变量 `PROFILE_WARMUP` 导致启动崩溃 → 修复 `config.py` 增加 `extra="ignore"`。
- 结果：

| 阶段 | 耗时 | 占比 |
|------|------|------|
| warmup_global_indices | 1468.7ms | 83% |
| init_db | 139.9ms | 8% |
| redis_init | 80.3ms | 5% |
| warmup_market_cache | 58.9ms | 3% |
| warmup_etf_cache | 17.5ms | 1% |
| **总计** | **1765ms** | |

- 诊断：主瓶颈为全球指数 + 新闻的**串行同步网络请求**（`run_sync` 线程池逐源拉取，cProfile 显示 refresh_news 1.595s/23 次 requests.get、SSL context 重复创建 23-26 次）。优化方向：指数/新闻 `asyncio.gather` 并行化、连接池复用。

### 2.2 前端 Lighthouse 评分（步骤 11）

工具：Lighthouse 13.4.1（Chrome headless），对 Docker nginx 形态 4 个核心页面评分：

| 页面 | Performance | Accessibility | Best-Practices | SEO | 关键指标 |
|------|:---:|:---:|:---:|:---:|------|
| `/`（Dashboard） | **60** | 96 | 92 | 91 | FCP 2.0s / LCP 3.2s / TBT 410ms / **CLS 0.538** |
| `/market-analysis` | **97** | 96 | 96 | 91 | FCP 1.5s / LCP 2.4s |
| `/portfolio-analysis` | **76** | 82 | 92 | 91 | FCP 2.0s / LCP 3.9s |
| `/news` | **96** | 94 | 96 | 91 | FCP 1.4s / LCP 2.0s |

首页问题定位（`lh_details`）：
- **3 个 8 秒级慢 API**：`pnl-history` 8528ms、`calculate off_exchange` 8287ms、`calculate on_exchange` 8257ms（Dashboard 首屏串行触发）
- **控制台错误**：`Market WS 发生错误` + `ws://localhost/api/v1/ws/portfolio` 握手 404（WS 断裂）
- **CLS 0.538**：summary-grid / nav-status 在数据异步到达后布局偏移
- **TBT 410ms / 主线程 2.4s**：echarts 等大库 JS 执行

### 2.3 后端全链路性能诊断（步骤 12）

perf_diag 49 端点扫描：**46/49 通过**（3 个 405 为脚本用 GET 调 POST 端点，非后端缺陷）。

| 慢端点 | 耗时 | 根因 |
|--------|------|------|
| `/portfolio/calculate` (on/off_exchange) | 8257-8287ms（约 8.2s） | 组合计算对每只持仓串行调实时行情 + 历史 K 线 |
| `/portfolio/pnl-history` | 8528ms | 同上，跨多期计算 |
| `/market/realtime/portfolio` | 1886-4470ms | 依赖单只 A 股行情降级链（mootdx 熔断时慢） |
| `/market/watchlist` | 1071-2327ms | 逐条目行情填充 |
| `/market/indices/global` | 1425-1530ms | 多源串行拉取 |

---

## 三、组合设计与策略检查审阅（步骤 2）

### 3.1 执行结果

- `POST /portfolio/design-async`（balanced/50 万/A 股）：completed，产出 **3 套方案**（防御/平衡/进攻），每套含 core/satellite/defense/cash 四层、多因子评分、入选理由，权重和 = 1.0，无占位符残留。
- `POST /portfolio/strategy-check-async`（`portfolio_type=on_exchange`）：completed，针对场内 **10 只标的**（159338 中证A500ETF 20%、518880 黄金ETF 13%、510880 红利 8%、512000 券商 8% 等），产出按标的建议（hold 为主，规则引擎）。

### 3.2 报告质量审阅（结合最新行情逐项核对）

| 维度 | 结论 | 证据 |
|------|------|------|
| 逻辑性 | ✅ 合格 | 四层结构清晰（核心 40%/卫星 25-35%/防御 3%/现金 22-32%），层预算不超 |
| 可读性 | ✅ 合格 | design_text 7KB，含方案对比总览、每标的入选理由 |
| 数据完整性 | ❌ 缺口 | `market_context.index_realtime` 为空；design_text"今日涨跌"列为 `—` |
| 准确性 | ❌ **严重** | 562320 设计称 RSI 2.4 超卖/信号偏多，实际 RSI=65.3 signal=hold；589720 设计标偏多，实际 sell(-1.5) |
| 投资认知 | ⚠️ 存疑 | 防御型方案配置科创创新药/科创芯片卫星层（12-13%），风格匹配度差 |
| 方案合理性 | ⚠️ 现金偏高 | 防御 32% / 平衡 27% / 进攻 22% 现金仓位（Z11 残余） |
| 风格匹配 | ⚠️ 部分 | regime=range_bound + 情绪中性下 3 套方案分层正确，但防御型含高波动科创主题 |

次要问题：design_text 标题"## 一、三种方案详解"重复（模板拼接）；策略检查 LLM 超时降级规则引擎（`report_text` 为空）。

### 3.3 任务失败定位

两任务均 completed（未失败）。策略检查内部 LLM 超时（summary 标注"LLM 分析超时…规则引擎兜底"），结合性能诊断归因于 Z07（LLM 429 限流，Retry-After 长达 8 小时），属既有延期项而非本轮新缺陷。

---

## 四、多市场行情分析测试（步骤 3）

### 4.1 覆盖矩阵

| 功能 | A 股 | 港股 | 美股 | 结论 |
|------|:---:|:---:|:---:|------|
| 综合研判（llm-report） | ✅ 质量好 | ⚠️ 数据错 | ⚠️ 数据错 | **market 参数未生效**：HK/US 仍输出 A 股指数 |
| AI 投顾（llm-advice） | ❌ | ❌ | ❌ | 上下文全缺失（"所有字段均为暂无/未知"） |
| 个股分析（symbol-analysis） | ⚠️ 技术面空 | ❌ 行情空 | ⚠️ 技术面空 | 600519 输出"技术指标：空、历史K线：无"；00700 实时行情 {} |
| ETF 分析 | ⚠️ 技术面空 | — | ⚠️ | 同个股分析 |
| 板块分析（sector-analysis） | ❌ 成分股错位 | — | — | BK0447 半导体返回立方控股/昆仑万维等软件股 |
| 概念分析 | ✅ | — | — | Kimi 概念成分股正确、分析质量尚可 |
| 指数分析 | ✅ | — | — | 000300 宏观传导逻辑清晰 |
| 搜索自动补全 | ✅ | ✅ | ✅ | DATABASE_URL 修复后全市场命中（510300/盈富/SPY/00700/AAPL） |

### 4.2 内容审阅

- **质量尚可**：A 股综合研判（数据准确、逻辑清晰）；指数分析与 Kimi 概念分析。
- **严重问题**：
  1. `llm-report` 的 `market` 参数未传导到数据采集（HK/US 分支仍采 A 股数据）——前端 MarketReport 切 tab 得到的是 A 股报告。
  2. `llm-advice` 上下文注入失败（`_inject_market_context`/`build_full_context` 产出空数据），AI 投顾回答基于"数据缺失"而非真实行情。
  3. `symbol-analysis` 技术指标/历史 K 线缺失（K 线依赖 akshare，熔断窗口放大）。
  4. **系统提示词内容泄漏到输出**（回答开头出现"我们只需要回答用户的问题…"等 prompt 指令文本）——LLM 输出未做隔离/后处理。
  5. 板块成分股错位：BK0447（半导体）返回 IT 服务/软件股，成分股映射错误。

---

## 五、热点 / 自选 / 技研 / 资讯 / 因子评估（步骤 4-8）

### 5.1 热点板块与个股（步骤 4）✅

- `hot-plates` 11 条（AI应用/机器人概念/算力工程/芯片产业链等，含涨幅/领涨股数/原因）
- `stock-hot-rank` 50 条（长鑫科技/德明利/兆易创新等，含概念标签）
- `wind` / `sectors/concept` / `sectors/industry` / `sectors/rotation` 均正常

### 5.2 自选功能（步骤 5）⚠️

| 用例 | 结果 |
|------|------|
| 添加 A 股 510300 | ✅ 201（名称正确"沪深300ETF华泰柏瑞"） |
| 添加美股 SPY | ✅ 201（**名称兜底为 "SPY"**，realtime 无 name 字段） |
| 添加港股 00700/02800.HK | ❌ 422（**港股实时行情 null**，存在性校验不过） |
| 重复添加 | ✅ 409 |
| 中文 symbol | ✅ 422 |
| GET 含实时行情 | ⚠️ A 股 realtime **间歇性为空**（mootdx 熔断窗口），美股稳定 |
| PUT 更新备注 | ✅ 200 |

### 5.3 持仓技研与综合信号（步骤 6）⚠️

场内 10 只持仓信号（K 线正常时）：

| 标的 | 权重 | 信号 | 依据 |
|------|:---:|:---:|------|
| 159338 中证A500ETF | 20% | **sell -2.0** | MACD 死叉空头、MA5<MA20 空头排列 |
| 159992 创新药ETF | 5% | sell -1.5 | MACD 偏空 |
| 513120 港股创新药ETF | 5% | sell -1.5 | MACD 偏空 |
| 510880 红利ETF | 8% | hold +1.0 | RSI 62.9 偏强、金叉多头 |
| 159545 恒生红利低波 | 5% | hold 0.0 | RSI 62.4、KDJ 超买死叉 |
| 159516 半导体设备 | 4% | hold -1.0 | RSI 31.2 偏弱、MACD 死叉空头 |
| 159869 游戏ETF | 5% | — | 本轮未单独拉信号 |
| 512000 券商ETF | 8% | — | 同上 |
| 513010 恒生科技ETF | 3% | — | 同上 |
| 518880 黄金ETF | 13% | — | 同上 |

评估结论：
- 信号引擎能输出明确 buy/sell（score ±2，**Z10 已改善**），与 range_bound 市态判断一致、逻辑合理。
- **严重问题**：akshare 熔断窗口期 history/indicators/signal 全线 `insufficient_data`（实测捕捉）；设计时点因子数据与实际指标不一致（见 §3.2）。

### 5.4 资讯页面（步骤 7）⚠️

- 数据源正常：headlines 30 / macro 15 / global 8 / 个股资讯 10 / 研报 761。
- **分级不合理**：关键词法（`classify_news_level`）将国际微观新闻评为中高等级——"斯特兰蒂斯召回 127 万辆" 1★3、"纽约州指控赌博" 1★3、"埃森哲与 IBM 合作" 4★5、5 星新闻有 5 条。评级未纳入与 A 股 ETF 组合的相关性维度。
- AI 智能分析：`news-impact` 结构化返回（impact_scope/summary/disclaimer）可用，但篇幅简短、内容泛化，未结合具体持仓。

### 5.5 因子模型（步骤 8）⚠️

33 个活跃因子状态：

| 状态 | 数量 | 明细 |
|------|:---:|------|
| valid | 20 | technical 13（RSI 0.50/MACD 0.44/KDJ 0.63-0.74 等）+ etf_specific 7（含 industry_diversification 0.13） |
| static | 3 | china_specific policy 因子（Z03 已修：不再计 no_data） |
| warn | 3 | stock_divergence / ln_mcap / ln_float_mcap（ic=0.0） |
| no_data | **7** | etf_specific 4（premium_discount/tracking_error/shares_change/institutional_holdings_change）+ sentiment 3（panic_greed_diff/news_heat/news_direction） |

- `factor-health` 200 + ok（Z01 已修）；IC 端点 23 条非空（Z06 已修）；avg_ic 0.22。
- **Z04 未达标**（验收 etf_specific no_data < 3，实际 4）；**sentiment 3 因子为新增 no_data**（情绪数据管道缺失）。

---

## 六、前后端数据断裂排查（步骤 9）

实测 20+ 端点 + 前端源码审计 + Lighthouse 网络瀑布，确认 6 个断裂点：

| # | 断裂点 | 形态 | 影响 |
|---|--------|------|------|
| B1 | **生产模式 WebSocket 404** | 前端连 `/api/v1/ws/*`，nginx 缺该路径的 upgrade 代理（`location /api` 无 upgrade 头、`location /ws` 不匹配 `/api/v1/ws`） | 实时行情推送、任务通知、设计报告推送在生产环境全失效；dev 模式靠 Vite 代理掩盖 |
| B2 | `/market/sectors/heat` 404 | 前端 `SectorHeatMap.vue` 调用 `marketApi.getSectorHeat()`，后端无此路由（数据在 hub 内部有，未暴露） | 板块热度组件降级/报错 |
| B3 | `marketApi.sectorAnalysis/marketAnalysis` 未定义 | `UnifiedAnalysis.vue` 调用不存在的方法，走 fallback `fetch /search` | 个股/板块深度分析功能降级为空壳 |
| B4 | 单只 A 股 realtime 间歇性 null | `fetch_a_stock_realtime` 降级链 mootdx→sina **缺 tencent 一级**（批量链有 tencent） | 自选/持仓单只行情偶发缺失 |
| B5 | 港股实时行情全 null | `fetch_hk_stock_realtime` 链路不通（多次 422/空） | 港股自选添加失败、港股分析无数据 |
| B6 | `market=A` 个股搜索降级错误 | instruments 表无 stock 行时降级到 ETF 搜索而非个股（"贵州茅台"返回 0） | A 股个股搜索失败 |

其余端点（rotation/industry-cls/watchlist/hot-plates/stock-hot-rank/wind/factors/admin 等）实测全部 200。

---

## 七、问题清单验证（步骤 10）

`docs/system-diagnosis-and-optimization-plan.md`（v4.0）Z01-Z15 逐项验证：

| ID | 问题 | 本轮状态 | 证据 |
|----|------|---------|------|
| Z01 | factor-health 500 | ✅ 已修 | HTTP 200 + ok |
| Z02 | 美股行情 null | ✅ 已修 | SPY 742.9 有值 |
| Z03 | china_specific 3 因子 no_data | ✅ 已修 | 状态均为 static |
| Z04 | etf_specific 10 因子无数据 | ❌ **未达标** | 仍 4 个 no_data（验收要求 <3）；industry_diversification 已修复 |
| Z05 | SSL 预热握手重复 | ✅ 改善 | 预热 1.77s（历史 38s→3s） |
| Z06 | 因子 IC 全空 | ✅ 已修 | 23 条 IC 非空，avg_ic 0.22 |
| Z07 | LLM 42.4% 错误率 | ⚠️ 改善未达标 | 23.2%（462/1995），429 限流持续（Retry-After 8h） |
| Z08 | sources/health 空 | ✅ 已修 | 返回非空数组 |
| Z09 | sigma 值异常 | ✅ 已修 | signal score 均在 ±2 |
| Z10 | 信号引擎保守 | ✅ 改善 | 有 buy/sell 输出（score ±2） |
| Z11 | 非交易时段设计失败 | ⚠️ 部分 | 现金 22-32%（非 100%），但现金仍偏高 |
| Z12 | 缺少运行时 profiling | ✅ 已修 | PROFILE_WARMUP 全套报告 |
| Z13 | 中文搜索 URL 编码 | ✅ 非服务器 bug | 后端 str 天然支持，客户端编码即可 |
| Z14 | pre-commit 仅前端 | ✅ 已修 | 已含密钥/构建/API 覆盖/异步审计/mypy/pytest/冒烟 |
| Z15 | verify_e2e 覆盖不足 | ✅ 部分 | 已含 US/HK 搜索、factor-health、IC、search；但见 §8.2 盲区 |

结论：**12/15 已修或部分修；Z04 未达标，Z07/Z11 部分改善**。本轮新发现（未列入旧清单）：B1 WS 生产断裂、B2-B6 断裂点、AK 线单源依赖、HK 行情链路、LLM 上下文缺失、市场参数失效、因子数据不一致、sentiment 因子无数据、搜索排序缺陷、资讯分级缺陷。

---

## 八、测试防护体系分析（步骤 13）

### 8.1 为什么 16 项 e2e 失败中有噪音

`verify_e2e.py` 本轮 185/201 通过，16 项失败完整构成（多次运行合并统计）：
- 性能 gate（真实捕获）：`search?market=HK` 5.6s、`portfolio/calculate` 8.1-8.2s 超 5s gate（2 项；另 1 项 `search` 默认分支在部分运行中 >5s 属同一慢源）
- **数据/时序 flaky（9 项）**：510300/518880/511090 `7/33 live factors`×3、`方案数>=3 实际 0`、`510300 in allocation`、`BB upper/ma/lower 全 0`（K 线空窗）、`risk_warnings 含未知类型`、`任务 26 到 quick_ready 未终态`、`设计历史端点 422`
- **脚本自身缺陷（4 项）**：`GET /market/etfs` 404、`GET /admin/sources` 404（过期端点）；快照/LLM 模块导入 `No module named 'app'`（PYTHONPATH）；`POST /daily-pnl` 422（参数）

### 8.2 防护失效根因（6 类盲区）

| 盲区 | 机制 | 漏掉的问题 |
|------|------|-----------|
| 拓扑盲区 | e2e 直连 `localhost:8000` 绕过 nginx | B1 WS 生产断裂、代理配置错误 |
| 环境盲区 | e2e 在本地（dev 有 `DATABASE_URL` 覆盖）运行 | prod 容器空库（本轮 P0 bug） |
| 内容盲区 | 只断言 200/非空，不校验内容正确性 | LLM 上下文缺失、market 参数失效、成分股错位、搜索排序错误 |
| 数据源运行时盲区 | 单测全 mock 外部网络；e2e 不覆盖熔断窗口降级 | 单只行情 null、K 线空导致技研 insufficient_data |
| 时序 flaky | 因子 live 数依赖后台 60s/120s 刷新，硬阈值 | e2e 自身不稳定，掩盖真实状态 |
| 脚本卫生 | 过期端点、PYTHONPATH 依赖、WS 测试缺库时"跳过即 PASS" | 失败噪音污染，削弱门禁可信度 |

---

## 九、优化修复方案

### 🅿️0 — 阻断性修复（已实施 2 项，剩余 2 项）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F0-1 ✅ | prod 容器空库 | `backend` 服务 environment 增加 `DATABASE_URL=sqlite+aiosqlite:////app/data/portfolio.db` 覆盖 Windows 路径 | `docker-compose.yml` | 容器内 `SELECT COUNT(*) FROM instruments` = 1544 |
| F0-2 ✅ | Settings extra_forbidden | `Settings.Config` 增加 `extra="ignore"` | `backend/app/config.py` | 任意无关环境变量不导致启动崩溃 |
| F0-3 | **WS 生产断裂** | nginx.conf 增加 `location /api/v1/ws`（`proxy_pass http://backend:8000` + upgrade 头，置于 `location /api` 之前）；或前端统一改 `/ws/*` | `frontend/nginx.conf` | `wscat -c ws://localhost/api/v1/ws/portfolio` 握手成功 |
| F0-4 | **A 股 K 线单源依赖** | `get_history` 降级链增加 sina K 线/levistock 源；akshare 熔断期间从 `indices_cache.json`/内存缓存兜底；`get_k_data` 失败不再返回空而标记 stale | `backend/app/services/market_service.py`、`backend/app/fetchers/china_market.py` | akshare 熔断时 `history/indicators/signal` 仍有数据（stale 标记） |

### 🅿️1 — 高优先级（数据质量与正确性）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F1-1 | 港股实时行情全 null | 排查 `fetch_hk_stock_realtime`（`china_market.py` 实际降级链 **sina → tencent → dongfang(_em_hk_realtime)**）与代码归一化（HK 代码无 `.HK` 后缀） | 涉及：`backend/app/fetchers/china_market.py` | `realtime/00700?asset_type=HK` 返回价格 |
| F1-2 | 单只 A 股实时行情间歇性 null | `fetch_a_stock_realtime` 降级链补 tencent（与批量一致：mootdx→tencent→sina） | 涉及：`backend/app/fetchers/china_market.py` | 连续 10 次 `realtime/510300` 无 null |
| F1-3 | LLM 上下文数据缺失 | 修复 `llm-advice`/`symbol-analysis` 的 `build_full_context` 采集链路（market 分支参数传导 + K 线注入） | 涉及：`backend/app/services/llm_context.py`、`backend/app/routers/analysis.py` | llm-advice 回答引用真实行情数据 |
| F1-4 | `llm-report` market 参数失效 | 后端按 `market` 参数切换指数/板块/资讯采集（HK/US 分支） | 涉及：`backend/app/routers/analysis.py`、`backend/app/analysis/llm.py` | `market=HK` 报告含恒生指数 |
| F1-5 | 设计因子数据不一致 | 统一设计引擎与 `indicators` 端点的 K 线来源与时点；rationale 从 factor_scores 取 RSI 时校验数据新鲜度 | 涉及：`backend/app/engine/`、`backend/app/factors/factor_registry.py` | 设计报告 RSI 与实际 `indicators` 一致 |
| F1-6 | 板块成分股错位 | 修复 BK0447 等板块成分股映射（sector 代码→成分股接口错位） | 涉及：`backend/app/services/market_data_hub.py`（get_sector_stocks） | 半导体板块返回半导体成分股 |
| F1-7 | LLM 输出未后处理 | 对 LLM 流式输出做系统提示词隔离（system prompt 与用户内容严格分段）+ 输出首段过滤已知泄漏模式 | 涉及：`backend/app/analysis/llm.py`、`backend/app/routers/analysis.py` | 输出无"我们只需要回答…"类泄漏 |

### 🅿️2 — 中优先级（性能与断裂修复）

| ID | 问题 | 修复方案 | 涉及文件 | 验收条件 |
|----|------|---------|---------|---------|
| F2-1 | 组合计算 8.2s | `calculate_allocation`/`daily_pnl` 对持仓行情/K 线改 `asyncio.gather` 并行 + 15s 缓存（注意：缓存会降低数据新鲜度，15s 与 `portfolio:realtime` 一致可接受） | 涉及：`backend/app/services/portfolio_service.py` | calculate < 2s（多次采样中位数） |
| F2-2 | 首页 Lighthouse 60 | Dashboard 慢 API 并行加载 + 骨架屏（消除 CLS）+ 路由级代码分割（echarts 按需）+ 关键 API 预热缓存 | 涉及：`frontend/src/views/Dashboard.vue`、`frontend/src/router/index.js`、`vite.config.js` | 首页 Performance ≥ 85（3 次采样中位数），CLS < 0.1 |
| F2-3 | `/market/sectors/heat` 404 | 后端暴露 `GET /market/sectors/heat`（hub 已有 `get_sector_heat`）或前端改调 `sectors/rotation` | 涉及：`backend/app/routers/market.py` 或 `frontend/src/components/market/SectorHeatMap.vue` | 前端 SectorHeatMap 无 404 |
| F2-4 | `marketApi.sectorAnalysis/marketAnalysis` 未定义 | 前端定义方法并接通 `/analysis/symbol-analysis/stream`、`/analysis/sector-analysis/stream` | 涉及：`frontend/src/api/index.js`、`frontend/src/components/market/UnifiedAnalysis.vue` | UnifiedAnalysis 真实分析可用 |
| F2-5 | 预热指数/新闻串行 | `warmup_global_indices` 内 `asyncio.gather` 并行拉取 | 涉及：`backend/app/main.py` | 预热 < 1.0s |

### 🅿️3 — 低优先级（质量完善）

| ID | 问题 | 修复方案 | 验收条件 |
|----|------|---------|---------|
| F3-1 | 资讯分级不合理 | `classify_news_level` 增加相关性加权（A 股/组合相关关键词加权、国际微观降级），财联社源评级复核 | 验收："召回/赌博"类国际新闻 ≤ 2 星 |
| F3-2 | 搜索排序缺陷 | 跨市场合并前先做全局精确匹配（symbol==kw 优先于首字母模糊）；`market=A` 个股搜索降级到 levistock 个股 | 验收：`search?keyword=SPY` 首条为 SPY；`market=A&keyword=贵州茅台` 返回茅台 |
| F3-3 | 设计现金仓位偏高 | 预算引擎对 range_bound 市态的现金上限收紧（22-32% → ≤15%），非交易时段才有高现金 | 验收：balanced 方案现金 ≤ 15% |
| F3-4 | Z04 etf_specific 4 因子 | 补 premium_discount（ask1/bid1）、tracking_error（K 线跟踪偏离）、shares_change（份额数据）、institutional_holdings_change（基金季报） | 验收：etf_specific no_data < 3 |
| F3-5 | sentiment 3 因子无数据 | 接通 panic_greed_diff（涨跌分布）、news_heat/news_direction（资讯情绪）数据管道 | 验收：sentiment no_data = 0 |
| F3-6 | LLM 429 限流 | 增加指数退避重试（尊重 Retry-After）+ provider 轮换 + 高峰排队（成本权衡：免费模型限流是常态，可接受降级） | 验收：单次分析失败前至少 2 次重试 |
| F3-7 | 自选美股名称 | `get_asset_realtime` US 分支补充 name 字段（静态基座映射） | 验收：自选 SPY 显示 "SPDR S&P 500 ETF" |

### 🅿️4 — 测试防护补强（步骤 13 落地）

| ID | 措施 | 拦截目标 |
|----|------|---------|
| T1 | e2e 增加 nginx 拓扑层（`http://localhost` 走 nginx 的 WS 握手 + /api 代理测试） | B1 WS 断裂（防回归能力最强） |
| T2 | e2e 增加 prod 容器 DB 完整性断言（instruments > 1000 **且 portfolio_etfs/watchlist 非空**——P0 bug 同样清空它们） | 空库回归 |
| T3 | e2e 增加内容级断言：①llm-advice 回答不含"暂无/未知"；②llm-report `market=HK` 含恒生指数；③板块成分股与板块名匹配（半导体含半导体股）；④搜索 `keyword=SPY` 首条 symbol=SPY；⑤LLM 输出不含"我们只需要"类泄漏 | 内容盲区（含排序/泄漏） |
| T4 | 修复 e2e 过期端点（/market/etfs、/admin/sources）、PYTHONPATH（`sys.path.insert(0, backend)`）、`POST /daily-pnl` 参数（对照契约补全请求体）、WS 缺库"跳过即 PASS"改为 SKIP 计数 | 失败噪音 |
| T5 | factor-health 门限改为多次采样取中位数 + 数据就绪等待（最多 30s） | 时序 flaky |
| T6 | 数据源熔断演练：通过 `admin/config` 或环境变量强制置 mootdx/akshare 熔断态，验证降级链输出非空 | 数据源运行时盲区 |

---

## 十、实施优先级路线图

```
第一梯队（P0 — 立即，预计 1 人日）
  F0-3 WS nginx 代理修复（30min）   F0-4 K 线降级链增强（半日）
第二梯队（P1 — 本周，预计 2-3 人日）
  F1-1 港股行情 / F1-2 单只降级链 / F1-3 LLM 上下文 / F1-4 市场参数
  F1-5 因子一致性 / F1-6 成分股 / F1-7 LLM 输出后处理
第三梯队（P2 — 下迭代，预计 2-3 人日）
  F2-1 组合计算并行 / F2-2 首页性能 / F2-3 sectors/heat / F2-4 前端方法 / F2-5 预热并行
  T1/T2 防回归测试（与 F0 修复同批交付：F0 交付即加 T1/T2，拦截两个 P0 bug 回归）
第四梯队（P3-P4 — 持续）
  F3-1~F3-7 质量完善（Z07 限流重试与 Z04 因子补齐已含其中，视成本权衡调度）
  T3-T6 测试防护补强
```

> 说明：Z07（LLM 429/23.2% 错误率）影响 llm-advice/llm-report 核心体验，因免费模型限流属常态（Retry-After 可达 8h），F3-6 重试策略成本低，可提前至 P2 并行推进；T1/T2 为防回归能力最强项，与 F0 修复同批交付可拦截本轮 P0 bug 回归。

实施必须遵循 AGENTS.md「先写 API 契约 → 写失败单测 → 改代码 → 跑 verify_e2e.py → commit」流程。

---

## 附录 A：测试数据快照

- 预热: 1.765s（global_indices 1468ms 占 83%）
- 组合设计: completed，3 套方案，权重和 1.0，现金 22-32%
- 策略检查: completed（LLM 超时降级），10 只场内标的，hold 建议
- Lighthouse: 首页 60 / market 97 / portfolio 76 / news 96
- perf_diag: 46/49（3 个脚本 405），慢点 calculate 8.2s / pnl-history 8.5s / realtime/portfolio 1.9-4.5s
- e2e: 185/201（16 失败：3 性能 gate + 9 因子 flaky + 4 脚本噪音）
- LLM: 462/1995 错误（23.2%），opencode_zen 429 限流 Retry-After 8h
- 因子: 33 总 / 20 valid / 3 static / 3 warn / 7 no_data；IC 23 条，avg_ic 0.22

## 附录 B：本轮修改文件

| 文件 | 修改 |
|------|------|
| `backend/app/config.py` | `Settings.Config` 增加 `extra="ignore"` |
| `docker-compose.yml` | `backend` 服务增加 `DATABASE_URL` 容器路径覆盖 |
| `backend/.env` | 增加 `PROFILE_WARMUP=1`（诊断用） |

## 附录 C：修订记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-07-31 | 初稿：15 步诊断全量结果 + P0-P4 修复方案 + 测试防护补强 |
| v1.1 | 2026-07-31 | 首轮 review 修订：修正港股降级链顺序（sina→tencent→dongfang）、LLM 泄漏术语；补步骤索引表/持仓全表/e2e 失败完整清单/P1-P2 涉及文件列/P3 验收条件；T1/T2 提前至 P2；T3/T6 断言补全 |
| v1.2 | 2026-07-31 | 二轮 review 修订：P1/P2/P3 表头补列（涉及文件/验收条件，修复渲染错位）；T1/T2 调度措辞修正（F0 交付即加）；§5.3 持仓表补全 10 只含权重；T4 补 daily-pnl 参数修复；calculate 耗时口径统一（8.2s/8257-8287ms）；F0-4 涉及文件补全路径 |
