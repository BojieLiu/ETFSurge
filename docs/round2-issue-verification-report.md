# ETF Surge — round2 问题清单修复验证报告 (v1.0)

> 生成时间: 2026-08-01
> 验证环境: Docker prod 态（etf_surge-backend-1 / frontend-1 / redis-1），与 round2 诊断同环境
> 验证对象: `docs/round2-system-diagnosis-and-optimization-plan.md`（v1.12）全部问题清单
> 验证方式: 容器内 API 实测 + 直调数据源绕过熔断 + 代码审计 + 单测回归
> 状态: **验证完成；结论与 round2 声明存在多处不一致，详见各节**

---

## 〇、验证摘要

round2 文档（v1.12）的问题清单状态与本次容器实测对照。**重要前提**：round2 是"诊断与优化方案"文档——Z 表（§七）有实测状态标记，F 系列/T 系列（§九）是**修复方案**（仅 F0-1/F0-2 标记 ✅ 已实施），不代表已落地。本次验证回答"方案对应的问题现在修好了吗"：

| 类别 | round2 状态 | 本次实测 | 差异 |
|------|-----------|---------|------|
| §七 Z01-Z15（15 项） | 12/15 已修或部分修 | **9/15 保持**，Z06 回归、Z04 恶化、Z11 未达标、Z05 回退 | ⚠️ 4 项恶化 |
| §九 F0-F3（30 项方案） | 方案（仅 F0-1/2 已实施） | **18 ✅ / 6 ⚠️ / 6 ❌**（多由后续迭代落地） | ⚠️ 部分 |
| 三个专项（Z04/候选池/合理性） | 方案 | 候选池 ✅、Z04 ❌、合理性部分 | ⚠️ |
| T1-T14 防护补强 | 方案 | **2/14 完整落地**（T5/T9），T4/T7/T12 部分 | ❌ |

### 核心结论

1. **round2 文档是"方案文档"而非"实施记录"**——F 系列/T 系列大多停留在方案，本次验证显示约 60% 已实施（多由后续迭代落地），约 40% 未实施或部分实施。
2. **Z06 回归 / Z04 恶化**：round2 实测"IC 23 条非空"（Z06 标 ✅ 已修），本次实测 **IC 0 条**——根因是 IC 计算对常量输入返回 0 后全批次被过滤（`ic_tracker.py:84 ConstantInputWarning`），且 `_last_ic_batch` 无条件覆盖，属**时序性假阳性**（当时数据源恰好有变化数据，容器重启后失效）。Z04（etf_specific）round2 已标"❌ 未达标"（4 no_data），本次 **恶化到 10 全 no_data**——其修复方案（§9.5）未实施。
3. **N01（策略检查报告空）的修复方案 F1-9 未实施**：实测 `report_text len=0`、`covered_by_llm=0`。round2 中 F1-9 是方案（非已修），其设计（CancelledError 捕获 + usage 留痕 + fallback）部分落地，但**兜底正文生成未实施**。
4. **F1-1（港股行情）修复方案未解决根因**：实测仍 null。`get_asset_realtime` 对 HK 标的**先走 A 股查询路径**，A 股路径对非 A 股代码的失败被计入熔断（sina/tencent/dongfang open），后续 HK 降级链全部被熔断器跳过——round2 方案中的前缀归一化未覆盖此根因。
5. **T1-T14 防护补强落地率极低**：14 项中仅 T5/T9 完整落地、T4/T7 部分，其余 10 项停留在文档——这是 round3 诊断发现"防护体系 6 类盲区"的直接原因。

---

## 一、§七 Z01-Z15 逐项验证

| ID | 问题 | round2 状态 | 本次实测 | 结论 |
|----|------|-----------|---------|------|
| Z01 | factor-health 500 | ✅ 已修 | HTTP 200 + ok | ✅ 保持 |
| Z02 | 美股行情 null | ✅ 已修 | SPY 747.03 有值 | ✅ 保持 |
| Z03 | china_specific no_data | ✅ 已修 | 3 因子全 static | ✅ 保持 |
| Z04 | etf_specific 10 因子无数据 | ❌ 4 no_data（未达标） | **10 全 no_data** | ❌ **恶化**（修复方案 §9.5 未实施） |
| Z05 | SSL 预热握手重复 | ✅ 改善 1.77s | 预热 6.6s，fetch_fund_nav 10 次 8.2s | ⚠️ **回退**（详见 N08） |
| Z06 | 因子 IC 全空 | ✅ 已修（23 条） | **IC 0 条**（e2e 直接 FAIL） | ❌ **回归** |
| Z07 | LLM 42.4% 错误率 | ⚠️ 23.2% | 25.2%（opencode_zen 429 持续） | ⚠️ 未达标 |
| Z08 | sources/health 空 | ✅ 已修 | 7 源非空 | ✅ 保持 |
| Z09 | sigma 值异常 | ✅ 已修 | factor-health 全 healthy | ✅ 保持（但 e2e zscore 检查为假 PASS，见 §五） |
| Z10 | 信号引擎保守 | ✅ 改善 | 513010 buy +2.0 | ✅ 保持 |
| Z11 | 非交易时段设计失败 | ⚠️ 现金 22-32% | 现金 19-24%（验收 ≤15%） | ❌ **未达标** |
| Z12 | 缺少 profiling | ✅ 已修 | PROFILE_WARMUP 报告齐 | ✅ 保持 |
| Z13 | 中文搜索 URL 编码 | ✅ 非 bug | 后端正常 | ✅ 保持 |
| Z14 | pre-commit 仅前端 | ✅ 已修 | 含 pytest+uvicorn 门禁 | ✅ 保持 |
| Z15 | verify_e2e 覆盖不足 | ✅ 部分 | 有 HK/US 搜索等，但 HK realtime 仍缺 | ⚠️ 部分 |

**结论：9/15 保持修复，Z06 回归为失败，Z04 恶化，Z05 回退（预热仍慢），Z11 未达标（Z07/Z15 部分）。**

说明：Z 表共 15 项 = 9 保持 ✅（Z01/Z02/Z03/Z08/Z09/Z10/Z12/Z13/Z14）+ 1 回归 ❌（Z06）+ 1 恶化 ❌（Z04）+ 1 回退 ⚠️（Z05）+ 1 未达标 ❌（Z11）+ 2 部分 ⚠️（Z07/Z15）。

---

## 二、§九 F0-F3 修复清单验证

### 🅿️0 阻断性（F0-1 ~ F0-5）

| ID | 问题 | 验收 | 实测 | 结论 |
|----|------|------|------|------|
| F0-1 | prod 容器空库 | instruments 搜索有数据 + 持仓非空 | 510300 命中 + 10 持仓 | ✅ 已修 |
| F0-2 | Settings extra_forbidden | 任意环境变量不崩溃 | 容器正常启动 | ✅ 已修 |
| F0-3 | WS 生产断裂 | nginx 80 端口 WS 握手 101 | `HTTP/1.1 101 Switching Protocols` | ✅ 已修 |
| F0-4 | A 股 K 线单源依赖 | 熔断时 history 有 stale 数据 | get_history 三级降级 + stale 兜底（market_service.py:1177-1192） | ✅ 已修 |
| F0-5 | 候选池=涨幅 Top25 | 方案 core 含主流宽基 | **三套方案 core 均含 510300/510500/588000**；etf_scanner 已改 fid=f6 | ✅ 已修 |

### 🅿️1 高优先级（F1-1 ~ F1-9）

| ID | 问题 | 验收 | 实测 | 结论 |
|----|------|------|------|------|
| F1-1 | 港股实时行情 null | 00700 返回价格 | **API 层 None**（容器内直调 tencent 正常 475.2） | ❌ **未修复** |
| F1-2 | A 股 realtime 间歇 null | 连续 10 次无 null | 510300 连续 10 次全有值 | ✅ 已修 |
| F1-3 | LLM 上下文缺失 | 回答引用真实行情 | market_data 第 5 步仍 get_all_realtime() 未过滤 | ⚠️ 部分 |
| F1-4 | llm-report market 失效 | HK 报告含恒生 | index 按 market 过滤已实施（llm_context.py:53-68），但 market_data 仍泄漏 A 股 | ⚠️ 部分 |
| F1-5 | 设计因子数据不一致 | RSI 与 indicators 一致 | rationale 用 factor_scores 键取值；运行时因子无数据时一致性无法验证 | ⚠️ 待观察 |
| F1-6 | 板块成分股错位 | 半导体返回半导体股 | BK1036 返回芯原股份/芯朋微/乐鑫科技等 | ✅ 已修 |
| F1-7 | LLM 输出未后处理 | 无泄漏 | `_strip_llm_leak` 过滤已实施（llm.py:49-88） | ✅ 已修 |
| F1-8 | 组合设计投资合理性 | core 重叠 ≤1、**防御型**科创卫星 ≤10% | core 含宽基 ✅；防御型 8% ≤10% ✅；但**平衡∩进攻 core 重叠 2 只 > 1**（验收未满）；平衡 15%/进攻 17.5% 科创卫星超限（round2 未对这两型设限，作合理性残留） | ⚠️ 部分 |
| F1-9 | 策略检查"LLM 超时"假象 | usage 留痕 + fallback | CancelledError 捕获部分落地（llm.py:1176-1193）；但 **report_text 仍为空**（实测 len=0）——方案设计未含兜底正文生成 | ❌ **未完整实施** |

### 🅿️2 中优先级（F2-1 ~ F2-9）

| ID | 问题 | 验收 | 实测 | 结论 |
|----|------|------|------|------|
| F2-1 | 组合计算 8.2s | calculate < 2s | **仍 8.2s** | ❌ **未修复** |
| F2-2 | 首页 Lighthouse 60 | Performance ≥85、CLS<0.1 | 骨架屏已加；round3 实测 CLS 0.538 仍超标 | ⚠️ 部分 |
| F2-3 | /sectors/heat 404 | 无 404 | 404 已修（200 返回 dict{items:20}）；但**结构 dict vs 前端 array 契约未修**（round3 N05） | ⚠️ 部分 |
| F2-4 | sectorAnalysis/marketAnalysis 未定义 | 流式内容 | UnifiedAnalysis 已用 SSE 流式端点，删 fallback | ✅ 已修 |
| F2-5 | 预热指数/新闻串行 | 预热 <1.0s | warmup_global_indices **1ms**（gather 并行） | ✅ 已修（总预热仍 6.6s，受 F2-5 范围外瓶颈） |
| F2-6 | 热点字段契约不匹配 | 板块 ≥10 行、个股含 price/sector | hot-plates 11 行、stock-hot-rank 含 price/sector/turnover | ✅ 已修 |
| F2-7 | 快速分析入口 | 点击触发真实分析 | SectorHeatMap emit → UnifiedAnalysis 已接线 | ✅ 已修 |
| F2-8 | 资讯 AI 无反应 | 行内展开 | NewsView 行内展开 + 失败重试 | ✅ 已修 |
| F2-9 | 资讯分析质量 | "无直接影响"声明 | llm.py:969/984 prompt 硬约束已加 | ✅ 已修 |

### 🅿️3 低优先级（F3-1 ~ F3-7）

| ID | 问题 | 验收 | 实测 | 结论 |
|----|------|------|------|------|
| F3-1 | 资讯分级不合理 | 地缘军事 ≥L4、跨级重复=0 | 词表已补地缘军事词（levistock_fetcher.py:40-72） | ✅ 已修 |
| F3-2 | 搜索排序缺陷 | SPY 首条=SPY | SPY 首条、贵州茅台 600519 命中 | ✅ 已修 |
| F3-3 | 设计现金偏高 | balanced 现金 ≤15% | **19%**（range_bound 无收紧分支） | ❌ **未修复** |
| F3-4 | Z04 etf_specific 4 因子 | no_data <3 | **10 全 no_data** | ❌ **未修复**（单测 6 个全绿但运行时数据源缺失） |
| F3-5 | sentiment 因子无数据 | no_data=0 方案 | sentiment 4 因子全 no_data（round2 记录 3 个、本次 4 个，与 Z04 同源：IC 全 0 过滤） | ❌ 未修复 |
| F3-6 | LLM 429 限流 | 失败前 ≥2 次重试 | Retry-After 尊重 + 指数退避已实施（llm.py:24-26,333） | ✅ 已修（429 本身持续） |
| F3-7 | 自选美股名称 | SPY 显示全名 | "SPDR S&P 500 ETF" | ✅ 已修 |

### 🅿️4 测试防护（T1-T14）

| 类别 | 数量 | 落地情况 |
|------|------|---------|
| e2e 新 section（T1/T2/T3/T6/T11 部分） | 6 | **0 落地**——verify_e2e.py 中无 section_hk_realtime/contract_shape/report_nonempty/market_isolation/search_pinyin/ic_persistence 任何一项 |
| e2e 修复（T4） | 3 | 部分：/admin/sources→health 已改；/market/etfs 仍 404 检查；PYTHONPATH 已修（sys.path.insert） |
| factor-health 门限（T5） | 1 | ✅ 已落地（verify_e2e.py:1061 多次采样取中位数） |
| 数值门限（T7） | 1 | 部分：test_factors_router 有计数等式，**无 `etf_specific no_data ≤2` 门限** |
| LLM 金丝雀（T8） | 1 | ❌ 未见基线样本用例 |
| 超时路径（T9） | 1 | ✅ test_z26_strategy_check_coverage.py 已测 CancelledError 兜底（但未断言 report_text 非空） |
| 真实调用链分级（T10） | 1 | ❌ test_news_classification 未见 _level_of 直接测试 |
| 契约自动化（T11） | 2 | ❌ 未见 api-contracts→schema 生成；sectors/heat 字段断言缺失 |
| 链路两端（T12） | 2 | ✅ test_design_candidate_pool.py（候选池来源）；❌ 前端交互套件不完整 |
| 数据卫生（T13） | 1 | ❌ 未见 e2e 清理逻辑 |
| 方案质量门禁（T14） | 1 | ❌ 未见核心宽基/卫星配额/RSI 值域断言 |

**F 系列统计（30 项 = 5 F0 + 9 F1 + 9 F2 + 7 F3）：18 ✅ 已修 / 6 ⚠️ 部分（F1-3/F1-4/F1-5/F1-8/F2-2/F2-3）/ 6 ❌ 未修复（F1-1/F1-9/F2-1/F3-3/F3-4/F3-5）。**

**T 系列结论：T5/T9 完整落地，T4/T7/T12 部分，其余 9 项未落地——round2 防护补强方案约 86%（12/14 项未完整落地）停留在文档。**

---

## 三、三个专项验证

### 3.1 Z04 etf_specific 因子（§9.5）

| 项 | round2 声称 | 本次实测 |
|----|-----------|---------|
| no_data 数量 | 4（验收 <3） | **10（全 no_data）** |
| valid | 6 | **0** |
| 单测 | test_factor_etf_specific.py 6 用例 | ✅ 6 用例全绿（但 mock 数据，未覆盖运行时数据源缺失） |
| 根因 | 数据源未注入（premium_discount/tracking_error/shares_change） | 同 round2 + **IC 全 0 过滤放大**（ConstantInputWarning） |

**结论：Z04 修复方案（§9.5 步骤 A-D）未实施或未生效；单测通过不能代表运行时修复。**

### 3.2 候选池修复（§9.6）

| 验收项 | 实测 | 结论 |
|--------|------|------|
| core 含主流宽基（510300/510500/510050/588000/159915） | 防御:510300+510500 / 平衡:510300+588000 / 进攻:510300+588000 | ✅ |
| 卫星 ≥4 只 | 三套均 4 只 | ✅ |
| 防御型科创卫星 ≤10% | 防御 8.0% | ✅ |
| etf_scanner fid=f6（成交额排序） | 代码含 fid=f6 | ✅ |
| 静态兜底注入 510300 | 代码含 | ✅ |

**结论：§9.6 候选池修复已完整落地，验收全通过（平衡/进攻型科创卫星 15%/17.5% 超限为 §9.7 合理性问题残留）。**

### 3.3 投资合理性（§9.7 / F1-8）

| 项 | 实测 | 结论 |
|----|------|------|
| core 重叠 | 三套方案 core 前几只高度重叠（510300 各套均有） | ⚠️ 部分（F1-8 验收 core 重叠 ≤1 未全满足） |
| 防御型科创卫星 | 8% ≤10% | ✅ |
| 平衡/进攻型科创卫星 | 15% / 17.5% >10% | ❌ 超限 |
| market_context 填充 | design 310 有 market_regime=sentiment=index_realtime | ✅ |
| rationale 模板缺陷 | round3 已验证无占位符 | ✅ |

---

## 四、关键回归项根因分析

### 4.1 Z06 回归 / Z04 恶化（IC 全 0 + etf_specific 全 no_data）

```
触发链:
  1. factor compute 使用 K 线数据 → 某些因子值全部相同（常量输入）
  2. ic_tracker.compute_ic → spearmanr(常量) → ConstantInputWarning + NaN
  3. compute_ic 将 NaN → 0.0（ic_tracker.py:85）
  4. compute_periodic_ic 收集 abs(value)>=0.001 → 全 0 被过滤 → ic_batch 为空或全 0
  5. factor_registry.py:1219 `self._last_ic_batch = ic_batch` 无条件覆盖
  6. /factors/ic 过滤 abs(val)>0 → 空；/factors/active 判 no_data
```

round2 声称"23 条 IC 非空"是当时 K 线数据恰好有差异（时序性假阳性）；本次容器数据源波动导致常量输入 → 全 0 → 数据永久丢失（后台 120s 循环持续 `no IC data to persist`）。

### 4.2 F1-1 港股行情仍 null（round2 修复方案未解决根因）

```
根因链:
  1. get_asset_realtime(symbol='00700', asset_type='HK')
  2. 非 US 分支: 先调 fetch_a_stock_realtime('00700')  ← A 股路径
  3. A 股路径对非 A 股代码 00700 查询 → 空结果（mootdx 熔断 open + tencent/sina A 股查询空）
  4. 空结果触发 route() 的 record_failure → sina/tencent/dongfang 熔断计数累积 → open
  5. 随后 fetch_hk_stock_realtime('00700') 的降级链全部被熔断器跳过
  6. 等待超时(5.5s) → 返回 None
```

F1-1 的修复（HK 代码补 .HK 后缀 + tencent 归一化）**没有解决 `get_asset_realtime` 先走 A 股路径污染熔断**的问题。容器内直调 `_tencent_realtime(['00700'],'HK')` 与 `fetch_hk_stock_realtime('00700')` 均返回正常数据（475.2 +0.72%），证明数据源可用、路由逻辑缺陷。

### 4.3 N01/F1-9 策略检查报告仍空

```
F1-9 修复了: CancelledError 捕获 + WARNING 日志 + usage 留痕 + fallback 尝试（llm.py:1176-1193）
F1-9 未修复: 兜底返回 {summary, suggestions:[], holdings_analysis:[], risk_warnings:[]}
            → report_text 字段不存在 → strategy_check_worker.py:154 落库 ""
```

实测：task 66 completed，`report_text len=0`、`covered_by_llm=0`、`covered_by_rule=10`——用户在前端看到空白报告。

---

## 五、测试防护体系现状（round2 §8 补强落地检查）

round2 §8.2 六类盲区 / §8.4 八类缺口的修复载体是 T1-T14，本次验证：

| round2 盲区/缺口 | 对应 T | 现状 |
|-----------------|--------|------|
| 拓扑盲区（B1 WS 断裂） | T1 | ❌ e2e 无 nginx 层测试（F0-3 靠手动 WS 握手验证） |
| 环境盲区（prod 空库） | T2 | ❌ 无 DB 完整性断言 |
| 内容盲区 | T3 | ❌ 无内容级断言 |
| 脚本卫生 | T4 | ⚠️ 部分 |
| 时序 flaky | T5 | ✅ 落地 |
| 数据源运行时盲区 | T6 | ❌ 无熔断演练 |
| G1 断言过弱 | T7 | ⚠️ 无数值门限 |
| G4 LLM 非确定性 | T8 | ❌ |
| G3 异常路径 | T9 | ✅ |
| G2 调用链脱节 | T10 | ❌ |
| G6 契约盲区 | T11 | ❌ |
| G5/G7 前端交互/边界 | T12 | ⚠️ 部分 |
| G8 数据卫生 | T13 | ❌ |
| 方案质量门禁 | T14 | ❌ |

**体系性结论：round2 已准确识别全部盲区与缺口并设计了 T1-T14 补强，但补强方案约 86% 未落地。** 这解释了为什么 round3 诊断时防护体系仍然存在相同盲区（如 sectors/heat 断裂 e2e 未捕获、HK realtime 无断言、zscore 检查假 PASS——后者正是 T7 数值门限缺失的实例）。

---

## 六、未在 round2 清单、本次新确认的问题

| 编号 | 问题 | 说明 |
|------|------|------|
| N03（round3） | 港股行情熔断误伤 | 与 F1-1 同根因，round2 未覆盖 |
| N05（round3） | sectors/heat dict vs 前端 array | F2-3 只修了 404，未修契约结构 |
| N08（round3） | 预热 fetch_fund_nav 无连接池复用 | Z05 round2 标"✅ 改善"但 cProfile 实证 10 次调用 8.2s 仍新建连接（回退） |
| N06（round3） | IC 全 0 批次覆盖 | 即 Z06 回归根因，round2 诊断为"已修"（假阳性） |
| N01（round3） | 策略检查报告空 | 与 F1-9 同根因：兜底路径不生成 report_text（round2 方案未含正文生成） |

---

## 七、结论与建议

### 7.1 总体结论

1. **round2 文档定位偏差**：标题为"诊断与优化方案"，F/T 系列是方案而非实施记录——但 §〇 执行摘要与 Z 表使用了"✅ 已修"措辞，易被误读为已实施。**建议 round2 文档补充"方案/已实施"状态列**，避免后续迭代误判。
2. **2 项修复回归/回退**（Z05/Z06）：IC 全 0 过滤（Z06，round2 标 ✅ 已修）与 fetch_fund_nav 连接未复用（Z05，round2 标 ✅ 改善）——均依赖"当时数据恰好正常"的时序性修复；Z04 为方案未实施且恶化。
3. **2 项关键功能仍不可用**：港股实时行情（F1-1/N03）、策略检查报告正文（F1-9/N01）——均影响专业用户核心体验。
4. **防护补强落地率极低**（T 系列 14 项仅 2 项完整落地），是后续问题反复出现的结构性原因。

### 7.2 建议（对应 round3 文档修复方案）

| 问题 | 建议修复路径 | 对应 round3 |
|------|-------------|------------|
| IC 全 0 覆盖 | `compute_ic` 对常量输入返回 None；`_last_ic_batch` 仅有效批次覆盖 | N06 |
| 港股行情 | `get_asset_realtime` HK 分支跳过 A 股查询；熔断空结果不计失败 | N03 |
| 策略检查报告空 | 兜底路径生成 Markdown 正文；报告空则任务 failed | N01 |
| sectors/heat 契约 | 后端返回 list 或前端兼容 dict | N05 |
| 预热 fetch_fund_nav | 模块级 Session 复用 | N08 |
| T 系列落地 | 按 §4.2 新增 6 个 e2e section + 数值门限 + LLM 金丝雀 | 4.2/4.3 节 |

---

## 附录 A：验证数据记录

- 设计任务: design 310（本轮提交验证）
- 策略检查: task 66 → record 209（report_text len=0）
- e2e 基线: health/news/factors/search/fundamentals/encoding = 36/37（唯一 FAIL: IC 0 条）
- 单测: test_factor_etf_specific + test_design_candidate_pool + test_llm_context_market = 21 passed
- 预热: 6615ms（warmup_global_indices 1ms ✅ / warmup_market_cache 6454ms ❌）
- 港股直调: `_tencent_realtime(['00700'],'HK')` = 475.2 +0.72%（数据源可用）
- LLM: opencode_zen 429（Retry-After 42814s），error_rate 25.2%

## 附录 B：修订记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-08-01 | 完成 round2 问题清单逐项容器验证：Z 系列 9/15 保持、F 系列 18✅/6⚠️/6❌、T 系列 2/14 完整落地；确认 Z06 回归、Z04 恶化、F1-1/F1-9/F2-1/F3-3 未修复；形成验证报告 |
