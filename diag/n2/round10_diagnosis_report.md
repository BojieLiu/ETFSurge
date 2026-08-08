# Round10 容器化复诊断与优化方案

> 状态：**诊断完成 + 方案设计完成，未实施**
> 日期：2026-08-08
> 范围：Docker prod 容器内全链路复诊断（构建/预热/设计/策略检查/行情分析/搜索/自选/技术分析/资讯/因子/前端Lighthouse/后端性能/测试防护/round9清单核对）
> 基线：HEAD = b2fd04c（round9 实施完成），工作树干净

---

## 0. 摘要

在 Docker prod 容器（docker-compose --profile prod，镜像烘焙）对 ETF Surge 做第 10 轮全链路复诊断。相对 round9（2026-08-07 同容器环境）的核心结论：

1. **超半数 round9 方案落地并确认修复**（P0-6/7 IOPV 链、P0-8 幽灵锚 560600→159338、P1-6 market_regime、P1-10 sentiment 静态化、P0-1 symbol-analysis 等）；预热从 37.4s→12.1s、watchlist 从 29.9s→3.0s。
2. **但容器内外部数据源脆弱（round9 C4/P0-2）未根治** → 本轮下游数据完整性故障几乎全部由此引发：策略检查 fetch_history 全空 → 因子 6/34 + 10 只 signal 全「数据不可用」；watchlist 实时 enrich 超时 → 列表 realtime 全 None；AI 投顾数据注入链断裂。
3. **新发现 3 个 round9 未暴露的问题**：
   - **AI 投顾（llm-advice）数据槽位错配 bug**——router 只注入 `ctx["market_snapshot"]`，但 `generate_advice` 第一段（大盘概况）读 `market_data/regime/sentiment` 槽（未注入）、第三段才用 market_snapshot → 3 市场投顾全部退化为「暂无实时指数数据/板块」模板（round9 §5 llm-advice ✅ 曾通过，本轮回归）；
   - **前端 Lighthouse 严重劣化**：/ 52、/market-analysis 89、/portfolio-analysis 73（round9 90/100/99）——首页跌破 F18 硬门禁 60、CLS 0.389 远超 0.1（round9 0.004）；
   - **后端新性能黑洞** `/admin/factor-health` 10.9s（round9 §10 未记录）。
4. **round9 清单核对**：47 项中确认修复 20 余、部分 12、**未修复 2（P1-8 benchmark_close、P1-9 shares_change）**、未专项验证 10。
5. **报告质量**：设计 456 明显提升（无幽灵锚/涨跌全真/regime 补齐）；但策略检查仍存在「报告标题因子 10/10 vs 逐项 6/34」「10 只全 hold 无真实信号」的诚实性/可用性缺陷，专业投资者仍不可接受。
6. **测试防护盲区**：本轮 6 个新/复现问题全部落在 6 类盲区（AI投顾内容零断言、策略检查 filled 与标题一致性零断言、watchlist realtime 零断言、Lighthouse 门禁平时不跑、负 IC 淘汰零门禁、容器弱数据源无模拟）。

**方案**：P0×5（数据完整性阻断）/ P1×8 / P2×5 / P3×7 共 25 项，均附验收标准，未实施。

---

## 1. 执行环境

- 同 round9：docker-compose v2 + prod profile（redis/backend/frontend-nginx）。
- 后端预热诊断：`docker compose run --no-deps -e PROFILE_WARMUP=1` 临时注入（P3-6 回滚后的正规诊断方式），产物落宿主 `logs/`。
- 前端：playwright (frontend/node_modules) + lighthouse 13.4.1 + chrome-launcher。
- LLM provider：opencode_zen（deepseek-v4-flash-free），时快时慢（60-121s）+ 偶发 500。

---

## 2. 预热性能诊断（PROFILE_WARMUP=1）

| 指标 | 本轮 | round9 | 判定 |
|---|---|---|---|
| 墙钟启动→预热完成 | **12.1s** | 37.4s | ✅ 大幅改善（低于 30s 阈值） |
| profiler 主段 | warmup_market_cache 11.83s/6.8s run_sync 批量实时 | 12.46s + EM 54.5s 空等重试 | ✅ EM 空等重试已调解 |
| cProfile 热点 | levistock 资讯 3.0s / fund_open_fund_info_em 2.5s / fund_nav 1.9s / advance_decline 1.1s | requests/akshare 54.5s（EM 拦截重试） | ✅ 均为正常网络 I/O |

**结论**：round9 C4（容器内 EM TLS 拦截导致预热 37.4s 空等）本轮**未在预热路径复现**——降级链（sina/qq/ttj）已接管 ETF 池/行情缓存主采集。预热健康。

**注意**：预热 12.1s 的主耗仍集中在 `refresh_market_cache → get_portfolio_realtime → run_sync 6.8s`——行情批量采集单点 6.8s，虽不超阈值但仍是预热耗时大头。

---

## 3. 组合设计与策略检查质量审阅（专业投资者视角）

### 3.1 组合设计（design #456，balanced/50万/A股）
**产出**：防御 10 / 平衡 13 / 进攻 12（含现金），报告 8694 字，report_quality=full。

**通过项（round9 P0/P1 修复确认）**：
1. **560600 幽灵锚已移除**：三套方案核心层全部为 159338 中证A500ETF国泰（真实标的）——P0-8 ✅；
2. **18 只标的全有真实「今日涨跌」**（510050 +1.13%、159338 +1.76% 等），无「数据源不可用」——P0-8/P1-12 ✅；
3. **顶层 `market_regime=range_bound` 已补**（round9 None）——P1-6 ✅；
4. **`market_context.data_fetched_at=08:11:11` 存在**——P0-9 时间戳字段已加；
5. 三层结构 + 现金分离清晰。

**问题项（本轮发现）**：
1. **「今日涨跌」无显式时间戳标注**——data_fetched_at 在 API 元数据，但**报告表格列仍无「（截至 08:11）」**，用户仍会误读为收盘值（盘中 vs 收盘对照 17/18 错位实证）；
2. **562600 医疗器械ETF 今日涨跌 +0.00%**——疑似零成交/数据缺失（幽灵锚同型风险），仅在卫星层 4%；
3. **多只卫星层标的 factor_score 为负仍入选**（平衡型 562870 -0.53 / 562600 -0.1 / 562990 -0.41 / 562950 -0.42）——负因子分入选卫星，入选逻辑张力；
4. 防御型卫星含「证券ETF嘉实 12%」（高贝塔），定位张力（同 round9 问题 6）。

### 3.2 场内策略检查（check #371，portfolio_type=on_exchange，task 299）
**通过项**：
- `portfolio_type=on_exchange` 过滤正确（10 场内）；P2-4 portfolio_type 已持久化（record 371）；
- 兜底机制诚实：summary「LLM 分析超时（90s 未返回，已用规则引擎兜底）」——P0-5 超时 60s→90s；
- **兜底建议已个性化**：按因子分区间给差异化理由（「维持现状…关注 RSI 超卖」），不再是 round9 同模板。

**问题项（专业不可接受）**：
1. **LLM 90s 仍超时 → 规则兜底**：10/10 全 hold、全「数据不可用」，与技术分析接口真实信号（buy 3 / sell 2 / hold 5）**完全矛盾**；因子分 16-18 挤堆无区分度；
2. **「因子数据质量：10/10 只持仓因子数据可用」标题 vs 逐项 factor_availability 6/34、RSI/KDJ 全 50.00**——**P1-15 假正常换形式复现**（report_text 模板 1285 行仍用 `filled/{total} 只可用`，data_quality.fallback_ratio 已算但未用），报告中含「数据不可用」因子；
3. **`industry:""` 全空**——候选池（弱源）空 → industry_map 空 → P1-14 的 ETFClassifier 兜底在容器内未生效；
4. **10/10 tech_signal「数据不可用」**——P1-13 显式兜底生效（不再空白），但指示器采集在容器内全空。

**根因（决定性）**：策略检查数据采集时刻（08:13:33）**10 只持仓全部 `fetch_history failed: empty data — skipping`**——容器内该时刻 EM/mootdx 历史源均失败，因子只能拿 DB 恢复的少量值；而**宿主 env + /signal 接口对同一批标的成功算出 RSI 64.8 / MACD 金叉**。**本质是容器数据源脆弱（P0-2 未根治）在下游管线的再现**——design 恰赶上降级源成功窗口，check 赶上失败窗口，时好时坏。