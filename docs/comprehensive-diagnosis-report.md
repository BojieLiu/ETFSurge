# ETF Surge 全链路诊断报告与优化方案

> 生成日期：2026-07-29  
> 测试环境：Docker (backend-dev + frontend-dev + Redis)  
> 性能工具：pyinstrument 5.1.2 / cProfile / Lighthouse CLI 13.4.1  
> 数据采集范围：A股/港股/美股行情、组合设计、策略检查、资讯、因子模型、AI分析

---

## 目录

1. [测试配置与性能诊断工具安装](#1-测试配置与性能诊断工具安装)
2. [组合设计与策略检查诊断](#2-组合设计与策略检查诊断)
3. [行情分析全链路测试](#3-行情分析全链路测试)
4. [技术分析与综合信号评估](#4-技术分析与综合信号评估)
5. [资讯页面与智能分析评估](#5-资讯页面与智能分析评估)
6. [因子模型状态评估](#6-因子模型状态评估)
7. [前后端数据断裂排查](#7-前后端数据断裂排查)
8. [前端性能诊断 (Lighthouse)](#8-前端性能诊断-lighthouse)
9. [后端性能诊断](#9-后端性能诊断)
10. [测试防护体系失效分析](#10-测试防护体系失效分析)
11. [优化与修复方案](#11-优化与修复方案)
12. [优先级实施路线图](#12-优先级实施路线图)

---

## 1. 测试配置与性能诊断工具安装

### 1.1 Docker 集群启动

| 组件 | 镜像 | 状态 | 端口 |
|------|------|------|------|
| backend | etf_surge-backend:latest (prod) | ✅ Running | 8000 |
| frontend | etf_surge-frontend-dev:latest | ✅ Running | 5173 |
| redis | redis:7-alpine | ✅ Running | 6379 |

### 1.2 后端性能诊断工具

**已配置工具：**

| 工具 | 版本 | 用途 | 启用方式 |
|------|------|------|----------|
| pyinstrument | 5.1.2 | 异步感知采样分析器 | `PROFILE_WARMUP=1` 环境变量 |
| cProfile | built-in | CPU 调用栈分析 | `PROFILE_WARMUP=1` 自动启用 |
| WarmupProfiler | 自定义 | 预热阶段耗时跟踪 | 内嵌在 lifespan 中 |

**输出报告位置：**

| 报告 | 路径 | 大小 |
|------|------|------|
| 时序报告 | `backend/logs/warmup_timing.json` | 0.7 KB |
| pyinstrument HTML | `backend/logs/warmup_pyinstrument.html` | 404 KB |
| pyinstrument 文本 | `backend/logs/warmup_pyinstrument.txt` | 2.5 KB |
| cProfile 统计 | `backend/logs/warmup_cprofile.txt` | 144 KB |

### 1.3 前端性能诊断工具

| 工具 | 版本 | 用途 |
|------|------|------|
| Lighthouse CLI | 13.4.1 | 网站性能审计 |
| rollup-plugin-visualizer | 已配置 | 打包体积可视化 |

### 1.4 警告：Docker 构建问题

- `etf_surge-backend-dev` 镜像构建耗时超过 5 分钟（Python 依赖包下载慢）
- 最终使用 `etf_surge-backend:latest`（prod 镜像）替代
- Dockerfile 中 `pip install` 未配置国内镜像源，下载速度极慢（~180 KB/s）

---

## 2. 组合设计与策略检查诊断

### 2.1 组合设计 (POST /portfolio/design-async)

**执行参数：** capital=500000, market="A"

**检测结果：**

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 设计方案创建 | ✅ | ID=1, 34 只 ETF, 3 套方案 |
| 方案持久化 | ✅ | 写入 SQLite |
| 防御型方案 | ✅ | 10 只 ETF, 仓位 75% |
| 平衡型方案 | ✅ | 13 只 ETF, 仓位 80% |
| 进取型方案 | ✅ | 11 只 ETF, 仓位 85% |
| 任务状态 | ❌ | 卡在 `quick_ready` 80% 进度 |
| LLM 报告生成 | ❌ | 未完成（从未进入 `completed`） |
| ETF 分配数据 | ❌ | 任务结果中 etfs 字段为空字符串 |
| 市场上下文数据 | ⚠️ | index_realtime/sector_momentum/benchmark_stocks 全部为空数组 |
| 资金流数据 | ⚠️ | total_net_inflow=0.0 全部为零 |
| 中文编码 | ❌ | 终端显示中文为乱码 |

**根因分析：**

1. **LLM 报告未生成**：`quick_ready` 状态表示只完成了引擎策略分配，LLM 报告任务未执行或未完成。设计引擎生成了 ETF 分配并持久化（设计详情中有 34 只 ETF），但异步任务未更新为 completed。

2. **ETF 分配在任务结果中为空**：任务回查的 result.strategies[].etfs 字段仅为空格字符串，但 design_text 和数据库中已包含完整数据。说明任务结果序列化时未正确携带 ETF 数据。

3. **市场数据缺失**：index_realtime（实时指数）、sector_momentum（板块动量）、benchmark_stocks（基准股票）全部为空。这些数据由 pool_manager 缓存提供，但缓存中无数据或数据未成功填充。

### 2.2 策略检查 (POST /portfolio/strategy-check-async)

**执行参数：** total_capital=500000, portfolio_type="on_exchange"

**检测结果：**

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 任务完成 | ✅ | task_id=65, status=completed |
| 数据采集 | ✅ | 10/10 持仓数据填充 |
| 市态判断 | ✅ | range_bound (震荡格局) |
| 数据可信度 | ✅ | high |
| LLM 分析 | ❌ | "LLM分析暂不可用，请稍后重试" |
| 持仓分析 | ❌ | 空数组 |
| 调仓建议 | ❌ | 空数组 |
| 风险警告 | ⚠️ | 仅有通用 info 级别提示 |

**根因分析：**

LLM 分析不可用的直接原因是导入错误：
```
cannot import name 'llm_provider' from 'app.analysis.llm'
```

这在 `strategy_check_worker.py` 中出现，说明 LLM 模块的函数命名或导出发生了变化，但 strategy_check_worker 没有同步更新。

### 2.3 报告质量审阅

**防守型方案（书面）：**
- 定位："低波稳健配置，控制回撤，适合保守风险偏好者"
- 预期年化：8%，最大回撤 -12%
- 资产结构：核心 40% · 卫星 25% · 防御 10% · 现金 25%
- ETF 数量：10 只
- **评价：** 逻辑合理，防御型定位清晰。现金比例 25% 偏高，在市场震荡格局下也算合理。

**平衡型方案（书面）：**
- 定位："核心稳健+卫星增强，攻守兼备，适合中等风险偏好者"
- 预期年化：11%，最大回撤 -18%
- 资产结构：核心 40% · 卫星 30% · 防御 10% · 现金 20%
- ETF 数量：13 只
- **评价：** 节奏合理，核心/卫星分层清晰，13 只 ETF 覆盖恰当。

**进取型方案（书面）：**
- 定位："高弹性行业/主题权重大，承受较大回撤博取超额"
- 预期年化：16%，最大回撤 -35%
- 资产结构：核心 40% · 卫星 35% · 防御 10% · 现金 15%
- ETF 数量：11 只
- **评价：** 预期收益 16% vs 最大回撤 -35% 的风险收益比偏高。

**整体质量评价：**

| 维度 | 评分 | 说明 |
|------|------|------|
| 逻辑性 | ⭐⭐⭐⭐ | 三种方案的分层递进合理 |
| 可读性 | ⭐⭐⭐ | 中文报告，但终端输出有乱码 |
| 数据完整性 | ⭐⭐ | 市场上下文数据大量缺失 |
| 准确性 | ⭐⭐⭐⭐ | 因子评分和分配逻辑正确 |
| 市场匹配度 | ⭐⭐⭐ | 判断为震荡格局，方案配置基本匹配 |
| AI 报告完整性 | ❌ | LLM 报告未生成 |

---

## 3. 行情分析全链路测试

### 3.1 全球指数

| 市场 | 覆盖指数数 | 状态 |
|------|-----------|------|
| A股 | 5 (上证/深证/创业板/沪深300/科创50) | ✅ |
| 港股 | 3 (恒生/国企/科技) | ✅ |
| 美股 | 3 (标普/纳斯达克/道琼斯) | ✅ |
| 日经 | 1 | ✅ |
| 韩国 | 1 | ✅ |
| 欧洲 | 4 (FTSE/DAX/CAC/STOXX50E) | ✅ |

**总计：17 条指数数据，全部含价格。** ✅

### 3.2 搜索功能

| 测试项 | 结果 | 详情 |
|--------|------|------|
| A股搜索 "沪深300" | ✅ | 20 条结果 |
| A股搜索 "510050" | ✅ | 1 条结果 |
| 港股搜索 "盈富基金" | ❌ | 0 条结果 |
| 美股搜索 "SPY" | ❌ | 0 条结果 |
| **自动补全支持** | ⚠️ | 搜索 API 返回精确匹配，非前缀模糊匹配 |

**根因分析：** 搜索 API 的 `asset_type` 参数过滤仅对 A 股有效，港股/美股的搜索数据源可能缺失或搜索逻辑未覆盖。

### 3.3 行情数据

| 端点 | 状态 | 响应时间 |
|------|------|----------|
| GET /market/indices/global | ✅ | 0.9s |
| GET /market/realtime/portfolio | ✅ | 18 条数据 |
| GET /market/hot-plates | ✅ | 15 条 |
| GET /market/sectors/industry | ✅ | 10 条 |
| GET /market/signal/510300 | ✅ | sell（MACD死叉）|
| GET /market/indicators/510300 | ✅ | MA/RSI/KDJ/Bollinger/MACD |

### 3.4 AI 分析

| 端点 | 状态 | 说明 |
|------|------|------|
| POST /analysis/llm-report | ✅ | 4,484 字市场综合研判报告 |
| POST /analysis/llm-report/stream | ⚠️ | 流式 SSE 端点 |
| POST /analysis/llm-advice | ❌ | 422 错误，参数解析问题 |
| POST /analysis/llm-advice/stream | ⚠️ | 流式端点在代码中定义 |
| POST /analysis/symbol-analysis/stream | ✅ | 产生 token 流式输出 |
| POST /analysis/llm-news-analysis | ✅ | 5,937 字深度分析 |
| POST /analysis/news-impact | ⚠️ | 返回了空数据 |
| POST /analysis/portfolio-review | ❌ | 缺少多个必填字段 |

**LLM 报告质量评估：**

市场综合研判报告内容完整，包含：
- ✅ 核心状态描述（横盘消化格局）
- ✅ 关键指数涨跌幅数据
- ✅ 市场情绪分析（中性 50/100）
- ✅ 市态标记（range_bound）
- **评价：** 数据引用准确，判断科学合理，可读性好。

---

## 4. 技术分析与综合信号评估

### 4.1 510300（沪深300ETF）技术指标

| 指标 | 值 | 判断 |
|------|-----|------|
| MA5 | 4.705 | ↓ 低于 MA20 |
| MA10 | 4.7069 | ↓ 低于 MA20 |
| MA20 | 4.773 | 中期均线 |
| MA60 | 4.867 | 长期均线，所有短均线在其下 |
| MACD | DIF=-0.055, DEA=-0.044 | 死叉，空头趋势 |
| RSI(14) | 42.69 | 中性偏弱区间 |
| KDJ | K=44.55, D=46.73, J=40.18 | 三线下行，弱势 |
| 布林带 | 中轨 4.773 | 价格靠近下轨 |
| **综合信号** | **卖出** | MACD死叉+MA空头排列 |

### 4.2 综合信号评估

| 持仓标的 | 信号 | 评估 |
|----------|------|------|
| 510300 | Sell (-2.0) | ✅ 合理，MACD死叉+均线空头 |
| 510050 | 未获取 | - |
| 159915 | 未获取 | - |
| 159949 | 未获取 | - |
| 588000 | 未获取 | - |
| 512880 | 未获取 | - |
| 159766 | 未获取 | - |
| 512010 | 未获取 | - |
| 515050 | 未获取 | - |
| 518880 | 未获取 | - |

**注：** 仅测试了 510300，信号合理。其他标的未逐一测试，但从日志看，因 mootdx/akshare 数据源熔断，部分行情获取失败。

### 4.3 信号准确性判断

- MACD 死叉信号：✅ 正确，DIF 在 DEA 下方，且持续发散
- 均线空头排列：✅ MA5 < MA10 < MA20 < MA60，典型的下跌趋势
- RSI 42.69 在 30-50 中性偏弱区间：✅ 合理
- KDJ 三线均 < 50：✅ 弱势
- **评价：** 技术分析信号准确合理，因子计算逻辑正确。

---

## 5. 资讯页面与智能分析评估

### 5.1 资讯数据概览

| 指标 | 值 |
|------|-----|
| 总资讯数 | 30 条 |
| 数据来源 | 财联社、新浪财经 |
| 级别分布 | level 1: 9条, level 2: 10条, level 3: 3条, level 4: 4条, level 5: 4条 |
| 星级分布 | ★3: 8条, ★4: 10条, ★5: 11条, ★2: 1条 |

### 5.2 重要等级划分合理性评估

| 级别 | 定义 | 样本 | 评估 |
|------|------|------|------|
| Level 5 | 最高级 | 兆易创新回购 | ✅ 合理，重大公司行动 |
| Level 5 | 最高级 | 环孢子虫疫情 | ✅ 合理，公共卫生事件 |
| Level 4 | 高级 | 特朗普就伊朗问题评论 | ✅ 合理，地缘政治事件 |
| Level 4 | 高级 | 兆易创新减持完成 | ✅ 合理，重要内幕交易 |
| Level 2 | 一般 | ASMPT 买入评级 | ✅ 合理，券商研报 |

**评价：** 资讯分级基本合理。Level 5 覆盖重大事件（回购、疫情），Level 4 覆盖重要宏观/公司事件，Level 2-3 覆盖日常市评。但 Level 1（9 条）占比 30% 偏高，部分低级别资讯可能有冗余。

### 5.3 AI 智能分析质量

**LLM 新闻分析（5,937 字）：**
- ✅ 系统性地分析了市场情绪（中性偏悲观）
- ✅ 提供了推理过程（消费龙头业绩预警等）
- ✅ 涵盖宏观、行业、个股多个层面
- ✅ 有理有据，分析深度好

**评价：** AI 新闻分析质量高，逻辑清晰，数据支撑充分。

---

## 6. 因子模型状态评估

### 6.1 因子总览

| 分类 | 总数 | 有效 | 无数据 | 警告 | 平均IC |
|------|------|------|--------|------|--------|
| technical | 14 | 14 | 0 | 0 | 0.1072 |
| etf_specific | 10 | 5 | 5 | 0 | 0.4161 |
| china_specific | 3 | 0 | 2 | 1 | 0.0 |
| sentiment | 4 | 0 | 4 | 0 | 0.0 |
| style | 2 | 0 | 0 | 2 | 0.0 |
| **合计** | **33** | **19** | **11** | **3** | **0.1628** |

### 6.2 具体问题

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 33% 因子无数据 (11/33) | 🔴 高 | sentiment(4)、china_specific(2) 等分类完全无数据 |
| style 分类全部警告 | 🔴 高 | 2 个样式因子均处于警告状态 |
| china_specific avg_ic=0 | 🟡 中 | 中国特有因子（股息质量、政策契合度等）无 IC 数据 |
| 总体 avg_ic=0.1628 | 🟡 中 | IC 值偏低，因子预测能力有限 |
| ic_tracker 常量输入警告 | 🟡 中 | `ConstantInputWarning: An input array is constant` |

### 6.3 因子根因分层

对这 11 个 no_data 因子做数据依赖链分析后，根因分三层，修复策略各不相同：

| 层 | 数量 | 因子 | 根因 | 修复策略 |
|----|------|------|------|----------|
| **A — 数据源不可达** | ~5 | `etf.shares_change`, `sentiment.stock_divergence`, `style.size.ln_mcap`, `style.size.ln_float_mcap`, `etf.premium_discount` (部分) | 依赖 akshare → EastMoney 数据链，IPv6 不通导致数据注入失败 | P0.5 **IPv4 优先**自动恢复，无需单独改动 |
| **B — 数据源已残** | ~2 | `sentiment.north_flow`（北向资金）、两融余额相关因子 | ① 北向资金自 2024 年 8 月起被监管禁止实时披露，任何数据源都无法获取；② 两融余额 SZSE/SSE 直连 HTTP 接口已 404 | 北向：P1.2e **彻底删除**，替换为 `volume_ratio`（成交量比）；两融：P1.2d **改用 akshare**（IPv4 下已验证全部 7 个 margin 函数可用） |
| **C — 从未实现** | ~4-5 | `china.policy.five_year_plan`, `china.policy.strategic_emerging`, `china.policy.dual_circulation`, `sentiment.news_heat`, `sentiment.news_direction` | 因子在 YAML 中定义、在 registry 注册，但计算管道从未产生有效数据。政策因子需要基础财务/行业分类数据接入和评分逻辑实现；新闻因子有数据缓存但 IC tracker 通路未接上 | P1.2a-c **逐项实现** |

### 6.4 因子表现准确性评估

- **technical (14 因子)**：均在合理范围。RSI_14 IC=0.927（高），MACD IC=0.855（高），KDJ 各值 IC 0.66-0.76（良好）。✅
- **etf_specific (10 因子)**：5 个有效，return_1m IC=0.77 最高，price IC=-0.22 合理（价高者可能回调）。✅
- **问题因子**：详见 6.3 根因分层。核心结论是——不是数据源单一故障，而是**数据源故障 + 管道断裂 + 从未实现**三重问题叠加。❌

---

## 7. 前后端数据断裂排查

### 7.1 发现的断裂点

| # | 位置 | 类型 | 严重度 | 描述 |
|---|------|------|--------|------|
| 1 | 设计任务 ETF 数据 | 后端 | 🔴 | task result 中 etfs 字段为空字符串，但 DB 中有数据 |
| 2 | 策略检查 LLM 导入 | 后端 | 🔴 | `llm_provider` 导入错误 → LLM 分析不可用 |
| 3 | 中文编码 | 全栈 | 🔴 | 多处 API 响应出现中文乱码（gbk/utf-8 混用） |
| 4 | HK/US 搜索 | 后端 | 🔴 | 港股美股搜索结果为 0 |
| 5 | 市场上下文空数据 | 后端 | 🟡 | index_realtime/sector_momentum 为空 |
| 6 | 资金流数据 | 后端 | 🟡 | 全部为零 (total_net_inflow=0) |
| 7 | 连接池耗尽 | 后端 | 🟡 | money.finance.sina.com.cn 连接池满 |
| 8 | 数据源熔断 | 后端 | 🟡 | mootdx/akshare/dongfang 三个源已熔断 |
| 9 | LLM Advice 422 | 后端 | 🟡 | /llm-advice POST 端点参数解析失败 |
| 10 | Portfolio Review | 后端 | 🟡 | 缺少 7 个必填参数，前端无法简单调用 |

### 7.2 熔断根因：IPv6 连接被东方财富 CDN 拒绝

经过深入测试排查，3 个熔断数据源的根因完全不同：

| 数据源 | Docker | 宿主机 | 真实原因 |
|--------|--------|--------|----------|
| **mootdx（通达信）** | ❌ 1.4ms 快速失败 | ✅ **126ms 秒回** | **Docker 网络隔离**——通达信 TCP 端口在容器内不可达，宿主机正常 |
| **akshare（东方财富 A 股）** | ❌ 熔断 | ❌ RemoteDisconnected | **IPv6 连接被东方财富 CDN 拒绝**——DNS 解析到 `240e:e1:...` IPv6 地址，但 CDN 侧 IPv6 路由中断 |
| **dongfang（东方财富港股）** | ❌ 5.2s 超时 | ❌ 空列表 | **同一原因**——`push2.eastmoney.com` IPv6 不通 |

**关键证据：**

```
强制 IPv4 → ✅ 成功: 510300 price=4.657, change=0.65%
默认 IPv6 → ❌ RemoteDisconnected (DNS 解析到 240e:e1:... IPv6 地址)
所有 User-Agent 变种 → ❌ 全部失败
Sina 备选源 → ✅ 0.15s 秒回
```

**结论：** 东方财富的 CDN 配置存在 IPv6 路由问题。akshare 通过 `requests` 库发起请求，`requests` 默认优先尝试 IPv6（Python 的 DNS 解析器行为），连接在 TLS 握手阶段被服务器端重置，导致 `RemoteDisconnected` 异常。**不是 akshare 版本问题，不是请求头问题，是底层 IP 协议栈选择问题。**

mootdx 在 Docker 内的失败是独立的网络隔离问题，不是数据源本身不可用。这解释了为何旧的 `verify_e2e.py` 中，行情数据（靠 Sina/Tencent fallback）通过检查，但数据源探针持续报错。

**关联历史变更：** 之前因为 `push2.eastmoney.com` 不通，系统临时将 `etf_scanner.py` 中的域名改为 `push2delay.eastmoney.com`（见 commit `981ef74`）。但实际上两个域名都存在 IPv6 路由问题（DNS 均返回 AAAA 记录），`push2delay` 能通可能是因为当时特定 CDN 节点恰好正常或测试条件不同。**修复 IPv4 优先策略后，`push2` 即可恢复可达，届时应回退域名并升级为 HTTPS。**

### 7.3 连接池耗尽

```
"Connection pool is full, discarding connection: money.finance.sina.com.cn"
```

`_shared_session` 使用了默认连接池配置，在并发请求场景下被耗尽。所有 Sina/QQ HTTP 请求共享同一个 session，`urllib3` 默认的连接池大小为 10，超过后丢弃连接而不会等待。

### 7.4 数据源健康状态

目前 8 个注册源的状态：
```
mootdx     → OPEN (7次连续失败, 冷却中)
akshare    → OPEN (6次连续失败, 冷却中)
dongfang   → OPEN (2次连续失败, 冷却中)
sina       → CLOSED (正常)
tencent    → CLOSED (正常)
levistock  → CLOSED (正常)
china_market→ CLOSED (正常)
factor.history→ CLOSED (正常)
```

3/13 数据源已熔断，占比 23%。虽然 fallback 链仍在工作（sina/tencent 正常），但市场趋势计算（行业动量、概念动量）已受严重影响。

### 7.5 编码问题详情

在多个 API 端点中发现中文 ETF 名称显示为乱码：
- `??300ETF????`（应为 沪深300ETF华泰柏瑞）
- `??50ETF`（应为 上证50ETF）
- `???ETF???`（应为 创业板ETF易方达）

**根因：** 数据库或数据传输链路中存在 GBK/UTF-8 编码混用，中文字符在 GBK 环境中被存储或传输后，在前端以 UTF-8 读取时出现乱码。

---

## 8. 前端性能诊断 (Lighthouse)

### 8.1 核心评分

| 类别 | 评分 | 评价 |
|------|------|------|
| Performance | **50** | 🔴 低 |
| Accessibility | **96** | ✅ 优秀 |
| Best Practices | **92** | ✅ 良好 |
| SEO | **91** | ✅ 良好 |
| agentic-browsing | **67** | ⚠️ 一般 |

### 8.2 关键指标

| 指标 | 值 | 目标 | 评价 |
|------|-----|------|------|
| FCP | **4.4s** | <1.8s | 🔴 慢 |
| LCP | **25.9s** | <2.5s | 🔴 严重 |
| TBT | **410ms** | <200ms | 🟡 一般 |
| CLS | **0.001** | <0.1 | ✅ 良好 |
| SI | **6.9s** | <3.4s | 🔴 慢 |
| TTI | **25.9s** | - | 🔴 严重 |

### 8.3 总字节

| 项目 | 值 |
|------|-----|
| 总大小 | **4,300 KiB** |
| 未压缩 JS | 可节省 1,498 KiB |
| 未使用 JS | 可节省 1,843 KiB |
| CSS 使用率 | ✅ 良好 |

### 8.4 诊断发现

**核心问题：**

1. **代码拆分不充分（最大问题）**：LCP 和 TTI 高达 25.9s，因为 Vite Dev Server 模式下所有 JS 都未被压缩和拆分。这是开发模式的特性，但仍暴露了生产包体积问题。

2. **未压缩 JavaScript**：可节省 1,498 KiB（35% 体积缩减），需要在构建中启用更好的压缩。

3. **未使用 JavaScript**：可节省 1,843 KiB（43% 体积），核心框架（Vue/ECharts/Axios）代码可能按需加载不足。

4. **ECharts 体积过大**：`vendor-echarts` chunk 合计约 1.2 MB，是最大的性能拖累项。

5. **无代码分割优化**：manualChunks 配置了 Vue/ECharts/Axios 分包，但未启用动态 import。

---

## 9. 后端性能诊断

### 9.1 预热性能 (Warmup)

**时序摘要：**

| 阶段 | 耗时 (ms) | 占比 |
|------|-----------|------|
| init_db | 786.4 | 34% |
| redis_init | 88.0 | 4% |
| warmup_etf_cache | 53.0 | 2% |
| warmup_market_cache | 150.4 | 7% |
| warmup_global_indices | 1,236.2 | 53% |
| **总耗时** | **2,313.9** | **100%** |

**结论：** 预热总耗时 2.3s，远低于 15s 警告线和 30s 失败线。性能良好。

### 9.2 Pyinstrument 分析

**关键调用链耗时排名：**

1. `lifespan` 核心（1.03s）：
   - `_foreign` (market_service.get_global_indices): 299ms（网络 I/O）
   - `_warmup_global_indices`: 194ms
   - `_warmup_market_cache`: 51ms
   - `lifespan` setup overhead: 276ms

2. `RedisCache.init`: 85ms（连接建立）
3. `init_db`: 36ms（SQLAlchemy 初始化）

**瓶颈分析：**

| 瓶颈 | 位置 | 影响 | 建议 |
|------|------|------|------|
| 全局指数网络 I/O | market_service | 1.2s | 缓存策略已部分实现，可以考虑进一步预加载 |
| 模块导入耗时 | lifespan | 276ms | 已在 main.py 中预导入，仍有优化空间 |
| Database ORM 初始化 | SQLAlchemy | 786ms | SQLAlchemy 异步引擎启动是已知开销 |

### 9.3 运行时性能问题

**关键性能问题：**

| # | 问题 | 严重度 | 证据 |
|---|------|--------|------|
| 1 | HTTP 连接池耗尽 | 🟡 | "Connection pool is full, discarding connection: money.finance.sin a.com.cn" 重复出现 |
| 2 | mootdx 实时行情频繁失败 | 🟡 | `_mootdx_realtime exception for [...]` 所有 ETF 均失败 |
| 3 | 行业/概念动量计算失败 | 🟡 | `_compute_industry_momentum` / `_compute_concept_momentum` 连接被重置 |
| 4 | SZSE/SSE 保证金接口 404 | 🟡 | 深圳交易所和上海交易所接口均返回 404 |
| 5 | LLM 报告 90s 超时 | 🟡 | 潜在问题，design_report.py 中有 90s 超时保护 |
| 6 | 线程池未配置大小 | 🟡 | `run_sync` 使用默认线程池，可能在高负载下成为瓶颈 |

---

## 10. 测试防护体系失效分析

### 10.1 现有测试防护体系

| 测试类型 | 文件 | 覆盖范围 | 执行时机 |
|----------|------|----------|----------|
| 后端单测 | `tests/test_design_optimization_plan.py` | 7 个用例 | pytest |
| 前端单测 | `npm test` (vitest) | 组件测试 | pre-commit |
| E2E 链路验证 | `scripts/verify_e2e.py` | 健康/行情/设计/新闻/WS | 改代码后运行 |
| 前端构建验证 | `npm run build` | Vue 编译 | pre-commit |
| Lighthouse CI | `.lighthouserc.js` | 性能门禁 | CI |

### 10.2 为何问题未被捕获

| 发现的问题 | 为何测试未发现 | 根本原因 |
|------------|----------------|----------|
| LLM 导入错误 (`llm_provider`) | 单测 mock 了 LLM，不测试实际导入 | 单测使用 mock，不覆盖真实导入链路 |
| 任务卡在 quick_ready | verify_e2e 不检查任务最终状态 | E2E 只检查设计方案是否存在，不检查 LLM 报告是否完成 |
| ETF 分配数据为空 | 不检查 task result 中的 etfs 字段 | E2E 验证是通过 DB 直接查询设计，非通过 task API |
| 市场上下文空数据 | 不验证 market_context 的完整性 | E2E 未对 market_snapshot_json 字段做深度校验 |
| HK/US 搜索为 0 | 只测试 A 股搜索 | E2E 的搜索测试仅用 A 股 symbol |
| 因子 33% 无数据 | 不对因子 IC 数据质量做断言 | 无因子模型数据健康检查 |
| 数据源熔断 | 不检查 source health | E2E 不包含数据源健康验证 |
| 连接池耗尽 | 单次请求不触发 | 需要高并发才暴露，单次单线程测试不触发 |
| 中文编码问题 | 测试不验证编码 | E2E 只检查响应状态码和数据存在性 |
| 前端性能 50 分 | Lighthouse CI 配置了 warn 而非 error | 门禁是 warn (50分)，CI 不阻塞 |

### 10.3 防护缺口总结

| 缺口维度 | 严重度 | 说明 |
|----------|--------|------|
| LLM 链路真实性测试 | 🔴 | 所有 LLM 相关测试都使用了 mock |
| 任务状态完整性验证 | 🔴 | 不检查任务是否走到 completed |
| 数据源健康监控 | 🔴 | 无自动化测试验证数据源可用性 |
| 市场数据完整性 | 🟡 | 不对 market_context 做深度校验 |
| 跨市场搜索 | 🟡 | 不测试 HK/US 搜索 |
| 编码验证 | 🟡 | 不检查中文字符是否正确编码 |
| 并发/连接池测试 | 🟡 | 无压力测试 |
| 因子数据质量门禁 | 🟡 | 不对 IC 值做断言 |
| 性能门禁过于宽松 | 🟡 | Lighthouse 是 warn 非 error |
| mypy 147 个 error 形同虚设 | 🔴 | pre-commit 门禁应阻止但有办法绕过（SKIP_MYPY=1），且现有 147 个已存 error 导致噪声淹没新 error |

---

## 11. 优化与修复方案

### 11.1 P0 — 关键路径修复（必须修复，否则系统不可用）

| # | 修复项 | 涉及文件 | 方案 |
|---|--------|----------|------|
| P0.1 | 修复 LLM 导入错误 | `strategy_check_worker.py` | 将 `from app.analysis.llm import llm_provider` 改为从 `app.config` 或 `app.core.llm` 导入 |
| P0.2 | 修复 LLM 报告未生成问题 | `design_report.py` / `task_manager.py` | 检查 design_worker 是否调用了 report pipeline，确保 quick_ready 后能正确 transition 到 completed |
| P0.3 | 修复港股美股搜索为 0 | `backend/app/routers/market.py` / `backend/app/services/market_service.py` | 搜索 API 增加 HK/US 数据源查询（新浪财经/东方财富国际版） |
| P0.4 | 修复中文编码问题 | `backend/app/config.py` / DB 连接 | 统一使用 UTF-8 编码，检查数据库编码设置和 HTTP 响应的 Content-Type charset |
| **P0.5** | **全局 IPv4 优先策略** | `backend/app/config.py` | 在 `config.py` 模块顶层注入 IPv4 优先的 socket 解析器（单行补丁）：`socket.getaddrinfo = lambda h,p,f=0,t=0,pro=0,fl=0: __import__('socket').getaddrinfo(h,p,socket.AF_INET,t,pro,fl)`。位置在 `DEEPSEEK_API_KEY` 等配置常量之后、任何网络调用之前。所有通过 `requests`/`urllib` 发出的 HTTP 请求走 IPv4，绕过东方财富 CDN 的 IPv6 路由问题。**注意：** 这种 monkey-patch 影响全局 socket 解析，需确认项目中没有任何依赖 IPv6 的功能（当前系统无）。回退方案：封装为 `enable_ipv4_only()` / `disable_ipv4_only()` 函数，在 lifespan 中控制生命周期 |
| P0.6 | 修复 LLM Advice 422 错误 | `backend/app/routers/analysis.py` | 解决 `Query(...)` 参数与 POST body 的冲突，确保前端以标准 POST JSON body 即可调用 |

### 11.2 P1 — 数据质量提升

| # | 修复项 | 方案 |
|---|--------|------|
| P1.1 | 修复市场上下文空数据 | 检查 pool_manager 的数据采集和缓存刷新链路，确保 index_realtime / sector_momentum 被正确填充 |
| P1.2a | 新闻因子数据通路修复 | `factor_registry.py` / `pool_manager.py` | 让 `sentiment.news_heat` 和 `sentiment.news_direction` 收到来自新闻缓存的 news_items 数据。IC tracker 数据通路有断裂，需追查 pool_manager → factor pipeline 之间 news_items 注入逻辑 |
| P1.2b | premium_discount / tracking_error 因子修复 | `factor_registry.py` / `fetchers` | 检查 Sina IOPV 数据是否确实注入到了因子计算管道。如果 IOPV 数据已存在但因子计算未收到，需修正数据传递链 |
| P1.2c | 实现政策因子评分逻辑 | 新建 `factors/policy_factors.py` | `china.policy.five_year_plan` / `strategic_emerging` / `dual_circulation` 需要：① 接入基础行业分类数据（新浪/申万）；② 实现主题映射和评分算法。依赖 P0.5 先让数据源恢复 |
| P1.2d | 两融余额换源：改用 akshare | `fundamentals_fetcher.py` | 当前 SZSE/SSE 直连 HTTP 接口已 404。改用 akshare 的 `stock_margin_szse()` + `stock_margin_sse()`（IPv4 下已验证全部可用），通过 `run_in_thread` 包装。两函数分别返回 SZSE 和 SSE 的融资余额(rzye)，合计即为全市场两融余额。移除直连 HTTP 的 `_fetch_szse` / `_fetch_sse` |
| P1.2e | 删除北向资金因子 + 替换为成交量比 | `factor_definitions.yaml` / `fundamentals_fetcher.py` / `factor_registry.py` | ① 从 YAML 和 registry 中删除 `sentiment.north_flow` 因子定义和计算函数；② 从 `calc_sentiment_index()` 中移除 north_flow 参数；③ 新增 `volume_ratio` 因子（实时成交量 / 20日均量），数据从 Sina/Tencent 实时行情获取，零额外成本；④ 调整情绪指数为 **四维权重**：advance_ratio=0.30（市场宽度）、margin_change=0.30（杠杆情绪）、volume_ratio=0.20（市场人气）、inst_consensus=0.20（机构共识） |
| P1.3 | mootdx Docker 网络隔离修复 | `docker-compose.yml` (dev profile) | dev profile 的 `backend-dev` 加 `network_mode: "host"`；将 `REDIS_URL` 从 `redis://redis:6379/0` 改为 `redis://localhost:6379/0`；曝光 redis `ports: ["6379:6379"]`。生产 profile 不变，mootdx 不可用时自动 fallback 到 Sina/Tencent |
| P1.4 | 数据源探针准确性修复 | `monitor/probes.py` | mootdx 探针在 Docker 内应自动跳过或使用备选检测；akshare 探针应改为检测系统实际使用的 akshare 函数（资讯/板块），而非 `stock_zh_a_hist` |
| P1.5 | HTTP 连接池扩容 | `backend/app/fetchers/_shared_session.py` 或所在文件 | 增加 `urllib3` 连接池大小到 20-30，或禁用默认连接池限制。设置 `pool_connections=30, pool_maxsize=60` |
| P1.6 | **消除 mypy 147 个类型错误** | 见下方详细分解 |
| P1.7 | `push2delay` 回退到 `push2` | `etf_scanner.py` | 等 P0.5（IPv4 优先）上线并验证通过后，将 `push2delay.eastmoney.com` 改回 `push2.eastmoney.com`，协议从 HTTP 升级为 HTTPS。回退前提：P0.5 已部署且 `push2` 在宿主机和 Docker 内均验证可达 |

#### P1.6 专项：mypy 147 个类型错误消零计划

**影响范围：** 23 个文件 / 147 个 error / 65 个 note。

**按类别治理：**

| 类别 | 大约数量 | 错误特征 | 治理方案 |
|------|---------|----------|----------|
| A — SQLAlchemy Column 类型误用 | ~45 | `Column[str]` 赋值给 `str` / `Column[int]` 赋值给 `int` | 增加 `sqlalchemy.ext.mypy.plugin` 插件；或在赋值处用 `await` 或 `sync_session()` 获取实际 Python 值 |
| B — 未标注类型 | ~25 | `Need type annotation for "xxx"` | 添加显式类型标注，如 `results: list[dict] = []` |
| C — None 安全/Union | ~15 | `Item "None" of "Optional[X]" has no attribute "Y"` | 增加 `assert x is not None` 保护，或 `if x is not None:` 分支配 |
| D — list.sort 返回值类型 | ~10 | `key=lambda x: x.get('field')` 返回值不兼容 | 明确 key 函数返回 `float` 或 `str` 而非 `object` |
| E — bytes 索引 dict | ~5 | `Invalid index type "bytes" for "dict[str, str]"` | 在 decode 前 decode() 或显式转型 |
| F — 名称未定义 | ~3 | `Name "pd" is not defined` | 补全 import |
| G — mypy.ini 配置错误 | ~5 | 通配符 `[mypy-apply_*.py]` 不符合规范 | 改为完整模块路径或合法通配符 |

**涉及的关键文件：**
- `task_manager.py`(10+ Column 赋值), `cache_service.py`(6 None 安全+类型标注)
- `portfolio_service.py`(10+ Column 赋值), `design_report.py`(3 Column+None)
- `market_trends.py`(4 sort key), `signal.py`(7 标注+float), `decode.py`(3 bytes索引)

**验收标准：** `cd backend && python -m mypy` 输出 0 error。pre-commit 中移除 `SKIP_MYPY` 逃生舱，mypy 门禁不可跳过。

---

### 11.3 P2 — 前端性能优化

| # | 修复项 | 方案 | 预期收益 |
|---|--------|------|----------|
| P2.1 | 代码分包优化 | ECharts 按需引入组件（`echarts/core` + 按需组件），而不是全量导入 | 节省 ~800 KiB |
| P2.2 | 懒加载路由页面 | Vue Router 动态 import：`() => import('./views/MarketAnalysis.vue')` | 减少首屏 JS 60% |
| P2.3 | Tree-shaking 优化 | 配置 `rollupOptions.treeshake` 选项 | 节省 ~200 KiB |
| P2.4 | 启用 gzip/brotli | nginx 配置 `gzip on; gzip_types application/javascript` | 传输压缩 70% |
| P2.5 | PWA 缓存策略优化 | 将 API 缓存改为 NetworkFirst + 较长的缓存时间 | 减少重复 API 调用 |

### 11.4 P3 — 测试防护增强

| # | 修复项 | 方案 |
|---|--------|------|
| P3.1 | 增加 LLM 真实链路测试 | E2E 中增加一个最小 LLM 调用测试（非 mock），只验证 import 是否正常 |
| P3.2 | 任务状态完整性断言 | verify_e2e.py 增加对设计任务 completed 状态的检查 |
| P3.3 | 跨市场搜索 E2E | 增加港股（盈富基金）和美股（SPY/QQQ）搜索测试 |
| P3.4 | 数据源健康检查 | verify_e2e.py 增加 `/admin/sources/health` 健康检查 |
| P3.5 | 编码验证 | 在 E2E 测试中验证中文名称响应是否包含乱码 |
| P3.6 | Lighthouse 门禁收紧 | 将 Performance warn score 从 50 提升到 60，LCP 门禁从 8s 收紧到 4s |
| P3.7 | 因子数据质量检查 | 增加对 factor IC 可用因子的数量和质量断言 |

### 11.5 P4 — 架构优化

| # | 修复项 | 方案 |
|---|--------|------|
| P4.1 | 统一 LLM 提供商管理 | 重构 `app/analysis/llm.py`，用策略模式管理多个 LLM 提供商，替代 `llm_provider` 函数级变量 |
| P4.2 | 数据源连接池配置化 | 将 `urllib3` 连接池、超时、重试策略统一到 `config.py` |
| P4.3 | 预热缓存持久化 | 将 index_realtime/sector_momentum 缓存持久化到 Redis（而非内存），重启后不丢失 |
| P4.4 | 异步任务超时监控 | 为所有异步任务增加寿命监测，超时自动标记 failed 并发送告警 |

---

## 12. 优先级实施路线图

```
Phase 1 — 一击必杀 (1小时, 系统恢复运行基础)
├── P0.5 全局 IPv4 优先策略 ← 前置条件, 恢复 akshare/dongfang 数据源
├── P0.1 修复 LLM 导入错误 (strategy_check_worker)
├── P0.6 修复 LLM Advice 422 错误 (analysis.py)
├── P0.2 修复 LLM 报告未生成 (design_report→task_manager)
├── P1.3 mootdx Docker 网络隔离修复 (dev profile network_mode: host)
├── P1.7 push2delay → push2 域名回退 (P0.5 验证通过后执行)
└── P1.4 数据源探针准确性修复 (probes.py 改用系统实际使用的函数)

  验证: verify_e2e.py 全 PASS; /admin/sources/health 确认 akshare/dongfang 恢复 CLOSED

Phase 2a — 因子与数据质量 (1-2天)
├── P1.2d 两融余额换源 (fundamentals_fetcher→akshare, IPv4下已验证)
├── P1.2e 删除 north_flow + 新增 volume_ratio 因子 (新四维权重已定义)
├── P1.1 修复市场上下文空数据 (pool_manager 数据刷新链路)
├── P1.2a 新闻因子数据通路修复 (sentiment.news_heat/direction)
├── P1.2b premium_discount 因子修复 (IOPV数据链)
├── P0.3 修复港股美股搜索为 0
├── P0.4 修复中文编码问题 (统一 UTF-8)
├── P1.5 HTTP 连接池扩容 (urllib3 pool_connections=30, pool_maxsize=60)

  验证: 因子 IC 页 ≥19 有效因子; 港股/美股搜索有结果; 中文无乱码

Phase 2b — 高级因子与类型安全 (3-5天)
├── P1.2c 实现政策因子评分逻辑 (3个 china.policy 因子)
├── P1.6 mypy 类型错误消零 (A类+ C类优先, ~60 个)
└── 补充新增因子的测试覆盖

Phase 3 — 前端性能优化 (3-5天)
├── P2.1 ECharts 按需导入 (echarts/core + 按需组件)
├── P2.2 Vue Router 动态 import 懒加载页面
├── P2.3 rollup Treeshaking 优化
└── P2.4 nginx gzip/brotli 压缩

Phase 4 — 测试防护增强 (持续)
├── P3.1-P3.7 增强测试覆盖 (LLM 真实链路/任务状态/跨市场搜索/编码验证/因子质量/数据源健康)
├── P1.6 mypy 剩余错误消零 (B类+D类+E类+F类+G类, ~70 个)
├── 修复 mypy.ini 配置错误 (G类, 通配符改用合法模块路径)
├── pre-commit 移除 SKIP_MYPY 逃生舱, mypy 门禁不可跳过
├── 收紧 Lighthouse 门禁 (Performance warn 50→60, LCP 8s→4s)
└── CI 增加数据源健康检查和因子质量断言

Phase 5 — 架构优化 (远期)
├── P4.1 统一 LLM 提供商管理 (策略模式替代函数级变量)
├── P4.2 连接池配置化 (config.py 统一管理超时/大小/重试策略)
├── P4.3 预热缓存持久化到 Redis (重启不丢失)
└── P4.4 异步任务超时监控 (自动标记 failed + 告警)
```

---

## 附录 A：测试数据快照

### A.1 热身性能时序
```json
{
  "total_duration_ms": 2313.9,
  "records": [
    {"label": "init_db", "duration_ms": 786.41, "category": "db"},
    {"label": "redis_init", "duration_ms": 87.98, "category": "cache"},
    {"label": "warmup_etf_cache", "duration_ms": 52.99, "category": "warmup"},
    {"label": "warmup_market_cache", "duration_ms": 150.38, "category": "warmup"},
    {"label": "warmup_global_indices", "duration_ms": 1236.16, "category": "warmup"}
  ]
}
```

### A.2 Lighthouse 原始评分
```
Performance:      50
Accessibility:   96
Best Practices:  92
SEO:             91
agentic-browsing: 67
```

### A.3 E2E 测试结果
```
Smoke 模式: 24/24 全部 PASS
```

### A.4 数据源健康
```
可用: 10/13 (77%)
熔断: mootdx, akshare, dongfang
```

### A.5 IPv4 验证测试
```
强制 IPv4 push2.eastmoney.com → ✅ HTTP 200, 3 items, 实时数据精准
默认 IPv6 push2.eastmoney.com → ❌ RemoteDisconnected (<200ms)
Sina (参考组)                → ✅ 0.15s 秒回
```

---

## 附录 B：变更文件清单

本诊断过程中新增的文件：

| 文件 | 说明 |
|------|------|
| `backend/logs/warmup_timing.json` | 热身性能时序报告 |
| `backend/logs/warmup_pyinstrument.html` | Pyinstrument 火焰图报告 |
| `backend/logs/warmup_pyinstrument.txt` | Pyinstrument 文本报告 |
| `backend/logs/warmup_cprofile.txt` | cProfile 调用栈报告 |
| `localhost_2026-07-29_20-22-30.report.json` | Lighthouse 原始报告 |
| `localhost_2026-07-29_20-22-30.report.html` | Lighthouse HTML 报告 |
| `_parse_lighthouse.py` | Lighthouse 结果解析脚本 |
| `docs/comprehensive-diagnosis-report.md` | 本诊断报告 |
| `backend/_test_host_sources.py` | 数据源宿主机可达性测试 |
| `backend/_test_em_url.py` | 东方财富 API 路径 / IPv4 vs IPv6 对比测试 |
| `backend/_test_akshare.py` | akshare 升级后功能回归测试 |
| `backend/_test_push2.py` | push2.eastmoney.com 多策略测试 |
| `backend/_test_eastmoney_api.py` | 东方财富全线域名/端口/API 路径测试 |

---

*文档版本：v1.1 | 评审状态：待多轮 Review*
