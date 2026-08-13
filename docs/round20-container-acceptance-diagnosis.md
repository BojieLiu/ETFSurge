# Round20 容器验收诊断（2026-08-13）— 全链路复诊 + round18/19 落地核对 + 关联度专项审阅 + 优化方案

> **性质**：容器验收诊断（对标 round18 流程）——构建最新代码（a842bb2）→ 预热性能诊断 → 组合设计 + on_exchange 策略检查 → 三市场分析 → 功能页面验证 → 数据断裂排查 → round18/19 落地核对 → 前后端性能诊断 → 测试盲区归因 → 冗余清理清单 → 优化方案（**本份只设计不实施**）。
> **验证窗口**：2026-08-13（周四）11:05-12:40 UTC+8，**交易时段内**（A股午盘前）——与 round18（非交易时段）形成对照，可区分「冷却期现象」与「代码问题」。
> **环境**：Docker prod profile + `docker-compose.diag.yml` 诊断 override（`PROFILE_WARMUP=1`）；commit `a842bb2`（round18+round19 实施后最新）；后端 8000 / 前端 80。
> **基线对照**：round18（2026-08-12 非交易时段）+ round19（2026-08-12 组合诊断）文档。

---

## 一、诊断范围与方法

| 阶段 | 动作 | 结果落点 |
|---|---|---|
| 1 构建 | `docker compose --profile prod build` + 回收老镜像 + diag override 启动 | §2.1 |
| 2 预热诊断 | WarmupProfiler（PROFILE_WARMUP=1，warmup_timing.json + cProfile） | §2.1 |
| 3 组合设计+策略检查 | design task 416→record 525；strategy-check task 417（on_exchange） | §3.1/§3.2 |
| 4 三市场分析 | symbol-analysis / llm-report / llm-advice / sector-analysis / search（A/HK/US） | §3.3 |
| 5-9 功能验收 | hot-plates / sectors-heat / watchlist / signal / news / factors | §3.4-§3.8 |
| 10 断裂排查 | 前端渲染层 × 后端数据层 × 前端 API 层三方比对 | §4 |
| 11 docs 落地 | round18/round19 方案逐项核对（静态代码 + 运行时验证） | §5 |
| 12 前端性能 | Lighthouse 13.4.1 四 URL（home 内嵌 factors 组件，覆盖五页面） | §2.2 |
| 13 后端性能 | 23 条热点链路 ×3 次 | §2.3 |
| 14 测试盲区 | 本轮发现 vs 测试防护体系归因 | §6 |
| 15 冗余 | 死端点/遗留文件/探针残留清理清单 | §7 |
| 16 方案 | P0-P2 分级（本份不实施） | §8 |

> **方法约束**（design-checklist D1-D3）：结论附 `file:line` 与实测命令输出；外部数据源结论标注验证窗口；涉及外部源的结论打标「待交易时段复测」。

---

## 二、性能诊断结论

### 2.1 后端预热（PROFILE_WARMUP=1，产物 `logs/warmup_timing.json` / `warmup_cprofile.txt` / `warmup_pyinstrument.html`）

预热墙钟 **11.19s** / total_elapsed **11188.8ms**（≤25s 门禁达标，但比 round18 非交易 9.0s 更高——交易时段数据源活跃）：

| 分段 | 耗时 | 占比 | 根因（cProfile 证据） |
|---|---|---|---|
| warmup_market_cache | 10002.5ms | 89% | `_mootdx_realtime` 单次建连 **5.84s**（tdxpy connect）；`fetch_margin_change` 5.67s + `fetch_margin_balance` 5.48s（深交所串行 HTTPS）；`news_fetcher._safe` 3.9s |
| warmup_global_indices | 1052.3ms | 9% | 多个 HTTPS 连接（交易时段东财指数快于 round18 的 5.8s） |
| init_db / redis_init / etf_cache | 133ms | 1% | 正常 |

**结论**：预热 11.19s 达标。**新发现交易时段瓶颈**：mootdx/tdxpy 建连 5.84s 为最大单点（round18 未捕获——非交易时段 mootdx 不走该路径），两融数据 5.67/5.48s 与 round18 同源（串行→并发优化目标）。

### 2.2 前端 Lighthouse（13.4.1，四页面，prod 80 端口，交易时段）

| 页面 | performance | LCP | TBT | **CLS** | round18（冷却期）对照 |
|---|---|---|---|---|---|
| **home（Dashboard）** | **57** | 3.1s | 510ms | **0.389** | 46 / CLS 0.389 |
| market | **82** | 3.4s | 330ms | **0.001** | 41 / CLS 0.389 |
| portfolio | **68** | 4.0s | 690ms | **0.001** | 40 / CLS 0.389 |
| news | **99** | 1.9s | 100ms | 0.021 | 34 / CLS 0.389 |

**关键发现**：
- **交易时段全页面 perf 大幅改善**（market 41→82、portfolio 40→68、news 34→99）——确认 round18 判断：冷却期数据源慢 → loading 占位 → CLS/LCP/TBT 全局恶化是「冷却期现象」，非代码问题；
- **home CLS 0.389 是存量确定性问题**：本次 `cumulativeLayoutShiftMainFrame=0.3885205676603475` 与 round18 **浮点级完全一致**——非随机、非冷却期现象，是 home 页面特有布局偏移（round14 P1-G 声称修复无实测，round16/18 均标记存量，本轮交易时段依旧）；
- unused-js：home 85KiB / market 151KiB / portfolio 73KiB（vendor-echarts 大包部分浪费）。

### 2.3 后端全链路（23 条热点链路 ×3 次，含 /health；`logs/tmp/perf_backend.py`）

| 端点 | 3次耗时(ms) | 判定 |
|---|---|---|
| **timeline** | [2815, 2917, 2974] | ❌ **持续 2.9s 恒定不降**——P0-1 声称修复但只做列裁剪，**无 TTL 缓存/limit/分页**（见 §5） |
| admin_metrics | [1892, 43, 43] | ✅ 热态 43ms（P0-2 30s TTL 缓存生效） |
| etfs_list | [2727, 71, 32] | ✅ 首次冷态 DB，热态 71ms |
| realtime_portfolio | [2811, 37, 50] | ✅ 热态 37ms |
| realtime_asset A / HK / US | [140/170/2135, 34/33/44, 33/31/50] | ✅ 热态 <50ms（US 首次 2.1s 源冷态） |
| search | [70, 83, 93] | ✅ <100ms |
| indicators | [2342, 105, 106] | ✅ 热态 105ms |
| chart / signal | [82/115, 100/85, 82/81] | ✅ <120ms |
| history_HK | [1796, 497, 487] | ⚠️ 0.5s 但**返回空**（港股数据源失败，见 §4-4） |
| factors_active | [306, 38, 34] | ✅ 热态 37ms |
| news_headlines / hot_plates / sectors_heat | [49/43/32, 31/30/30, 31/31/41] | ✅ <50ms |
| stock_hot_rank | [4566, 251, 246] | ✅ 热态 250ms |
| watchlist | [2154, 36, 63] | ✅ 热态 63ms |
| indices_global | [4784, 32, 96] | ✅ 热态 96ms |
| fund_flow / sentiment / sector_industry | [49/208/480, 45/54/49] | ✅ <60ms |

**结论**：除 timeline 外，22 条链路均为「首次冷态慢、热态达标」模式（符合 TTL 缓存设计）。**timeline 是唯一热态持续慢端点（2.9s）**——性能门禁验收缺口（见 §6）。

---

## 三、功能验收结论

### 3.1 组合设计（task 416 → design record 525，balanced 50w）

- 状态 completed / report_quality=**partial**（LLM 报告部分降级——opencode_zen 持续 429，deepseek 部分成功）；
- 三套方案：防御 13 只 / 平衡 13 只 / 进攻 8 只（含 CASH），层预算合规（core 45%/sat 18%/def 15% 等）；
- degradation `{mode:normal, pool_degraded:false, factor_matrix_empty:false}`——数据管道正常；
- **专业投资者审阅发现**：
  - D-A1 **技术指标与信号矛盾**：588200 RSI 23.8 明确「超卖」却给「综合信号偏多(+0.60)」+「进攻性强」；159995 RSI 35.9（偏超卖）给「适合进攻」——超卖被建议进攻，逻辑牵强；
  - D-A2 511090（30年国债）综合信号 -0.50（明显负面）仍作三套方案防御层——负信号品种作防御配置矛盾；
  - D-A3 **候选池未纳入当日领涨医药板块**：BK1600 医疗研发外包 +7.27%、BK1216 医药生物 +3.06%（29:0 普涨）是当日最强主线，但方案中仅港股通创新药 159570(-0.95%)、港股创新药 513120(-0.78%) 等低配/负向描述标的，**强势板块与候选池脱节**；
  - D-A4 **多因子评分超「0~1」注释范围**：511090=-2.31、512890=-1.93、159995=+2.41（round18 D1 同源未修）；
  - D-A5 进攻型现金 33%（design 525 实测；task 419/design 527 为 34.4% 见 D-A6）但创业板 20% 高权重——「激进定位」与「高现金」自相矛盾（round18 D2 部分复现）；
  - D-A6 **进攻型卫星层塌缩（本轮新定位的根因链）**：task 419（design 527）进攻型 satellite 层仅 **1 只（588200 科创芯片 9.7%）**，预算 20% 只用 9.7%，现金被顶到 **34.4%（比防御型 22.5% 还高）**。日志证据（logs/backend.log，**三次 aggressive 设计全部命中 underfill**）：`03:09:44 → no non-tech candidates to reclaim 0.100 → CASH underfill`（:55744，budget=0.200）；`03:17:32 → 同上`（:56575）；`04:10:15 → 同上`（:58206）——（同秒 03:09:44 的 `reclaimed 0.032 across 4 non-tech` 属 **balanced** 方案 :55739，budget=0.220，非 aggressive）。**根因链**：aggressive `c2_bonus=+1.5` 科技奖励（allocation_engine.py:401-402）+ momentum 权重 0.45（:361）→ 卫星 top 选 100% 科技（tech_alloc=0.200 占满预算）→ `tech_cap=budget×0.5=0.100` 裁剪（:461, :490）→ 非科技替补候选被**跨方案重叠惩罚 -1.5**（:406-407，`_penalize`=前序方案全部层已用，:778）压到 ≤-0.3 被过滤（:438）→ `no non-tech to reclaim` → 被裁权重转 CASH（:523-529，`satellite budget underfill`）。**替补机制存在但替补池被"跨层惩罚"清空**；
  - D-A7 **防御层纳指/标普归属错配（跨市场被误当防御）**：task 419 防御层 159941 纳指 median_r=**0.457（跨市场标的中最高，防御层全层排第 5，高于国债 0.168/黄金 0.293）**、513500 标普 0.377，且二者两两 r=0.864（美股双宽基）；纳指为高波动成长资产（科技权重 >50%，2026-08-04 单日 -1.78%），却被文案称「避险资产…降低组合波动」——**防御层按"跨境资产类别"硬编码而非"低相关+低波动"筛选**（与 D-A2 同源：511090 负信号仍作防御层）；真对冲（国债 0.168/黄金 0.293/红利低波 0.018）与跨市场成长（纳指 0.457/标普 0.377）在防御层混为一谈。

### 3.2 on_exchange 策略检查（task 417，10 只场内标的）

- 状态 completed，但 **summary 明确「LLM 生成超时(38s)未返回，使用规则引擎兜底，结论: ReadTimeout」**——LLM 层失败，全部 suggestion `source=rule`；
- risk_warnings 提示「LLM 超时…结论仅供参考」——**降级诚实标注 ✅**；
- **专业投资者审阅发现**：
  - D-B1 **KDJ 超买却给 BUY/HOLD**：159338 J=101.67/K=84.77 → BUY；159516 J=110.97 → BUY；518880 J=104.51 → HOLD；159992 J=91.59 → HOLD——J>100 极端超买仍买入/持有信号，KDJ 超买钝化无处理；
  - D-B2 **holdings_analysis.action=None 与 suggestions 割裂**：holdings_analysis 10 条 confidence=high 但 action 全空，suggestions 才有 action——前端若读 holdings_analysis 显示无操作建议；
  - D-B3 **因子缺失 12/39（31%）**：全部标的 factor_availability=27/39，宏观/政策类因子部分缺失；
  - D-B4 **规则引擎只看动量忽略超卖**：159545 恒生红利低波 decrease（动量-1.71）但 KDJ.D=23.66 超卖；512000 券商 decrease（动量-0.69）但 RSI 47.82 中性——可能错杀超跌反弹品种（round18 D8 同源部分修复）；
  - D-B5 **suggestions 理由模板化**：4 条 increase 理由完全同模板（仅因子分数不同）——round18 D7 未修。

### 3.3 三市场行情分析（A/HK/US）

| 链路 | A | HK | US | 结论 |
|---|---|---|---|---|
| 个股分析 symbol-analysis | ✅ 64609B 高质量 | ❌ **DATA_UNAVAILABLE** | ✅ 65171B 高质量（技术指标空但诚实标注） | 港股断裂（见 §4-4） |
| 综合研判 llm-report | ✅ 54037B 高质量 | — | — | 市态/数据准确 |
| AI 投顾 llm-advice | ✅ 36233B | — | — | 三档组合权重加总 100% |
| 板块分析 sector-analysis | ✅ 59567B（BK1600） | — | — | 数据精确 |
| 概念分析 | ✅ 68221B（BK0899 CRO） | — | — | 同板块 |
| 搜索自动补全 | ✅ 芯片→30条 | ✅ 腾讯→命中 | —（未测，A/HK 已覆盖） | 正常 |

**内容质量审阅（专业投资者视角）**：
- A 股 symbol-analysis（159338）：结构完整（基本面/技术/资讯/风险/操作五段）、技术指标解读准确（KDJ J=101.7 标超买、MACD 底背离金叉）、**PE/PB 缺失诚实披露**「无法完成估值分位判断」、操作建议具体（1.266/1.240/1.223 价位）——**高质量**；
- 美股 symbol-analysis（AAPL）：财报数据准确（营收 1094 亿 +16%/净利 297.9 亿 +27%/毛利 50.1%）、**诚实标注「技术指标为空、历史K线无，仅依据实时行情」**、多空面均衡、风险 7 条——**高质量但数据完整性受限**（US K线缺失，见 §4-5）；
- 综合研判：市态判断准确（range_bound 横盘消化）、数据真实（上证 3960.54 +0.35%/成交 1.5 万亿/情绪 34.8）、**但当日最强主线医药板块完全未提及**（只讲科技成长）——与 D-A3 呼应；
- AI 投顾：三档组合权重加总正确（100%）、调仓规则具体；**但与设计方案标的池不一致**（投顾用沪深300/医疗ETF，设计用中证A500/红利低波）——三套 LLM 系统（设计/投顾/板块）使用不同 ETF 标的池，建议碎片化；
- 港股 symbol-analysis 失败根因：`/market/history/00700?asset_type=HK` 返回 `[]`、`/market/indicators/00700` 返回 `{"data_available":false,"reason":"K线数据不足(<30交易日)或数据源缺失"}`——**港股历史K线在容器内完全缺失**（yfinance 港股/东财港股历史接口容器网络失败），实时好但历史空 → F7 规则「数据全空不调 LLM」→ DATA_UNAVAILABLE。

### 3.4 热点板块/个股（任务 4）

- **hot-plates ✅**：24866 字节，医药生物（+7.27% 领涨）、算力工程、超级电容、IDC 电源、芯片产业、机器人等板块 + lead_stocks（secu_code/name/change/up_reason/up_tags）；
- **sectors/heat ✅**（交易时段）：电子 BK1201 +0.87%、半导体 BK1036 +1.23%、医药生物 BK1216 +3.06%，degraded=false（round18 冷却期 degraded=true 的 16/20 涨跌幅为 0 问题交易时段消失）；
- **stock-hot-rank A ✅**（真实个股）；**US ❌**（2 字节空，round18 P1-3 未修，东财美股 spot 冷却，验证窗口：美股盘中）。

### 3.5 自选功能（任务 5）

- GET ✅ 18 只（A/HK/US/ETF）；POST 添加 159338 ✅（id=23）；
- **港股(09988/00700/01398/00981)/美股(QQQ/AAPL/SPY)自选 realtime 全部 `_degraded:true`**：market.py:742-755（P1-2 round17）批量实时调用失败（twelvedata 429）→ 该市场整体跳过 per-item 直接 DB-only → realtime=null + _degraded=true；
- **前端 WatchlistPanel.vue:127-134 用 `v-if="item.realtime"` / `v-else` 显示「行情加载中（数据源弱）」**——永久降级被误标为「加载中」，用户永远看到「加载中」以为网络慢（静默降级假完成）；
- 新增自选 159338 realtime=null（代码注释 line 322-323 承认需手动刷新）。

### 3.6 持仓技术分析与综合信号（任务 6）

- `/market/signal/159338` 返回 `{"signal":"buy","score":1.5,"reasons":["MACD偏多","MA5>MA20多头排列"]}`——**但 KDJ.J=101.67 超买仍给 buy**（与 D-B1 同源）；
- 11 只持仓 signal 全部 data_available=true（含黄金 518880 hold）；
- **round18 D6 KDJ 显示错配已修复**：check_417 factor_summary 显示原始值（KDJ.K 84.77/J 101.67），非归一化负值——P0-3 ✅。

### 3.7 资讯页面（任务 7）

- 21 条 headlines，content 全有，level 分布 1-5 合理；
- **ai_summary 仅 5/21 非空（16 条缺智能分析）**，且**前端 NewsView.vue 完全不读取 ai_summary 字段**（列表只渲染 level 映射的 stars + title + content；AI 分析改为点击触发 news-impact 实时调用 LLM）——**后端 ai_summary 预生成管线是前端不消费的冗余管线**；
- **新鲜度维度前端不可见**：后端 stars 为独立「新鲜度」维度（news_fetcher.py:226-259 `_compute_stars`，round9 P2-1：<1h→5★/<6h→4★/<24h→3★/<72h→2★，时间不可解析回退 level）——本轮 21 条全为 4-5 星（资讯均 <6h）**符合设计**；但**前端 NewsView.vue 用 `mapNewsLevel(level).stars` 由 level 映射显示星星，未消费后端 stars 字段**——新鲜度维度在前端不可见，用户看到的星数是 level 派生值（非真实新鲜度）；
- news-impact 智能分析：需点击触发，round18 验证质量好（本轮未重复验证）。

### 3.8 因子模型（任务 8）

- factors/active：total=38，**valid=10 / warn=15 / static=11 / no_data=2，avg_ic=-0.1109**——28/38 非 valid（warn15+static11+no_data2）；
- round18 P0-4 已修复：status 接 DB IC 样本计数（valid/warn/no_data/static + reason + sample_count），本次 valid=10（round18 非交易时段 valid=9→0 波动问题已解决）；
- **static 11 个因子**（未实时计算）+ warn 15 个 → 因子数据完整性不足，与 D-B3（factor_availability 27/39）同源。

---

## 四、前后端数据断裂排查（任务 9）

| # | 断裂点 | 后端行为 | 前端行为 | 根因（file:line） | 级别 |
|---|---|---|---|---|---|
| F-1 | 港股/美股自选 realtime 降级误标 | realtime=null + `_degraded:true` | WatchlistPanel.vue:127-134 v-else 显示「行情加载中（数据源弱）」——**永久降级被误标加载中** | market.py:742-755 批量失败整体跳过 per-item（twelvedata 429）；前端不消费 _degraded | **P0** |
| F-2 | news ai_summary 双端断裂 | ai_summary 16/21 空 | NewsView.vue 不读取 ai_summary（列表只渲染 level/title/content） | 后端预生成管线冗余；前端改走 news-impact 点击触发 | P1 |
| F-3 | 资讯新鲜度维度前端不可见 | 后端 stars 为新鲜度（<1h=5★，round9 P2-1 设计），21 条全 4-5 星符合设计；**前端 mapNewsLevel(level).stars 由 level 映射显示，未消费后端 stars** | 用户看到的星数是 level 派生值，新鲜度维度失效 | 前端消费后端 stars（新鲜度）或删除 stars 字段（治理项，见 P2-3） | P2 |
| F-4 | 港股 symbol-analysis DATA_UNAVAILABLE | history 返回 []、indicators data_available=false | 前端显示错误提示 | 港股历史K线容器内缺失（yfinance/东财港股历史失败），F7「数据全空不调 LLM」 | **P0** |
| F-5 | 美股 K 线缺失 | history 空（AAPL 技术指标/历史K线无） | 美股 symbol-analysis 仅基于实时行情（LLM 诚实标注） | US K线主源 akshare 被 EM 风控 + 降级链限流（round19 问题9 已备 TickFlow 方案未对 US 生效验证） | P1 |
| F-6 | 新增自选实时为 null | POST 添加后 realtime=null | 需手动刷新（代码注释承认） | market.py 添加路径无实时回填 | P2 |

> **前端 API 层核对**：`frontend/src/api/index.js` 端点路径与后端全部匹配（/market/watchlist、/market/hot-plates 等），**断裂在后端数据层与前端渲染层，非路径不匹配**。

---

## 五、round18/round19 落地核对（任务 10）

### 5.1 round18 修复项核对

| 项 | 声称修复 | 本轮验证 | 结论 |
|---|---|---|---|
| P0-1 timeline 热态 ≤300ms | 30s TTL 缓存 + 列裁剪 + limit | **热态 2815-2974ms**——列裁剪生效（portfolio.py:550-553 只查 5 列），**无 TTL 缓存/limit/分页**（portfolio.py:529-583 全表查询无缓存） | ❌ **只修一半** |
| P0-2 metrics 热态 ≤300ms | 30s TTL 缓存 | 热态 43ms | ✅ |
| P0-3 KDJ 显示错配 | factor_summary 用原始值 | check_417 KDJ.K 84.77/J 101.67（原始 0-100） | ✅ |
| P0-4 factors/active DB IC | status 接 DB 样本计数 | valid10/warn15/no_data2/static11+avg_ic | ✅ |
| P1-2 sectors/heat 冷却期降级 | 交易时段复测 | 交易时段 degraded=false，医药 +3.06% | ✅（待交易时段全窗口复测） |
| P1-3 US stock-hot-rank | 备源 | 仍空（2 字节） | ❌ |
| P1-4 design etfs price | realtime fallback | design 525 price=4.771 非空 | ✅ |
| P2-1 fetch_history 归一化 | etf/fund→A | sz301308+asset_type=A 返回 23049B | ✅ |
| D1 多因子评分超 0~1 | 注释修正 | 511090=-2.31 仍超 | ❌ |
| D4 510050 单只 20% | 风控上限 | 防御型 510050=20.34% 仍复现 | ❌（合规但集中） |
| D7 模板化 reason | 措辞与数据匹配 | increase 4 条同模板 | ❌ |
| D9 confidence 固定 0.7 | 按填充率分级 | check_417 全部 0.7 | ❌ |

### 5.2 round19 落地核对（含用户补充「方案内标的相关联度」专项审阅）

| 项 | 声称实施 | 本轮验证 | 结论 |
|---|---|---|---|
| P1 correlation.py 引擎 | matrix/median/high-pairs | 实测 r(510300,159338)=**0.983**（与 round19 文档一致）；median_correlation_for 工作 | ✅ |
| P1 同指数去重 _dedup_same_index | allocation_engine:620 | 存在；裸 A500/A50 补漏（:137-138/:184-185） | ✅ |
| P1 低相关措辞接线 | build_rationale correlation_median | **实测 511090 median=0.168<0.3 但 rationale 无「低相关」措辞**——rationale.py:108 用 symbol hash 在短语池随机选句，「低相关」句不保证被选中 | ⚠️ 接线生效但**不保证出现** |
| P1 高相关对权重约束 max_correlation | risk_controls.py:31 生效 | **零消费**（仅定义处）——方案内高相关宽基不受约束 | ❌ |
| **用户补充：方案内标的相关联度** | — | task 419（design 527）三套方案完整关联度矩阵（60 日收益率 Pearson r，26 只标的全部 240 根 K 线可用，`logs/round20/corr_audit_out.txt`）：**defensive** 14只 平均r=0.368/最大0.983——核心层 510300+159338+510050 两两 r=0.822~0.983 合计 **29.7%**，r>0.9 对 2 个（159570+513120 港股医药双持有 5.9%）；**balanced** 15只 平均r=0.303/最大0.983——5 只宽基集群（510300/159338/159915/510500/588000）8/10 对 r≥0.85 合计 **43.1%**（round19 design 519 实测 43% 完全复现），r>0.9 对 4 个合计权重 58.1%；**aggressive** 8只 平均r=0.198/最大0.983——3 只宽基两两 r=0.916~0.983 合计 **31.2%**，r>0.9 对 3 个合计权重 62.4%；三套方案真低相关资产（median<0.3：512890 红利低波 r≈0/511090 国债 r≈0.16/518880 黄金 r≈0.26/588200 科创芯片 r≈0.06）单只权重仅 3-4%（defensive 512890 15%、aggressive 512890 9.7%/588200 9.7% 除外） | ❌ **round19 design 519 问题在 task 419 三套方案全部复现，且无任何关联度约束/警示** |

**关联度专项审阅结论（专业投资者视角）**：系统已具备真实相关度计算能力（引擎+数据源均正常，26 只标的 240 根 K 线全可用），但**方案生成未应用关联度约束**——① 核心层宽基高相关集群（r 0.82~0.98）在三套方案中系统性存在且权重 29.7%~43.1%，「核心层分散」实为「同一 A 股 beta 的多个切片」；② balanced/aggressive 的 r>0.9 高相关对合计权重 58%~62%，**超过一半风险押注单一 beta 方向**；③ 真低相关资产（红利低波/国债/黄金/科创芯片）单只权重多数仅 3-4%，分散贡献有限（defensive 512890 15%、aggressive 512890/588200 9.7% 除外）；④ 同质化双持有无约束（港股医药 159570+513120 r=0.97、美股宽基 159941+513500 r=0.864、恒生科技+中概互联 r=0.899）；⑤ 报告无任何高相关对警示，低相关措辞因 hash 随机不出现；⑥ **防御层归属错配（D-A7）**：159941 纳指 median_r=0.457 为防御层**跨市场标的中最高**（全层排第 5）、513500 标普 0.377，却与真对冲资产（国债 0.168/黄金 0.293）同置防御层并被文案称「避险资产」——「跨市场」被误当「低相关对冲」。根因：max_correlation 约束未实施（risk_controls.py:31 reserve 零消费，round19 方案 2.2 只设计未落地）+ 低相关措辞 hash 随机选取 + 防御层按跨境类别硬编码筛选。**结论：关联度不合理——「分散」声明与实际相关性脱节，方案风险集中度被高估的分散性掩盖，专业投资者不可接受**；修复见 P1-1（max_correlation 高相关对权重约束）+ P1-2（低相关措辞确定性）+ P2-5（防御层归属校验）。

---

## 六、测试防护盲区归因（任务 13）

| # | 本轮问题 | 测试为何未识别 | 修复方案 |
|---|---|---|---|
| T-1 | timeline 热态 2.9s | verify_e2e.py:630 阈值 **5.0s** 太宽；verify_perf.py timeline 阈值 1.0s 但**软门禁不阻断 commit**；P0-1 验收「≤300ms」从未作为硬门禁 | verify_perf timeline/metrics 改为硬门禁或至少 CI 阻断；verify_e2e 阈值 5.0→1.0s |
| T-2 | 港股/美股自选降级误标「加载中」 | 前端测试无 `_degraded` 渲染断言；verify_e2e watchlist 检查（line 1585-1598）只验后端 realtime=null 时 _degraded=true，不验前端 UI 状态 | 前端单测加「_degraded=true → 显示『行情暂不可用』非『加载中』」断言 |
| T-3 | news ai_summary 16/21 空 | verify_e2e news 只验 200/非空，无非空率断言 | 加「ai_summary 非空率 ≥ N」内容断言（或删除该管线） |
| T-4 | KDJ 超买给 BUY/HOLD | 策略检查测试无「超买不应 BUY」负向断言（round18 §5② 已指出未补） | 加负向断言：KDJ.J>100 时信号不得为 BUY |
| T-5 | 方案内高相关宽基集中 30% | max_correlation 零消费 + 无关联度约束测试 | 加「方案内高相关对合计权重 ≤ 阈值」断言（引擎已具备） |
| T-6 | correlation_median 措辞 hash 随机 | build_rationale 测试只测 None 分支，不测「低相关标的必出现措辞」 | 加断言：correlation_median<0.3 时 rationale 必含低相关措辞（改确定性选取） |
| T-7 | 死端点逃过 check_routes | check_routes 判定「api/index.js 有方法定义」即 OK，**不查组件调用** | check_routes 升级为「路由 → api 方法 → 组件调用」三层核对 |
| T-8 | LLM 429 限流下 verify_e2e 超时 | 设计检查等待 LLM 报告 2min 无输出 | verify_e2e 对 LLM 报告阶段加超时降级（报告部分失败不阻塞其余检查） |
| T-9 | **共性根因：修复不留痕** | round18/19 修复落地未同步补测试（P0-1 声称修复但无验收门禁；round19 落地无关联度断言） | 修复方案必须自带验收测试（对照 design-checklist D3 验证窗口） |

> 与 round18 §5 共性根因一致：测试强调「测试绿」但缺乏「显示值=指标源值」「性能门禁链路完整」「内容措辞与数据支持匹配」三层；**修复不留痕**是本轮最大盲区——round18 P0-1「声称修复」实际只做列裁剪，因无硬验收门禁而逃过。

---

## 七、冗余代码清理清单（任务 14）

### 7.1 后端死端点（round18 §6 清单，全部仍在，前端组件 0 引用）

| 模块 | 端点 | file:line |
|---|---|---|
| market | GET `/realtime`、`/realtime/batch`、`/realtime/{symbol}`（前端只调 realtimePortfolio）、`/signal/debug/{symbol}`、`/fundamentals/{symbol}`、`/sentiment`、`/sectors/industry`、`/sectors/concept`、`/sectors/industry-cls`、`/sectors/{code}/stocks`、`/sectors/{plate}/popular`、`/sectors/rotation`、`/sectors`、`/wind` | market.py:25/33/51/395/447/489/494/505/517/523/529/535/540/654 |
| portfolio | POST `/apply-strategy`、GET `/designs`、DELETE `/designs/{design_id}`、GET `/strategy-checks` | portfolio.py:102/186/322/460 |
| news | GET `/macro`、`/global`、`/stock/{symbol}`、`/research/{symbol}` | news.py:15/20/25/30 |
| analysis | POST `/news-impact/stream`（前端用非 stream 版） | analysis.py:725 |
| admin | GET `/sources/connection-pool`、`/thread-pool`、`/llm/health`、`/factor-health`、DELETE `/config/{key}`、GET `/metrics`（verify_e2e 依赖 metrics，**不能删，只性能优化**） | admin.py:104/119/132/145/216/231 |
| factors | GET `/model` | factors.py:171 |
| WS | `/ws/market/{symbol}`、`/ws/design-report/{session_id}`（前端 3 条 WS 均不连） | ws.py:85/127 |

> ⚠️ 删除任何端点须同步删 `api-contracts/` 契约段并跑 `check_routes.py`；verify_e2e 依赖项（metrics）删除前须确认调用方，只优化不删。

### 7.2 遗留文件

| 文件 | 来源 | 处理 |
|---|---|---|
| `data/_diag_*.py` ×20 | round8（2026-08-07）探针 | 归档到 `logs/round8/` 后删 |
| `scripts_diag_test_analysis.md`（根目录） | round18 P1 归档项 | 移到 `docs/archived/` |
| `start_backend_profiled.py`（根目录） | 历史诊断残留 | 确认无用后删 |
| `docker-compose.diag.yml` | 本轮诊断 override | **保留**（注明用途，本轮仍在用） |
| `logs/` 历史诊断产物（lh_*、backend_prof*.log、warmup_*.txt 等） | 多轮累积 | 按 round16 P2-7 惯例归档到 `logs/round20/` |
| 本轮诊断产物（logs/tmp/*.json/txt） | 本轮 | 归档到 `logs/round20/` 后清理 |

### 7.3 前端

- api/index.js 中与死端点对应的 api 方法（realtimeAll/sentiment 等）：若组件无调用则删；
- check_api_usage 显示前端 api 50/50 有调用点（无死方法）——**后端死端点对应 api 方法存在但组件不调用**，需 check_routes 升级后统一清理。

---

## 八、优化与修复方案（P0-P2 分级，本份不实施）

> 对照 design-checklist 关键项（证据链 D2 / 非兜底 / 真实调用点 / 复杂度审计 / 验证窗口 D3）：每方案标注证据链（file:line + 实测命令输出，见 §二/§三/§五 各节）、非兜底要求（验收含「非空/真实值」断言，P0-4/P1-5/P1-9 明确真实数据源）、真实调用点（timeline→DesignHistory、CLS→home Dashboard、自选→WatchlistPanel、港股K线→symbol-analysis、max_correlation→allocation_engine 分配后校验、ai_summary→news 管线、因子→factors/active、规则引擎→strategy_check_worker）、复杂度审计（每方案标注 I/O 与超时/缓存）、验证窗口（P0-4/P1-5/P1-9 标注交易时段）。

### P0 级（功能正确性/性能，必做）

**P0-1 timeline 补 TTL 缓存 + limit + 分页（性能 P0，round18 P0-1 剩余部分）**
- 证据：portfolio.py:529-583 全表查询（design/check/task 三表无 limit）+ 无缓存；实测 2815-2974ms 恒定；round18 P0-1 方案 ②③④ 项未实施；
- 修复：① 查询加 `limit(limit+1)` + 子查询分页（先查 id/created_at 再回表）；② `strategies_json`/`holdings_json` 等大字段 column defer（select 不含该列）；③ **30s TTL 内存缓存**（对齐 admin_metrics 模式，admin.py:258-285 已用）；④ check/task 表同样 limit 裁剪；
- 验收：`time curl /portfolio/timeline` 热态 ≤300ms；verify_perf timeline 阈值 1.0s 改为**硬门禁**（或 CI 阻断）；verify_e2e:630 阈值 5.0→1.0s；
- 复杂度：仅 DB 查询改造 + 内存缓存，无新增网络调用；缓存写一次读多次。

**P0-2 home CLS 0.389 修复（存量布局偏移）**
- 证据：Lighthouse 四页 CLS 0.001-0.021（非 home），home 恒 0.3885205676603475（round16/18/20 浮点级一致）——home 特有确定性布局偏移，非数据时序；
- 修复：浏览器 tracing（PerformanceObserver layout-shift）定位偏移元素（疑 Dashboard 顶部 strip/卡片 mount 后插入）；根因修复后加 Lighthouse CLS 断言（≤0.1）；
- 验收：home CLS ≤0.1；round14 P1-G「声称修复」必须有实测报告背书；
- 复杂度：纯前端 DOM 布局，无网络。

**P0-3 港股/美股自选降级状态修复（状态误标）**
- 证据：WatchlistPanel.vue:127-134 `v-else` 显示「行情加载中（数据源弱）」但后端 `_degraded:true` 永久降级；market.py:742-755 批量失败整体 skip；
- 修复：前端读取 `_degraded` 字段，降级时显示「行情暂不可用」+ 非「加载中」；后端 `_degraded` 语义保持；
- 验收：前端单测「_degraded=true → 显示『行情暂不可用』」负向断言；手动走查港股自选显示正确；
- 复杂度：前端条件渲染，无网络。

**P0-4 港股历史 K 线数据源补齐（港股分析链路修复）**
- 证据：`/market/history/00700?asset_type=HK` 返回 `[]`；`/market/indicators/00700` data_available=false；symbol-analysis DATA_UNAVAILABLE（F7 数据全空不调 LLM）；round19 问题 8/9 已实测 TickFlow `hk{sym}` 320 根可行（fetch_index_history 仅支持 A 股）；
- 修复：fetch_history/indicators 的 HK 分支接入 TickFlow（对齐 round19 问题 9 US 分支模式）或腾讯 hk{sym}（320 根实证）；HK 指数历史同样补齐（HSI/HSTECH 当前空）；
- 验收：`/market/history/00700?asset_type=HK` 返回 ≥30 根真实 K 线；`symbol-analysis` HK 不再 DATA_UNAVAILABLE；负向断言「HK history 空 → FAIL」；
- 验证窗口：交易时段 9:30-11:30/13:00-15:00 + 真实环境；非窗口结论打标「待交易时段复测」；
- 复杂度：新增数据源调用须 `asyncio.wait_for` 超时（对齐现有 5s）+ 缓存（300s K 线缓存已有）。

**P0-5 策略检查 LLM 超时优化（ReadTimeout 38s）**
- 证据：task 417 summary「LLM 生成超时(38s)未返回」；日志 opencode_zen 持续 429（每 2-3s 失败一次）+ deepseek 间歇 200；
- 修复：① LLM 调用超时 38s→15s（对齐 round15 P2 超时保护）；② opencode_zen 429 退避（429 时立即降级 deepseek，不再反复重试）；③ 失败降级保留（已诚实标注）；
- 验收：策略检查 LLM 阶段 ≤20s 内出结果或降级；降级标注不变；
- 复杂度：LLM 调用参数调整 + provider 选择逻辑，无新网络。

### P1 级（数据完整性/体验，随轮次排期）

**P1-1 max_correlation 高相关约束实施（round19 方案 2.2 落地 + 用户补充审阅修复）**
- 证据：risk_controls.py:31 `max_correlation=0.95` reserve 零消费；task 419（design 527）defensive 核心层 510300+159338+510050 两两 r=0.822~0.983 合计 **29.7%**（实测 corr_audit；design 525 因 510050 权重 20.34% 为 30.34%，同源问题）；
- 修复：allocation_engine 分配后校验——高相关对（r ≥ 0.9）合计权重 ≤ 阈值（如 25%）；同指数去重（_dedup_same_index 已有）基础上补跨名称高相关约束；超限时剔除低 factor_score 标的并在报告标注「关联度提示」；
- 验收：设计方案的「高相关对合计权重 ≤ 阈值」断言；task 419 式组合不再出现 30% 高相关核心层；负向断言「高相关对超限 → FAIL」；
- 复杂度：基于已有 correlation.py 引擎（无新数据源），分配后校验为纯计算。

**P1-2 correlation_median 措辞确定性选取（修复 hash 随机）**
- 证据：rationale.py:108 `idx = md5(sym) % len(pool)` 随机选句；实测 511090 median=0.168<0.3 但 rationale 无「低相关」措辞；
- 修复：低相关标的（median<0.3）强制插入「与组合低相关，有效平衡波动」措辞（覆盖 hash 选取）；或改为确定性匹配（低相关标的必命中低相关句）；
- 验收：build_rationale 单测「correlation_median=0.2 → rationale 必含低相关」；负向断言「低相关标的无措辞 → FAIL」；
- 复杂度：rationale.py 文案生成逻辑，无 I/O。

**P1-3 KDJ 超买信号修正（超买不 BUY）**
- 证据：check_417 159338 J=101.67→BUY、159516 J=110.97→BUY；signal 端点同源（D-B1）；
- 修复：KDJ.J>100（或 K/D>85）时综合信号不得为 BUY——降级为 HOLD/减仓提示，或标注「超买回落风险」；
- 验收：策略检查/signal 端点「KDJ.J>100 → 非 BUY」负向断言；
- 复杂度：信号合成逻辑（factor_registry / signal 生成），无 I/O。

**P1-4 news ai_summary 管线接通或删除（双端一致性）**
- 证据：news/headlines ai_summary 仅 5/21 非空；NewsView.vue 不读取（走 news-impact 点击触发）；
- 修复（二选一）：① 前端改消费 ai_summary（列表内联展示）且后端补全生成；② 删除后端 ai_summary 预生成管线（避免冗余）+ 保留 news-impact 点击触发；
- 验收：二选一落地后「ai_summary 或 news-impact 至少一条链路可消费」；无「生成但不消费」冗余；
- 复杂度：取决于选择，前端渲染或后端管线删除。

**P1-5 US K 线数据源补齐（覆盖 F-5 + round18 P1-3）**
- 证据：US history 空（AAPL 技术指标/历史K线无，symbol-analysis 仅基于实时行情）；`stock-hot-rank?market=US` 空（东财美股 spot 冷却）；round19 问题 9 已实证 TickFlow `AAPL.US`/`SPY.US` 各 500 根（含当日收盘）可作 US K 线主修；
- 修复：① fetch_history US 分支接 TickFlow（对齐 round19 问题 9 已实施路径，若未对 US 生效则补验证）；② stock-hot-rank US 备源（新浪 levistock 美股 spot 降级链，round19 已实证）；
- 验收：`/market/history/AAPL?asset_type=US` 返回 ≥30 根真实 K 线；美股盘中 `stock-hot-rank?market=US` 非空；数据源守卫「US K线空/hot rank ≤ N → WARN」；
- 验证窗口：美股交易时段（盘中/盘后）；非窗口结论打标「待交易时段复测」；
- 复杂度：新增数据源调用须 `asyncio.wait_for` 超时 + 300s K 线缓存复用。

**P1-6 技术指标与信号一致性修正（覆盖 D-A1 超卖给进攻、D-B1 超买给 BUY、D-B4 超卖错杀）**
- 证据：588200 RSI 23.8（超卖）给「综合信号偏多+进攻性强」；check_417 159338 J=101.67/159516 J=110.97（超买）给 BUY；159545 KDJ.D=23.66（超卖）被规则 decrease（只看动量）；
- 修复：① 综合信号合成加入 RSI/KDJ 超买超卖守卫——超买（KDJ.J>100 或 RSI>80）不得 BUY、超卖（RSI<30）不因动量负而裸 decrease；② 规则引擎 reason 融合超买超卖提示；
- 验收：负向断言「KDJ.J>100 → 非 BUY」「RSI>80 → 非 BUY」「RSI<30 且动量负 → decrease 理由含超卖提示」；
- 复杂度：信号合成/规则引擎纯逻辑，无 I/O。

**P1-7 候选池与强势板块联动（覆盖 D-A3，含引擎侧 c2_bonus 动态化——用户新发现问题）**
- 证据：BK1600 医疗研发外包 +7.27%（29:0 普涨）当日最强主线，但方案仅低配港股创新药（159570 -0.95%/513120 -0.78%）；sector_momentum 数据已进 market_context（design 416 实测含板块榜）但未参与候选池筛选；**且引擎侧 c2_bonus 的板块奖励是硬编码科技关键词**（allocation_engine.py:373-374 `_RISKY_THEMES`=科创/半导体/新能源/军工/芯片/AI…**不含医药/CRO/创新药/消费**，:401-402 只对科技 +1.5）——**当日强势的医药板块即使进候选池，aggressive 引擎也无奖励 + 被跨层 -1.5 惩罚（defensive 已用 159570/512170/513120）→ composite ≤-0.3 过滤（:438）→ 入选不了**（实测 task 419 aggressive 卫星层只剩 588200 科技 1 只，医药 3 只在 defensive 有、aggressive 全部消失）；
- 修复（两层）：
  - **池层**：设计管线将当日 sector_momentum 前 N 板块映射到 ETF 候选池，强势板块主题 ETF（如创新药/医疗/CRO ETF）纳入候选；或至少报告「当日强势板块 vs 候选池覆盖」对照；
  - **引擎层**：`c2_bonus` 板块奖励由「名称关键词静态列表」升级为「基于 sector_momentum 的当日强势板块动态奖励」——进攻型对当日涨幅前 N 板块的对应 ETF 给予 +1.5（替代/叠加 `_RISKY_THEMES`），医药/CRO 当日 +7% 应获奖励而非 0；与 P2-6 方案 A（跨层惩罚层内化）配套——方案 A 解决"非科技被惩罚排挤"，本项解决"非科技无奖励"；
- 验收：强势板块（涨幅前 3 行业）在候选池有 ≥1 只对应 ETF（负向断言「强势板块无对应候选 → WARN」）；**引擎侧**：当日强势板块（如医药 +7%）对应 ETF 在 aggressive 卫星层可入选（负向断言「强势板块 ETF composite 被 -0.3 过滤且无强势奖励 → FAIL」——**注意：该引擎层验收依赖 P2-6 方案 A（跨层惩罚层内化）先行，若 P1 批次先于 P2 批次单独落地，需先实现方案 A 或将该断言标记为「待方案 A 落地后生效」**）；
- 复杂度：sector→ETF 映射表（可复用 etf_index_mapping.json 思路）+ sector_momentum 传入 engine（market_context 已有数据），设计冷路径，不阻塞主链路。

**P1-8 规则引擎 reason 与数据支持匹配（覆盖 D-B5/D7 模板化、D-B2 holdings_analysis.action 割裂）**
- 证据：check_417 4 条 increase 理由完全同模板（仅因子分数不同）；holdings_analysis.action=None 与 suggestions 割裂（round18 D7/D9 未修）；
- 修复：① reason 按实际可用因子组装措辞（无基本面因子时不拼「基本面与动量共振」，改「因子评分+技术信号」）；② holdings_analysis 补 action/suggested_weight 字段（与 suggestions 同源）；③ confidence 按因子填充率分级（factor_availability<70% → medium，round18 P2-7）；
- 验收：负向断言「reason 含『基本面』但因子填充率<50% → FAIL」「holdings_analysis.action=None → FAIL」「factor<70% 仍 confidence=high → FAIL」；
- 复杂度：规则引擎文案/字段组装，无 I/O。

**P1-9 因子 valid 率提升（static/warn 因子接入）**
- 证据：factors/active valid=10/warn=15/static=11/no_data=2（28/38 非 valid）；factor_availability 27/39（D-B3）；
- 修复：static 11 个因子接入 IC 计算（如有数据源）或标注「设计为静态」；warn 因子补数据源；
- 验收：valid 率 ≥ 60%；「因子缺失 ≥ 阈值 → 方案标注数据完整性降级」；
- 验证窗口：因子数据源（两融/政策/情绪）外部源，接入须交易时段 + 真实环境验证；非窗口结论打标「待交易时段复测」；
- 复杂度：因子数据源逐个接入，须评估各因子数据源可行性（探针前置 D1）。

### P2 级（治理/清理/契约）

**P2-1 死端点清理（§7.1 清单）**
- 前置：check_routes 升级为「路由→api→组件」三层核对（T-7）后，删 §7.1 死端点 + 同步 api-contracts + 跑 check_routes；
- 验收：删除后 check_routes 无残留引用；verify_e2e 全 PASS。

**P2-2 遗留文件归档（§7.2 清单）**
- data/_diag_*.py → logs/round8/；scripts_diag_test_analysis.md → docs/archived/；start_backend_profiled.py 删除；本轮产物 → logs/round20/。

**P2-3 资讯新鲜度维度前端接通或删除（覆盖 F-3）**
- 证据：后端 stars 为新鲜度维度（news_fetcher.py:226-259，round9 P2-1），前端 NewsView.vue 用 level 映射显示星星未消费 stars；
- 修复（二选一）：① 前端改消费后端 stars（显示真实新鲜度：5★=<1h）——level 徽章与新鲜度星数并存；② 删除后端 stars 字段（避免生成不消费的冗余字段）；
- 验收：二选一落地后「stars 生成且前端消费」或「stars 已删除」；无「生成但不消费」冗余；
- 复杂度：前端渲染或后端字段删除，无 I/O。

**P2-4 多因子评分注释与数据一致（round18 D1）**
- 证据：design 525 511090=-2.31 超「0~1」注释；
- 修复：注释改为「因子综合分（可负可超 1，区别于技术信号）」或按实际分布截断；
- 验收：报告注释与数值范围一致断言。

**P2-5 方案结构合理性检查（覆盖 D-A2 负信号作防御层、D-A5 进攻型高现金、D-A7 防御层归属错配、D4 单只 20% 集中）**
- 证据：511090 综合信号 -0.50 仍作三套方案防御层；进攻型现金 33-34.4% 但创业板 20% 高权重；防御层混入高相关跨市场成长（159941 纳指 median_r=0.457/513500 标普 0.377，真对冲 国债 0.168/黄金 0.293）；防御型 510050 单只 20.34%（round18 D4 复现）；
- 修复：① 综合信号明显负面（≤-0.5）的标的不入防御层（或标注「负信号防御配置」理由）；② 风格定位与现金/权重自洽校验（进攻型现金 ≤20%）；③ **防御层归属按「低相关 + 低波动」校验**——跨市场成长资产（纳指/标普，median_r ≥0.35 或波动率高于组合中位）不得作防御层「避险资产」文案，归卫星/进攻层或改文案为「跨市场分散」；④ 单只权重接近 30% 上限时报告标注「集中度提示」；
- 验收：负向断言「信号 ≤-0.5 且 layer=defense 且 rationale 无负信号说明 → FAIL」「进攻型现金>20% → FAIL」「防御层标的 median_r≥0.35 且 rationale 含『避险/低相关』→ FAIL」；
- 复杂度：分配后校验纯逻辑，无 I/O。

**P2-6 进攻型卫星层 underfill 修复（覆盖 D-A6，用户选定方案 A）**
- 证据：D-A6 根因链——logs/backend.log 三次 `no non-tech candidates to reclaim → CASH underfill`；allocation_engine.py:401-402（aggressive c2_bonus +1.5 科技奖励）、:461/:490（tech_cap=budget×0.5 裁剪）、:406-407（`sym in penalize_symbols → composite -= 1.5`）、:778（`_penalize`=前序方案**全部层**已用）、:438（卫星负分 ≤-0.3 过滤）、:523-529（无回补转 CASH）；
- 修复（三选项，**方案 A 为用户选定主选**）：
  - **A. 跨方案重叠惩罚改为层内生效**：`_penalize` 按层拆分——core 层传 `_prev_core_used`（已有，:756/:907）、satellite 层传新增 `_prev_sat_used`、defense 层传新增 `_prev_def_used`（在循环末尾 :1159-1162 按层分类更新）；使 aggressive 卫星候选只被 balanced **卫星层**用过的标的惩罚，不再被 balanced core/defense 标的一并 -1.5 → 非科技替补（159928 消费/515880 通信等）不再被误伤清空，tech_cap 裁剪后回补有标可补；`_used_symbols_for_overlap` 保留（U11 :915 判断 core 全重叠仍依赖）；
  - B.（备选）进攻型 `tech_cap_ratio 0.5→0.75` 或「无非科技可回补时允许超配科技」——把被裁权重留在卫星层而非转 CASH；
  - C.（断言，与 A/B 并行）`satellite budget underfill` 触发即算引擎失败信号（WARN 已有，方案层加 FAIL 断言）；
- 验收：进攻型 satellite ≥2 只且现金 ≤20%；负向断言「satellite underfill → FAIL」（方案 C）；回归 test_satellite_min_count（round12 曾修"aggressive 卫星整层清空"，本修复须不破坏其保底 ≥2 语义）；
- 复杂度：方案 A 纯逻辑（集合拆分 + 按层传参），无 I/O 无网络；影响面 = engine 分配器（三方案顺序生成路径），须全量引擎测试回归。

---

## 九、实施顺序与验收口径

1. **P0-1**（timeline 性能）→ verify_perf timeline 改硬门禁 → 实测 ≤300ms；
2. **P0-2**（home CLS）→ Lighthouse CLS 断言 ≤0.1；
3. **P0-3**（自选降级状态）→ 前端负向断言；
4. **P0-4**（港股 K 线）→ history/indicators HK 非空 + symbol-analysis HK 通（交易时段复测）；
5. **P0-5**（LLM 超时）→ 策略检查 ≤20s 或降级；
6. **P1-1**（max_correlation）→ 方案高相关对断言（用户补充审阅收口）；
7. **P1-2~P1-9** 随轮次排期；
8. **P2-1~P2-6** 治理清理（P2-6 方案 A 为用户选定，随 P2 批次实施）。

> **验证窗口标注**：P0-4/P1-5/P1-9 涉及外部行情源（港股 K 线、美股 K 线、因子数据源），须交易时段 + 真实环境验证；非窗口结论打标「待交易时段复测」。P0-1/P0-2/P0-3/P0-5/P1-1/P1-2/P1-3/P1-4/P1-6/P1-7/P1-8/P2-x 无窗口限制。

---

## 十、专业投资者总评

1. **方案质量**：三套方案结构完整、层预算合规、真实数据匹配（涨跌幅/RSI/MACD 与行情一致），但**技术指标与信号矛盾**（超卖给进攻、超买给 BUY）、**候选池与强势板块脱节**（当日领涨医药未纳入）、**关联度约束缺失**（核心层 3 宽基 30% 高相关）、**进攻型卫星层塌缩**（卫星仅 1 只、现金 34.4% 被动膨胀，D-A6）、**防御层归属错配**（纳指 median_r 0.457 跨市场标的中最高却称「避险资产」，D-A7）——「分散」「进攻」「防御」三个声明均与实际不符；
2. **报告质量**：LLM 成功时（symbol-analysis/综合研判/板块分析）质量高、诚实标注数据缺失；失败时（策略检查 38s 超时）规则兜底诚实降级但模板化、无基本面支撑——**专业投资者可接受降级但不会接受模板化建议作为决策依据**；
3. **数据完整性**：港股/美股 K 线缺失是最大短板（港股分析链路断裂、美股分析降级）；因子 28/38 非 valid；news ai_summary 16/21 空——多处「有管道无数据」；
4. **总体判断**：功能链路完整、诚实降级体系成熟（加分项），但**「显示值与数据源一致性」「性能验收硬门禁」「内容措辞与数据支持匹配」「关联度约束」四层仍需补齐**——当前方案对专业投资者「可参考不可直接采纳」，达到可接受标准需落地 P0 全部 + P1-1/P1-3。
