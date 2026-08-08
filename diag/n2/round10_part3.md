# Round10 容器化复诊断与优化方案（续 · 7-10 节）

---

## 7. round9 清单核对摘要（详表见 diag/n2/round9_verification_n2.md）

- **确认修复（20 余）**：P0-1/2(预热段)/3/6/7/8、P1-1/2/4/5/6/7/10/12、P2-3/4/7/8/10、P3-1/4/6/7/8 等；
- **部分修复（12）**：P0-2/4/5/9、P1-3/13/14/15、P2-1/6、P3-2/9/10；
- **未修复（2）**：P1-8（benchmark_close）、P1-9（shares_change）——数据源接入工作仍未做；
- **未专项验证（10）**：P1-4/11/16、P2-2/5/11、P3-3/5 等。

---

## 8. 性能（前端 Lighthouse + 后端 perf_diag）

### 8.1 前端 Lighthouse（13.4.1，desktop preset）
| 页面 | 本轮 | round9 | 变化 |
|---|---|---|---|
| 首页 / | **52**（CLS 0.389 / TBT 640ms / LCP 3.5s） | 90（CLS 0.004） | **-38 严重劣化** |
| 行情分析 /market-analysis | 89（CLS 0.001） | 100 | -11 |
| 组合管理 /portfolio-analysis | 73（TBT 800ms） | 99 | -26 |

**首页 perf 52 < F18 硬门禁 60，CLS 0.389 >> 0.1**。根因：
- **CLS 0.389**：dashboard `<div class="summary-grid">` 主内容网格（Lighthouse cls-culprits score 0.3885）——图表/卡片容器**未预留高度/宽度**，数据加载后位移；
- **主线程 3.0s**：Script Evaluation 1.2s + Style & Layout 927ms（echarts + 骨架屏开销）；
- 相对 round9 劣化主因：**首页骨架屏/图表容器布局未锁 + 慢后端（watchlist/calculate）加载期多次重布局**。

### 8.2 后端全链路（perf_diag.py，49 端点）
48/49 通过（1 个 422 body 空预期）。**8 个 >1s**：

| 端点 | 耗时 | 对照 |
|---|---|---|
| `/admin/factor-health` | **10964ms** | **新黑洞（round9 未记录）** |
| `/portfolio/calculate` | 5059ms | 5052ms（持平） |
| `/market/indices/global` | 3929ms | 4367ms（改善） |
| `/market/stock-hot-rank` | 3433ms | 4711ms（改善） |
| `/market/watchlist` | 3041ms | 29856ms（**29.9s→3.0s 巨大改善**） |
| `/market/chart` | 1932ms | 2092ms |
| `/market/wind` | 1591ms | 1831ms |
| `/portfolio/tasks` | 1253ms | 1387ms |

**watchlist 29.9s→3.0s（P0-4 生效）**，但仍 >1s 且实时数据空；**factor-health 10.9s 为新性能黑洞**（逐因子健康探测串行/自采）。

---

## 9. 测试防护体系为何未识别（6 类盲区，本轮 6 个问题均落盲区）

1. **AI 投顾内容零断言（新）**：verify_e2e section_analysis 对 llm-advice 只测 HTTP 200/非空字符串，**不断言 advice 含实时行情数据**（指数名/值/情绪）→ llm-advice 数据槽位错配（§4.1）在 3 市场全模板化时通过；
2. **策略检查 filled 与标题一致性零断言（换形式）**：round9 P3-10 断言 tech_signal 非空（本轮「数据不可用」满足）与可用占比，但 **未断言 report_text 标题「N/M 可用」与每只 holdings factor_availability.filled 一致** → P1-15 假正常换形式（10/10 vs 6/34）漏网；
3. **watchlist realtime 零断言（延续）**：P3-2 加了耗时门禁但 **不测 realtime price/pct 非 None** → 列表实时全空仍通过；
4. **Lighthouse 门禁平时不跑（延续）**：F18 硬门禁只在 round8 专项跑过，**后续 commit 未接 CI** → 首页 perf 52 / CLS 0.389 回归无人发现；
5. **负 IC 淘汰零门禁（延续）**：factors/active 只测列表非空 + reason 文案，**不断言「强负 IC NOT 在活跃列表」** → O6 未落地静默通过；
6. **容器弱数据源无模拟（延续/核心）**：所有单测/e2e 用「完美数据」mock，**从不在容器内模拟 EM 源弱/TLS 拦截** → P0-2 下游连锁（策略检查因子空、watchlist 实时空）在真实弱源下零拦截。

> 根因归：**门禁验证「自述行为」而非「生产形态（容器）+ 真实混合数据 + 跨模块消费」**——尤其「模块间契约（router 注入槽 vs 引擎消费槽）」与「容器弱源降级链」两大维度系统缺失。

---

## 10. 优化方案（未实施）

### P0（数据完整性/功能阻断）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P0-A | **AI 投顾数据槽位错配**（§4.1） | `llm_advice` router 除注入 `market_snapshot` 外**同时注入 `market_data`/`market_regime`/`market_sentiment`/`hot_plates`/`sector_heat`**（复用快照构建已取的结构化数据）；或 `generate_advice` 大盘概况直接优先解析 `market_snapshot` | llm-advice 对 3 市场返回含真实指数名/值/涨跌幅与情绪，不再「暂无实时指数数据」 |
| P0-B | **策略检查报告标题 vs 逐项 filled 矛盾**（§3.2-2） | report_text 模板（portfolio_service.py:1285）改吃 `data_quality.fallback_count/ratio`，标题按「真实 filled/total 只可用（其中 N 只全兜底）」；全兜底时不报「N/M 正常」 | 全兜底场景不再出现「10/10 可用」；报告明示真实覆盖率 |
| P0-C | **策略检查 fetch_history 数据源脆弱 → 因子/信号全空**（§3.2 根因） | factor_registry.compute K 线采集加多级降级 + 失败时用 cache/上次成功拉取兜底（标注 data_source=stale）；若 10/10 全空则明示「数据源不可用」 | 容器弱源下 filled 不再骤降 6/34；全空时文案诚实 |
| P0-D | **前端首页 perf 52 / CLS 0.389**（§8.1） | Dashboard `summary-grid` 与各图卡容器锁 aspect-ratio/min-height（骨架屏与真数据同构替换）；echarts init 前锁容器高 | 首页 CLS <0.1、perf ≥60（Lighthouse 复测） |
| P0-E | **watchlist 实时空 + 耗时偏高**（§5.2） | enrich 超时后**降级到单标的轻量快照（5s TTL quote 缓存）**回填 realtime；DB-only 时前端标注「行情加载中」 | 列表 10 条 realtime 全非 None；端点 ≤3s；前端不再 requestfailed |

### P1（数据完整性）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P1-A | factor-health 10.9s 黑洞（§8.2） | 逐因子健康探测加缓存/并发/短路（同 watchlist 模式），慢源不阻塞 | factor-health ≤2s |
| P1-B | design 表格「今日涨跌」无显式时间戳（§3.1-1） | 报告表格列加「今日涨跌（截至 data_fetched_at HH:MM）」 | 表格可见时刻标注 |
| P1-C | 负 IC 强因子未淘汰（§5.5/O6） | 负 IC 且 \|IC\|≥0.05 的因子从 active 降权/下架（inactive 列表），reason 标注「负向预测已下架」 | factors/active 无强负 IC 活跃项 |
| P1-D | 卫星层负 factor_score 入选（§3.1-3） | 卫星层对 factor_score 显著为负的标的不给权重（或降级并列标注） | 卫星层无强负分标的 |
| P1-E | watchlist realtime None 前端体验（§5.2） | 前端列表无 realtime 时显示「—」+ tooltip「行情加载中（数据源弱）」 | 自选页有明确加载态 |
| P1-F | AI 投顾 L1 分级偏高（§5.4） | 校准 level 规则（时效/来源权重/量级），降低低权重快讯的 level 或改 stars | L1 占比 <25% |
| P1-G | 策略检查 industry 全空（§3.2-7） | industry_map 候选池空时用 instruments 表行业字段 + ETFClassifier 独立兜底（容器弱源下 fallback 可用） | 数据源可用时行业缺失权重 <50% |
| P1-H | 防御型证券 ETF 高贝塔定位（§3.1-4） | 防御型卫星去除非低波标的或报告明示风险 | 报告明确披露 |

### P2（质量/体验）
| # | 项 | 方案 | 验收 |
|---|---|---|---|
| P2-A | LLM 不稳定致投顾/策略检查间歇失败 | LLM 本地缓存（同 query+同 market_data 短 TTL）；provider 多路（opencode_zen→deepseek fallback 已有）；失败自动重试 1 次 | 同 query 短时重复命中缓存；500 自动重试 |
| P2-B | nginx /health 被 SPA 兜底 | nginx 加 `location = /health { proxy_pass http://backend:8000; }` | nginx /health 返回后端 JSON |
| P2-C | 策略检查 10/10 全 hold 无真实信号 | 规则兜底消费真实 /signal（buy/sell/hold 有区分），按信号方向 + 因子分生成非 hold 差异化建议 | 无 LLM 时建议非模板化且与 /signal 不矛盾 |
| P2-D | 报告时间戳前端展示 | 设计详情卡片/报告头显示 data_fetched_at（人类可读） | 用户可见采集时刻 |
| P2-E | 容器弱源降级链路 QA | docker_smoke.py 增加弱源模拟（EM 不可达），断言降级链路（pool/design/hot/signal/watchlist）不崩溃且诚实降级 | 弱源下各端点限时内返回 |

### P3（测试防护补强）
| # | 项 | 方案 |
|---|---|---|
| P3-A | **AI 投顾内容门禁**：verify_e2e 对 llm-advice 断言输出含「上证指数/深证成指/市场状态:」至少一项真实数据关键词，否则 FAIL | llm-advice 模板化必 FAIL |
| P3-B | **策略一致性断言**：断言每只 factor_availability.filled 与 report_text「N/M 可用」一致；全兜底不得报「N/M 正常」 | P1-15 换形式回归必 FAIL |
| P3-C | **watchlist realtime 断言**：verify_e2e watchlist 断言 items 每项 realtime.price 非 None（缓存热时） | 列表实时空必拦 |
| P3-D | **Lighthouse 进 CI**：F18（perf≥60、CLS≤0.1）首页/行情/组合三页每次 merge 前必测 | 首页 perf 52 类回归必 FAIL |
| P3-E | **负 IC 下架门禁**：factors/active 断言无「强负 IC 活跃项」 | O6 方案落地后防再犯 |
| P3-F | **容器弱源集成测试**：mock「EM 不可达」的容器级集成（断言降级链数据完整） | 本轮 P0-C/P1-G 类弱源问题在门禁可拦 |
| P3-G | **模块契约测试**：llm_advice router 与 generate_advice 的 context key 契约单测（断言 router 注入的 key ⊆ 引擎消费的 key） | 槽位错配类回归必拦 |