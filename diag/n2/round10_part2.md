# Round10 容器化复诊断与优化方案（续 · 4-10 节）

---

## 4. 行情分析功能测试（A股/港股/美股）

| 功能 | 端点 | 结果 |
|---|---|---|
| 综合研判 | POST /analysis/llm-report | ✅ A 63.4s / HK 58.9s / US 33.4s 全成功，报告含实时指数/板块/情绪（口径统一 37.8） |
| **AI 投顾问答** | POST /analysis/llm-advice | ❌ **3 市场全部退化为「暂无实时指数数据/暂无板块热力/市场状态未知」模板**（§4.1） |
| 板块分析 | POST /analysis/sector-analysis/stream | ✅ 200，1489 events |
| 概念分析 | POST /analysis/sector-analysis/stream | ✅ 200，2019 events |
| 个股/ETF/指数分析 | POST /analysis/symbol-analysis/stream | ✅ 5 类全出文（600519 3334 / 510300 3353 / 00700 2069 / AAPL 2333 / 000300 3170 字），无 STREAM_ERROR（P0-1 确认） |
| 搜索自动补全 | GET /market/search | ✅ A/茅台 1、A/510 9、A/沪深300 14、HK/0070 1、HK/腾讯 1、US/AAPL 1、US/苹果 1（include_stocks=true 全命中，O4 确认修复） |

### 4.1 【新高】AI 投顾问答数据槽位错配 bug（round9 §5 未暴露）
- **现象**：llm-advice 对 A/HK/US 均返回结构完整但**全部「暂无实时指数数据/暂无板块热力/市场状态未知」**——内容空洞无实际行情支撑。
- **根因（代码级实证）**：
  1. `llm_advice` router（analysis.py:368-373）仅调用 `_build_advice_market_snapshot()` 写 **`ctx["market_snapshot"]`**；
  2. `_build_advice_market_snapshot()` 在容器内生成了 **174 字符快照**（市场状态 + 情绪 + 上证/深证/创业板/沪深300/科创50 实时价）——注入成功；
  3. 但 `generate_advice()`（llm.py:876-882）第一段读 **`context["market_data"]` / `["market_regime"]` / `["market_sentiment"]`**（未注入 → 空）→ 大盘概况模板化；`market_snapshot` 只在第三段「资金面」出现；
  4. **prompt「一、大盘概况」写死「暂无实时指数数据」→ LLM 被冲突 prompt 带偏，按模板输出数据缺失**。
- **本质**：`market_snapshot` 是字符串注入槽，而 `generate_advice` 需要结构化 market_data/regime/sentiment 槽——**router 与引擎契约错配**。

### 4.2 报告内容质量（专业投资者视角）
- A股个股：PE-TTM 36.48 历史中上、技术面绑缚完整；ETF：基金规模 995 亿/资金净流入；US：三季度财报（营收 +16%）完整；HK：回购行为+实时价——**基本面/资金面引用准确**；
- ⚠️ ETF/指数/HK 报告「估值数据缺失」诚实降级（容器内 PE/PB 拿不到），数据完整性受限但未谎报。

---

## 5. 热点/自选/技术分析/资讯/因子验证

### 5.1 热点板块与个股 ✅
- hot-plates 11 条（含 change/reason/lead_stocks）；sectors/heat 20 条 **9 条真实涨跌幅**（PCB +5.63%、通信 +3.76%）；stock-hot-rank 50 条真实 pct（药明康德 +8.49%、哈药股份 +9.97%）——全部加载成功。

### 5.2 自选功能 ⚠️ 部分断裂
- **添加成功 + 名称正确回填**（159915→创业板ETF易方达、00981→中芯国际，O9 补名 ✅）；
- **但 GET /watchlist 实时行情全 None**：容器内 enrich 5s 超时 → DB-only 兜底 → 列表 price/pct/vol 全空；
- **端点总耗时 11-14s**：响应 200 但慢（DB-only 分支后仍有阻塞），前端「组合管理」12s 窗口 requestfailed——**P0-4 只治响应端，未解决 realtime 数据 + 实际耗时偏高**。

### 5.3 技术分析与综合信号 ⚠️ 与策略检查矛盾
- `/signal` 接口 10 只持仓全部 data_available=true，分布 **buy 3 / sell 2 / hold 5**（有区分度）；
- `/indicators` 有真实 MA/RSI/MACD（RSI 64.8、MACD 金叉）；
- **但策略检查对同一批全部「数据不可用」+ hold**——两数据链路在容器内 K 线缓存时刻不一致产生矛盾，**同一持仓两处信号打架，专业不可接受**。

### 5.4 资讯页面 ✅ 改善
- level 分布：headlines {1:7, 2:2, 3:4, 4:4, 5:3}——L5 占比 15%（round9 50% 失真改善）、有 L1；stars 独立维度（4:13/5:7）——P2-1 部分达成；
- ⚠️ L1 仍占 35%（头条多为次要宏观/财经快讯），分级规则保守。

### 5.5 因子模型 ✅ 大幅改善
- summary：**valid=12 / warn=13 / no_data=2 / static=6 / avg_ic=0.0206**——no_data 从 round9 **6 项降到 2 项**；
  - **no_data 仅剩** tracking_error（缺 benchmark_close）、shares_change（缺 shares_change_20d）——**P1-8/P1-9 数据源接入未做**；
  - **折溢价率已消除 no_data，IC=0.1321**——**P0-6/P0-7 IOPV 链修复确认** ✅；
  - **sentiment 三因子 static**（reason「市场级因子不参与截面 IC」）——**P1-10 确认** ✅；
- **neg-IC 已标 warn**（`|IC|=0.45 ≥ 阈值(负向)` 文案修正，P1-3 部分）——但 **13 个负 IC 因子仍活跃未淘汰**（O6 未落地）；
- IC 明细（29 条）：return_1m +0.67 / macd_raw +0.65 / signal.overall +0.62 强正；bollinger.bandwidth -0.56 / change_pct -0.45 / atr -0.43 强负。

---

## 6. 前后端数据断裂排查

- **8 页面前端走查：0 JS console error**；
- **唯一断裂 = 「组合管理」页 2 个请求（/portfolio/tasks、/market/watchlist）12s 内 requestfailed**——慢后端软断裂；
- nginx `/api` 代理 200、`/api/v1/ws` 代理配置正确；
- ⚠️ **nginx `/health` 被 try_files 兜底为前端 index.html**（SPA 吞掉健康检查路径，非致命）。