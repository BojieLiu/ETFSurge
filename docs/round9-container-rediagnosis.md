# Round9 容器化全链路复诊断与优化方案

> 状态：**诊断完成 + 方案设计完成，未实施**（待 review 至实施标准后再落地）
> 日期：2026-08-07
> 范围：Docker prod 容器内全链路（构建/预热/设计/策略检查/行情分析/热点/自选/技术分析/资讯/因子/前端 Lighthouse/后端性能/测试防护）

---

## 0. 摘要

本轮在 **Docker prod 容器内**（docker-compose --profile prod，镜像烘焙）对 ETF Surge 全链路做复诊断，与历轮"宿主 Windows 本地运行"的验证环境形成对照。核心结论：

1. **容器化基础设施存在 5 个此前从未暴露的问题**（docker-compose.yml 无法解析、Dockerfile CMD 无法启动、容器内 IPv6 双栈失效、容器内东财 EM 数据源被 TLS 层拦截、mootdx 未配置），其中 EM 源被拦截导致**候选池为 0、A股个股搜索 0 命中、预热 37.4s 超阈值**——根因是历轮验证全部在宿主跑，**容器环境零测试覆盖**。
2. **round8 O 项核对**：25 项（O13/O14 编号保留缺口）中 12 项确认修复、2 项未复现（O3/O10）、4 项部分修复、**4 项未修复（O2 港股K线 / O4 个股搜索 / O6 IC淘汰 / O21 容器内双栈）+ O24 已修复（round9 §6.1-2：标的分析全挂回归 bug 已实施修复并实测出文）**、2 项未专项验证（O20/O27）。
3. **性能**：前端 Lighthouse 90/100/99 优秀（O8 达成）；后端 8 个端点 >1s，`/market/watchlist` **29.9s** 灾难级且无任何门禁拦截。
4. **报告质量**：组合设计可用但存在数据缺失仍入选、表格口径误差；**策略检查在 LLM 60s 超时后降级为全 hold 模板，专业投资者不可接受**。
5. **因子模型 no_data 专项（宿主复诊，2026-08-07 补充）**：用户截图指出的 **7 个因子"没数据"（6 no_data + 1 warn）根因全部代码级定位**——IOPV 三级降级链 4 处解析 bug（sina 字段双错位+接口无 IOPV、qq GBK 解码崩溃、em 字段不匹配、TTJ 兜底 tuple/dict 契约错）导致折溢价率必然 no_data；benchmark_close/shares_change_20d 依赖链脆弱；sentiment 三因子是宏观单值作截面因子的设计缺陷；vol_ratio 为真实弱 IC。详见 §6.5.1。
6. **设计报告涨跌与「数据源不可用」专项（宿主复诊，同日补充）**：涨跌幅与收盘对不上 = 报告无数据采集时刻标注（#427 生成于 11:58 盘中，收盘后对照必然错位，510050 报告 -0.23% vs 收盘 +1.22% 实证）；560600「数据源不可用」= **硬编码幽灵锚**——`MANDATORY_CODES` 写死的「中证A500ETF」锚实际对应医药白酒ETF/全源零成交/无此证券，真实 A500 应为 159338；另发现本地快照路径 bug 与因子/涨跌缓存口径不一致。详见 §4.3。
7. **策略检查复诊（同日补充）**：LLM 超时（#344 60s 兜底）归入 P0-5；**技术信号空**根因 = indicators 空 dict 时 `technical_signal={}` 兜底失效 + 规则引擎骨架无该字段；**行业数据空** = industry_map 依赖候选池（池空则全空）；**「因子数据 10/10 正常」假正常** = RSI 50/KDJ 50 缺数据默认值被计入 filled；**「组合为空」为历史孤立记录（#343 无 task），后端实测正常（手动触发 10 只持仓）**。详见 §4.4/§4.5。
8. **测试防护体系**存在 4 类系统性盲区（stream 端点零契约测试、预热门禁口径错误、watchlist 只查 DB 不调 API、容器环境零覆盖；本轮再添 **IOPV 链零单测、设计涨跌与策略检查完整性无断言**），本轮所有新问题均落在盲区内。

**方案**：P0×9（阻断）/ P1×16（数据完整性）/ P2×11（质量体验）/ P3×11（测试防护补强）共 **47 项**，均附验收标准，未实施。

---

## 1. 执行环境

- Docker Desktop (Windows) + docker-compose v2，prod profile 三容器（redis / backend / frontend-nginx）。
- backend: `python:3.14-slim` + uvicorn；frontend: node 24 构建 + nginx stable-alpine。
- 诊断注入：prod backend 追加 `PROFILE_WARMUP=1`（与 dev 对齐）以启用 WarmupProfiler（cProfile + pyinstrument）。
- 基线：`verify_e2e.py` 263/284 通过、21 项失败。

---

## 2. 容器化基础设施问题（C1-C6；其中 C1-C5 为 P0 级阻断/降级类，C6 次要——摘要/结论计数「5 个基础设施问题」即指 C1-C5）

### C1. docker-compose.yml 无法被 go-yaml 解析（dev/prod 双模式全挂）
- **现象**：`docker-compose --profile prod build` 报 `go-yaml load error at L61:C43: mapping values are not allowed in this context`。
- **根因**：round8 O21 把 backend-dev 的 command 改为 `uvicorn app.main:app --host :: ...`，裸 `::` 后跟空格触发 go-yaml 严格解析报错；整个 compose 文件无法加载。
- **影响**：dev 与 prod 全部无法编排（此前从未在 docker 跑过，故未暴露）。
- **处置**：command 改为 YAML list 形式（本轮已实施，见「附改动」C1）。

> 发现顺序说明：C1（compose 无法解析）在构建第一步即触发，**修复 C1 后**才观察到 C2（容器无法启动）与 C3（启动后端口不通）——三者递进暴露，本报告按根因类别排列而非发现时序。

### C2. backend 容器无法启动：Dockerfile CMD 退化为 shell form（C1 修复后暴露）
- **现象**：容器 `Restarting (127)`，日志 `/bin/sh: 1: [uvicorn,: not found`。
- **根因**：Dockerfile 末行 `CMD ["uvicorn", ...]  # O21 (round8): [::] 双栈监听` —— **exec-form JSON 数组后追加行内注释**，Docker 解析为非法 JSON 后按 shell form 执行 `[uvicorn,` 命令 → exit 127。
- **影响**：prod backend 无法启动（dev 因 compose command 覆盖未暴露）。
- **处置**：注释移到 CMD 上一行（本轮已实施）。

### C3. 容器内 uvicorn `--host ::` 只服务 IPv6 → Docker 端口映射全失效（O21 容器回归）
- **现象**：容器内 `[::1]:8000` 200、`127.0.0.1:8000` Connection refused；宿主 127.0.0.1:8000 / localhost:8000 全失败，nginx 502。
- **根因**：uvicorn 对 `--host ::` 在 Linux 容器内显式设置 `IPV6_V6ONLY` → 仅 IPv6 监听；Docker Desktop 端口映射走 IPv4 转发 → 全部失效。O21 在 Windows 本地跑通（Windows 的 AF_INET6 默认双栈），容器内从未验证。
- **影响**：O21 方案"uvicorn 监听 [::]:8000"在容器场景不可用（且连基础启动都不行）。
- **处置**：容器内改 `--host 0.0.0.0`（Docker 端口映射无 IPv6 回退问题，O21 意图仅本地需要；本轮已实施）。

### C4. 容器内东方财富 EM 数据源被 TLS 层拦截（本轮最大环境性发现）
- **现象**：
  - 容器内 urllib/akshare 访问 `push2.eastmoney.com`（http/https）均 `RemoteDisconnected`，**宿主同一代码同一 UA 正常返回 1640 条**；
  - baidu/qq/tencent 等外网从容器内访问正常 → 非全外网受限，指向 EM CDN/WAF 按 TLS 指纹拦截容器出口流量；
  - 后果链：akshare EM 系接口（`fund_etf_spot_em`/`stock_zh_a_spot_em`/`stock_hk_spot_em`/`stock_us_spot_em`/`fund_open_fund_info_em`）全挂 → **候选池 0、ETF 数据质量 1 条、instruments A股个股段同步超时、A股/美股名称搜索 0 命中**。
- **影响**：容器内行情数据管道大面积降级；宿主验证全绿的场景在容器内系统性失败。
- **候选对策**（见 §12）：容器内为 akshare 换 TLS 指纹客户端（curl_cffi）；或调低 EM 优先级、把 mootdx/Sina/腾讯降级链补成主链；或容器出口走宿主代理。

### C5. mootdx 未配置且 health 探针误报
- **现象**：启动日志 `mootdx ERROR: 请手动运行 python -m mootdx bestip`（TDX 服务器未配置）；但 `/admin/sources/health` 显示 mootdx `available=true, failures=0`。
- **根因**：source_health 探针只测连接池/配置存在性，不实测数据拉取；mootdx 无 bestip 配置时探针依然报可用。
- **影响**：A股实时降级链第一环（mootdx）空转，浪费每次调用 1-2s；探针信息误导排障。

### C6. 镜像烘焙携带历史日志（次要）
- `backend/logs/backend.log.1-5`（各 ~10MB）被 COPY 进镜像，与 `./data` 挂载不同，logs 目录未挂载 → 预热 profiler 产物留在容器内需 docker cp 才能取（诊断路径缺陷）。

---

## 3. 预热性能诊断（PROFILE_WARMUP=1）

### 3.1 数据
| 指标 | 值 | 判定 |
|---|---|---|
| 墙钟启动→预热完成 | **37.4s** | 超 30s 阈值（日志告警 `Warmup took 37.4s (threshold 30s)`） |
| profiler 标注段合计 | 12.6s（market_cache 12.46s 占大头） | 覆盖缺口 ~25s |
| 未标注耗时段 | instruments 同步 A股段 30s TIMEOUT、IC 持久化首轮 19s | 未纳入任何计时 |

### 3.2 cProfile 热点（37.3s 采样）
- `requests`/akshare 网络 I/O 累计 **54.5s**（含重试）：`fund_etf_spot_em` 23.9s（分页 8 次）、`fund_open_fund_info_em` 12.2s（10 次）、`stock_zh_a_spot_em` 6.6s、`stock_us_spot_em` 5.4s —— **全部是被 EM 源拦截后的空等重试**（C4 直接后果）；
- 线程锁等待 38.2s（run_sync 并发排队）、SSL 握手/读异常 14s（连接被拒后的特征）。

### 3.3 结论
预热超时的**主因不是代码逻辑，而是容器内 EM 源被拦后的超时重试**；次要原因是 mootdx 空转与 instruments 同步无段级超时。宿主环境预热正常（此前 R7/R8 已优化至 12s 内）。

---

## 4. 组合设计与策略检查质量审阅（专业投资者视角）

### 4.1 组合设计（design #426，balanced / 50 万 / A 股）
**产出**：防御 10 只 / 平衡 13 只 / 进攻 12 只（含现金），报告 8917 字，report_quality=full。

**通过项**：
- O18 已修复：510050 报 -0.23%（复诊基线 -23.40%）、518880 -0.11%（-10.70%）；全部 29 个涨跌样本在 ±10% 内；
- 三层结构（核心/卫星/防御）+ 现金比例清晰，震荡市分批建仓/止损/再平衡纪律有量化标准；
- M7/P1-1/P1-2 门禁通过（核心含宽基锚、卫星无宽基、核心层重叠 ≤1）；
- O15 修复：562950 标注"电子方向"。

**问题项（数据完整性）**：
1. **560600 中证A500ETF "今日涨跌：数据源不可用"仍以 6% 权重入三套方案核心层**——数据缺失标的入选核心宽基，专业不可接受（应降级或剔除，标注原因）；
2. 平衡型表格"核心 50%/卫星 24%/防御 11%" vs 实际权重 52%/22%/12%——1-2% 口径误差（防御 11% vs 12% 明显是笔误级）；
3. 顶层 `market_regime=None` 而 `market_context.market_regime=range_bound`——接口字段断裂（前端若读顶层字段将显示空）；
4. "多因子评分（0~1）"注释与数据矛盾（实际 ±5 范围值）——误导读者。

**问题项（投资逻辑）**：
5. 进攻型现金 38% 却标 16% 预期年化——62% 仓位要兑现 16% 需要权益部分 ~26% 年化，弹性假设激进；报告解释"留弹药"可自洽但应披露假设；
6. 防御型卫星含证券 ETF 12%（高贝塔），与"防御"定位张力大，应有风控说明。

> **方案归口**：问题 1→P0-8（幽灵锚清点）/P1-5（数据缺失不入核心）；问题 3→P1-6（顶层 market_regime 补字段）；问题 2（表格口径误差）与问题 4（评分注释 0~1 vs ±5）→ 随 P0-9（报告数据时间戳/来源标注）一并修正报告模板口径；问题 5/6（投资假设披露类）记录在案，方案轮未单列条目——实施报告模板时并入假设披露段。

### 4.2 场内策略检查（check #342，portfolio_type=on_exchange）
**通过项**：
- `portfolio_type=on_exchange` 过滤正确：DB 20 条持仓（10 场内 + 10 场外）只检查 10 只场内标的；
- 兜底机制诚实：summary 明示"LLM 分析超时（60s 未返回，已用规则引擎兜底）"。

**问题项（专业不可接受）**：
1. **LLM 60s 超时 → 规则引擎兜底 → 10 只持仓全部 hold、理由为同一句模板、confidence 固定 0.7**——零增量信息，无法支撑"策略检查"价值主张；且与技术分析接口的信号（510880/513010/159869=buy、159545/512000=sell）直接矛盾；
2. 因子分全部挤在 20-22（中性区间），区分度不足（与 §6.4 因子模型负 IC 问题同源）；
3. 行业集中度检查因"数据源未覆盖 63% 权重标的"降级为空提示——容器内 EM 源被拦的直接后果；
4. `StrategyCheckRecord` 持久化**未写 portfolio_type 字段**（模型有列），详情接口返回 None。

**结论**：当前容器环境下，策略检查对专业投资者**不具可用性**；修复优先级 = LLM 超时（90s 对齐）> 模板化 hold 文案（个性化建议）> 行业数据完整性。

### 4.3 设计报告涨跌幅与「数据源不可用」专项诊断（宿主复诊，2026-08-07 补充）

触发：用户对比设计全文报告与今日收盘——涨跌幅大面积对不上（抽样 16 只几乎全部不同、4 只方向相反：510050 报告 -0.23% vs 收盘 +1.22%、562870 -0.43% vs +0.11%、518880 -0.11% vs +1.10%、562990 -0.31% vs +1.02%），且 560600 显示「数据源不可用」。

**(A) 涨跌幅对不上 = 报告无「数据采集时刻」标注**
- 报告「今日涨跌」列 = **设计生成时刻**（#427 创建于 2026-08-07 11:58，容器内）采集的行情值；K 线实证 510050 08-06 close=3.029 → 08-07 close=3.066 = **+1.22%** 与实时一致——报告里的 -0.23% 是**上午盘中值**，下午翻红；其余标的同理（盘中 vs 收盘的正常差异）；
- 缺陷定性：数据本身当时正确，但**表格无时间戳**（如「截至 11:30」），「今日涨跌」被误读为最新收盘；且 #427 在容器内生成（EM 被拦，C4），涨跌来自降级源（新浪/腾讯），与宿主实时口径/时刻不同——**同一报告不可与收盘数据直接对照**。

**(B) 560600「数据源不可用」= 硬编码幽灵锚（代码写错，全链路实证）**
- 560600 是 **`MANDATORY_CODES` / `_COMMON_ANCHOR_SYMBOLS` 硬编码的「中证A500ETF」强制锚**（allocation_engine.py / market_data_hub.py，名称写死、跟踪指数写死 sh000510），经 R5-0-1「截断后强制标的二次校验」机制**永远注入核心层**（日志「re-inject mandatory 560600 -> core」实证）；
- 但 560600 在**全部行情源身份错配**：腾讯/新浪 = **「医药白酒ETF」** 且今日**零成交**（量=0，价=昨收 0.691，无有效涨跌）；EM push2 = `rc:100 data:null`（无此证券）；快照（1618 只）/ portfolio_etfs / instruments **均无 560600**；
- 真实中证A500ETF = **159338**（腾讯「中证A500ETF华夏」正常成交、流动性好）/ 563650 / 560510 等——**560600 是历史写错的代码，一直沿用**；
- 后果：幽灵锚永远入核心 6%，涨跌三级注入链（pool → 快照 → K线）全失败 → 「数据源不可用」；而 factor_breakdown 齐全（RSI 60.4 / MACD 0.194）——因子分来自**错误标的（医药白酒ETF）的历史 K 线** → **560600 的因子/权重/入选理由整体是错标的的**，比「数据缺失」更严重；
- 附带 bug ①：本地快照兜底失效——`etf_scanner._etf_cache_file()` 解析到 `backend/app/data/`（`os.path.dirname(__file__)` 多带一层 app/，文件不存在）而非项目根 `data/`（容器 /app/data 分支正常）→ 宿主环境 `_snapshot_change_pct` 永远 None；
- 附带口径 ②：`_kline_change_pct` 用缓存 `get_kline_rows_any`（无 560600 → None）而因子计算用实时 `fetch_history`（有历史）——**因子分与涨跌可用性缓存口径不一致**。
- 备注：§4.1 的 #426（10:31）与本节的 #427（11:58）编号不同（非同一次生成），但 510050 两处报告均为 -0.23%——同容器内 pool 缓存时段内值一致（或盘中确实持平），不构成数据矛盾，仅提示报告值代表「生成时刻缓存」而非逐次实时拉取。

### 4.4 策略检查复诊：LLM 超时 / 行业数据空 / 技术信号空（2026-08-07 补充）

用户复现：策略检查出现 **LLM 超时、行业数据为空、技术信号为空**。DB 实证（container 12:00 前后三次检查）：

- **#344（12:00）**：summary=「LLM 分析超时（60s 未返回，已用规则引擎兜底）」；holdings 10 项 **`industry:""`（9/10 空）且无 `tech_signal` 字段**（前端信号列空白）；suggestions 全 hold 同模板（P0-5 已知）；risk_warnings 2 条（LLM 超时提示 + 行业缺失 63% 权重）；
- **#345（12:02，两分钟后）**：LLM 成功，但 **RSI(14)=50.00 / KDJ=50.00 全部为缺数据默认兜底值**、因子分 20-22 中性挤堆、`tech_signal:"hold"`（LLM 依据兜底信号生成）、industry 仅 518880 有「商品」——**「因子数据 10/10 正常」是假正常**。

**根因（portfolio_service.py / strategy_check_worker.py 逐行定位）**：
1. **技术信号空**：`technical_signal = sig if isinstance(sig, dict) else {"signal":"hold"}`（portfolio_service.py:701）——当 `indicators`（技术指标）为**空 dict** 时（`indicators.get(symbol, {})` 返回 `{}`，本身是 dict）兜底不触发 → `technical_signal={}` → 860-862 行「真实信号注入」`real_sig.get("signal")` 为空而跳过；规则引擎骨架 `_build_rule_fallback_holdings_analysis`（981-1023）**本身无 tech_signal 字段** → 前端渲染空白；
2. **行业数据空**：`industry_map` 从 `market_data_hub.get_pool()` / `get_by_code()` 构建（811-835）——候选池空（数据源弱/容器 EM 被拦）时 map 空 → `h.setdefault("industry")` 不生效；骨架 industry 依赖 `fb.technical_indicators.sector`（空）→ 9/10 空（518880「商品」为 LLM 生成，非数据）；
3. **假正常**：`filled_factor_count` 判定「任何非零值即 filled」（706-709）——RSI 50 / KDJ 50 缺数据默认值非 0 → 计为正常 → 报告「因子数据 10/10 正常」；
4. **LLM 超时**：#344 60s 超时（O25② 分级预算：all_empty 15s / partial 30s / 完整 60s），DeepSeek 偶发慢（两分钟后 #345 成功）；P0-5 已覆盖未实施。

### 4.5 「组合为空」专项（2026-08-07 补充）

用户手动点击「检查场内组合」→ 结果显示「组合为空」。**实证结论：当前后端正常，用户看到的是历史孤立记录，非新检查结果**：

1. **后端实证**：手动触发 `POST /portfolio/strategy-check-async {portfolio_type: on_exchange}` → task 255（66s）→ check #346：**holdings 10 只**、summary「LLM 分析超时（60s 未返回，已用规则引擎兜底）」——**无「组合为空」**；
2. **20:21 用户点击未创建任何任务**：DB tasks 表最新为 #254（12:01）、#255（本次手动触发 20:43）——用户点击时刻（20:21）**零任务落库**，前端请求未到达后端（或未发起）；
3. **「组合为空」来源 = #343（2026-08-07 11:23 容器内）孤立记录**：holdings_json=[] / suggestions_json=[] / risk_warnings=[]，summary=「组合为空」；**tasks 表无对应任务**（11:23 无 task，10:26-10:33 有 #341/#342，12:00 起 #344 恢复 10 只持仓）——前端历史/任务列表（localStorage 持久化 + timeline）展示该记录，用户点开后看到「组合为空」，误以为是刚触发的检查结果；
4. **「组合为空」的判定路径**（portfolio_service.py:636-637）：`etfs = await list_etfs(db, portfolio_type)`（is_active=True + portfolio_type 过滤，108-111 行）返回空 → 直接返回 `{"summary": "组合为空..."}`——**不记录查询条件/原因**，裸文案无诊断信息；#343 的空组合为 11:23 容器内瞬时状态（前后 40 分钟均有 10 只持仓），成因不可追溯（无 task params 留存）。

---

## 5. 行情分析功能测试（A股/港股/美股）

| 功能 | 端点 | 结果 |
|---|---|---|
| 综合研判 A/HK/US | POST /analysis/llm-report | ✅ 3 市场全部成功（报告含指数/板块/情绪上下文） |
| AI 投顾问答 | POST /analysis/llm-advice | ✅ 成功 |
| 板块分析 | POST /analysis/sector-analysis/stream | ✅ 成功（558 events，含行情快照注入） |
| 概念分析 | POST /analysis/sector-analysis/stream（与板块分析同一端点，以 `sector_type=concept` 区分） | ✅ 成功（686 events） |
| **个股/ETF/指数分析（A股/港股/美股）** | POST /analysis/symbol-analysis/stream | ❌ **全挂：STREAM_ERROR** `llm_complete_stream() got an unexpected keyword argument 'rate_limit_cap'` **（已修复，§6.1-2：删除 rate_limit_cap 透传，实测 5 类标的全出文）** |
| 搜索自动补全 | GET /market/search | ✅ A/510→30 条、HK/0070→1、US/AAP→1（A股个股名称/代码 0 命中，见 O4） |

**O24 回归 bug（本轮新增，P0）**：analysis.py:921-926 在 O24 实施时为 `agent.run_stream()` 透传 `max_retries=1, rate_limit_cap=10`，但 agent 底层调用 `llm_complete_stream()`（llm.py:415）签名**没有** `rate_limit_cap` 参数 → `/analysis/symbol-analysis/stream` 单一端点对**5 类标的**（A股个股/港股个股/美股个股/ETF/指数）全部 STREAM_ERROR，前端"🔍 标的分析"Tab 功能完全不可用。verify_e2e 的 section_analysis 只测 llm-report/advice，**不测 symbol-analysis/stream**，故回归零拦截。

---

## 6. 热点/自选/技术分析/资讯/因子验证

### 6.1 热点板块与个股
- hot-plates 11 条（医药/PCB/芯片产业链/AI应用…），含 `change`/`reason`/`lead_stocks` 完整字段（前端 hot tab 不消费 change，无断裂）；
- sectors/heat 20 条，change_pct 兜底 0（O19 修复确认，无 console TypeError）；
- stock-hot-rank 50 条真实数据（哈药股份 +9.97%、云南锗业 +10.0%），concept_tags 50/50 非空（O9 验收①通过）。
- ⚠️ 板块分析报告出现"**单日暴涨 13.03%**"（医疗研发外包 BK1600）——A股板块单日 13% 极可疑，O5 值域校验未覆盖板块数据（应加板块级 ±10% 校验）。

**2026-08-07 用户反馈专项（已实施）**：用户指出"板块热度涨跌幅全是 0 + AI 按钮报错 + AI 文案抽象"。处置：
1. **涨跌幅 0 → 东财板块行情回填（已实施）**：`sector_fetcher.fetch_em_sector_changes()`（新增）拉东财行业+概念板块 f3 涨跌幅（push2 → **push2delay 降级**——push2 对高频/大请求 RemoteDisconnected 限流，push2delay 稳定可用）；`sectors/heat` 端点按名称**三级匹配回填**（精确 → 包含 → `/` 分割首段，`_match_em_change`）；实测 20 板块 **8 个拿到真实涨跌幅**（CRO/CMO +10.84%、PCB +5.63%、创新药 +5.43%…），其余为东财无同名映射的财联社细分概念（铜箔/覆铜板、商业航天、氟化工等）保持 0 兜底不伪造；单测 8 用例（含三级匹配纯函数）全绿；
2. **AI 按钮报错 = O24 回归**（symbol 模式 `rate_limit_cap` 透传）——**已实施修复**：analysis.py:923-926 删除 `rate_limit_cap=10`（`llm_complete_stream` 签名无此参数 → TypeError → STREAM_ERROR）；runtime.py `run_stream` 透传白名单去掉该参数（双保险）；实测 5 类标的 symbol-analysis/stream 正常出文（42.8KB 无 STREAM_ERROR）；回归测试同步更新（原测试固化 bug 行为，断言 `rate_limit_cap` 透传——修正为新契约）；**O24 从"未修复"转为"已修复"**；
3. **AI 文案**（已实施）：`🤖 AI` → `🤖 AI 分析`（heat/symbol 两处按钮，与 title 一致，增强可读性）。

**港股热门/板块涨跌幅专项（同日补充，已实施）**：用户质疑"港股热门个股和板块热度涨跌幅不合理"。实证**确认异常 + 根因代码级定位**：

1. **根因：东财 clist/get 缺 `fltt=2&invt=2` 参数**——不带该参数时 f2（价格）/f3（涨跌幅）返回 **×100 整数**（盈富基金 f2=26160/f3=62 实为 **26.16 港元 / +0.62%**）；`hk_hot_fetcher._URL`（fs=m:128 港股全量）原样缺失 → 港股热门个股 price ×100、板块热度 change_pct ×100（软件服务显示 +296.7 实为 +2.97%、药品及生物科技 +758.38 实为 +7.58%）；
2. **修复**：①`_URL` 加 `&fltt=2&invt=2`（f2/f3 恢复正确语义）；②`_fetch_hk_rows` 加 **60s TTL 缓存 + last_ok 兜底**——板块/个股两端点各自触发 pz=5000 全量拉取，同分钟两次大请求必被东财限流（热门个股偶发 0 条），缓存共享 + 失败回退保证不空；③回归单测 `test_url_has_fltt2`（防 fltt 缺失再犯）；
3. **验证**：修复后港股热门个股 50 条（盈富基金 26.16/+0.62%、南方恒生科技 4.766/+0.68%）、板块热度 20 条（药品及生物科技 +7.58%、银行 -0.47%）——**全部合理**；函数层/路由层/API 三层实测一致。

### 6.2 自选功能
- 添加/列表/实时行情全部正常；**O22 修复确认**：sh688981 中芯国际 price=128.5 ✓；
- ⚠️ POST /watchlist 不传 name 时 instruments 补名未生效（新增条目 name=代码）——根因疑似 instruments 表 `market` 字段与请求 `asset_type='A'` 不匹配（O9 部分未修复）。

### 6.3 技术分析与综合信号
- 10 只场内持仓 indicators/signal 全部有数据；信号分布 buy 3 / sell 2 / hold 5（有区分度）；
- ⚠️ 与策略检查"全 hold 模板"直接矛盾（§4.2）；
- ⚠️ MACD 接口返回 30 个历史 histogram 数组（冗余 5-10KB/标的，批量时放大延迟）。

### 6.4 资讯页面
- 头条 18 条，**level 分布 {2:7, 3:1, 4:1, 5:9}——L5（最重要）占 50% 且无 L1**，分级明显失真；
- **stars 与 level 完全同分布**（2:7/3:1/4:1/5:9）——stars 无独立"新鲜度"信息维度；
- 新闻智能分析（llm-news-analysis）1921 字结构完整（情绪/支撑/压制/综合判断），但 **AI 引用"情绪指数 60"与系统 sentiment 37.8 不一致**——LLM 自估值与系统口径脱节，专业读者会困惑。

### 6.5 因子模型
- summary：valid=23 / warn=1 / **no_data=6** / static=3 / avg_ic=0.0151；
- O25 部分修复：no_data reason 已区分（etf 三因子"数据源未接入（缺 nav/benchmark_close/shares_change_20d）"、sentiment 三因子"截面无差异（常量输出）"）——不再笼统"IC 未累积"；但 **no_data 仍 6 项**（容器内 EM 源被拦为外部根因；宿主复诊见 §6.5.1：根因全部代码级定位，与容器 TLS 无关，宿主下折溢价率等仍 no_data）；
- **O6 未实施**：`/factors/ic` 端点返回的 28 条 IC 记录中 13 条为负（change_pct -0.449、bollinger.bandwidth -0.5661、atr_14 -0.4293、j_value -0.381…，口径：IC 端点仅收录已累积 IC 的因子，33 总数含 static/no_data），仍标 valid，且 reason 文案"IC -0.4490 ≥ 阈值 0.02"逻辑错误（负数不可能 ≥ 阈值，应取 |IC| 或显著性）。

### 6.5.1 因子模型 no_data 专项诊断（宿主环境，2026-08-07 补充）

触发：用户截图因子模型页——**7 个因子"没数据"**。API 实证构成：**6 个 no_data（etf 三因子 + sentiment 三因子，ic_value 全 null）+ 1 个 warn（vol_ratio，IC=0.001 接近 0，avg_ic 亦 null）**——前端第 137 行 `ic_value !== null ? toFixed(4) : '无数据'` 把 7 个无 IC 值项都渲染成"无数据"，与用户观感吻合（summary 计数仍为 6，口径差 1 需前端澄清）。宿主（非容器）环境下逐源实测，**根因全部代码级定位，均与容器 TLS 拦截无关**：

**(A) 折溢价率缺 nav —— IOPV 三级降级链 4 处代码 bug，实测全链 0 命中**
- 数据源实测：`hq.sinajs.cn`（sina）、`qt.gtimg.cn`（qq）、`push2.eastmoney.com`（em）三者 HTTP 均 200 且有数据——**源可用，坏在解析**；
- **sina（`_fetch_iopv_from_sina`，factor_registry.py:687-717）双错位**：`sym = parts[2]`（实际是昨收价，代码应从行前缀 `var hq_str_sh510050` 提取）；`nav = parts[8]`（实际是成交量 513471237）→ 解析出 `{'3.029': {'nav': 513471237.0}}` 这类 key/值全错的 dict → 与真实 symbol 永不匹配 → 0 命中；且实测 sina 该实时接口 **34 个字段根本没有 IOPV 字段**（到 `[30]=日期/[31]=时间/[32]=状态` 止）——接口选型本身就错；
- **qq（`_fetch_iopv_from_qq`，720-759）解码崩溃**：`resp.read().decode("utf-8")` 遇 GBK 中文抛 UnicodeDecodeError → 整个源被外层 except 吞掉；且注释"pos 31 = IOPV"实测错误（`[31]=0.037` 是涨跌额）；
- **em（`_fetch_iopv_from_em`，762-810）解析空**：`fields=f12,f13,f2,f236` 请求 `ulist.np/get` 返回体**不含 f236** → `row.get("f236")` None → 0 命中；且 push2 对高频重复请求时好时坏（本地实测 200 → RemoteDisconnected）；
- **TTJ 兜底（factor_registry.py:1124-1132 → `hub.get_fund_nav` → `china_market.fetch_fund_nav`）类型契约错**：`fetch_fund_nav` 返回 `tuple[float, float]`（`(nav, chg)`，china_market.py:1086-1113），调用方却用 `_nav.get("nav")`（dict 契约）→ AttributeError 被 except 吞掉 → 兜底**永远静默失败**；
- 四级链路（sina→qq→em→TTJ）代码全坏 + 零单测 → 折溢价率 no_data 是**必然结果**而非数据源问题。

**(B) 跟踪误差缺 benchmark_close / 规模变化率缺 shares_change_20d（market_data_hub.py:1242-1292）**
- benchmark_close：仅**宽基 ETF**（510050/510300/510880 等）从东财指数历史注入，行业/主题 ETF（159545/513120 等）无基准映射 → 全缺；且依赖 EM 源（容器被拦/宿主不稳定）；
- shares_change_20d：`fetch_etf_shares_outstanding`（china_market.py:494-521）走 akshare `fund_etf_hist_em`（8s 超时 + EM 源脆弱 + "份额"列名匹配乱码风险）→ 失败率极高，10 只全缺；
- 两字段均为"真数据源接入"工作（非 bug），但**依赖链脆弱且无失败降级**。

**(C) sentiment 三因子"截面无差异（常量输出）"——设计缺陷，非数据问题**
- `panic_greed_diff`/`stock_divergence`：注入的是**全市场单一值**（`sentiment_index`、`advance_decline`/`advance_ratio`，factor_registry.py:1134-1150）→ 10 只样本**完全相同** → 截面 std=0 → IC 不可计算 → 标 no_data（O20 常量检测生效）；
- `news_direction`：`get_news_stock` 对 ETF 基本查不到 → 降级 `news_scope=market` 注入**同一批全市场新闻** → 同样截面恒等；
- **本质**：宏观/市场级数据（情绪指数、涨跌家数比）作为"每只 ETF 打分"的截面因子天然无区分度——应改为 regime/组合层因子（不参与截面 IC），或换 ETF/板块级情绪数据源。

**(D) vol_ratio 弱 IC（warn）——真实弱因子**
- 71 样本、IC=0.001（非无数据）：量比对 ETF 收益截面预测力接近 0（ETF 同质化 + 量比差异小），或 IC 计算窗口/横截面方法偏差——需先核对 IC 口径（P2-9），再按 O6 淘汰线决策。

**(E) 测试防护缺口**
- IOPV 三级链 + sina 净值函数是**纯函数**（可 mock 响应文本断言解析），却**零单测** → 4 处解析 bug 全部存活；`fetch_fund_nav` 返回 tuple 与调用方 dict 契约不匹配亦无契约测试；verify_e2e 对因子只查"列表返回非空"（factors/active 200），从不断言 no_data 数量/数据完整性 → 因子页"7 个没数据"长期静默。

---

## 7. 前后端数据断裂排查

- 8 页面 playwright 走查：**无 JS console error**；Dashboard/行情/配置/数据源/Token 页零失败请求；
- 组合管理页 3 个请求（watchlist/hot-plates/tasks）与资讯页 8 个请求在 8s 快照窗口内未完成（requestfailed）；**延长等待至 50s 后全部 200**——结论为**"慢后端→前端超时/空白"的软断裂**，非硬断链：
  - 组合管理页 8s 时"场内 ETF 列表"空白（权重合计 0.0%），用户体验差；
  - 慢主因 = `/market/watchlist` 29.9s（§10）；
- hot-plates 字段（change）不被前端消费，无字段级断裂；heat/stock tab 字段匹配。

---

## 8. round8 三份文档问题清单核对

见 `diag/out/round8_verification.md`（核对表全文）。摘要：

- **确认修复（12）**：O5、O8、O11、O12、O15、O16、O17、O18、O19、O22、O23、O26；**未复现（2）**：O3、O10（热缓存/宿主正常态下未再触发，不计入修复）；
- **部分修复（4）**：O1（后台化生效、A股段超时）、O7（兜底文案 OK、LLM 仍 60s 超时）、O9（concept_tags ✓、补名 ✗、watchlist 性能 ✗）、O25（reason ✓、no_data 仍 6）；
- **未修复（4）**：O2（港股K线 0 条）、O4（A股/美股个股名称搜索 0 命中）、O6（负 IC 未淘汰）、O21（容器内双栈失效）；**O24 已修复**（round9 §6.1-2：symbol-analysis/stream 删除 rate_limit_cap 透传 + runtime 白名单过滤，实测 5 类标的正常出文）；
- **未专项验证（2）**：O20（K线图渲染，需人工视觉）、O27（市值注入路径一致性）。
- interaction-redesign（P1-P7 状态机）：前端 42 文件 388 用例全绿，达成；
- frontend-theme-redesign（字号/铺满）：theme.css 已放大、Lighthouse 无劣化，达成。

---

## 9. 前端性能（Lighthouse 13.4.1，desktop preset）

| 页面 | Performance | LCP | TBT | CLS | 附注 |
|---|---|---|---|---|---|
| 首页 / | 90 | — | — | — | a11y 96 / BP 96 / SEO 91 |
| 行情分析 /market-analysis | **100** | 0.7s | 0ms | 0.004 | echarts 按需生效 |
| 组合管理 /portfolio-analysis | 99 | 0.9s | 40ms | 0.042 | 数据加载期 CLS 可控 |

**结论**：O8（echarts 按需 + CLS 治理）确认达成；F18 硬门禁（perf≥0.6、CLS≤0.1）远超。前端性能**无问题**。

---

## 10. 后端全链路性能（perf_diag.py，49 端点）

48/49 通过（1 个 422 为 body 空预期行为）。**8 个端点 >1s**：

| 端点 | 耗时 | 根因 |
|---|---|---|
| `/market/watchlist` | **29856ms** | 批量行情降级链在容器内逐源超时（10 条自选 × 多源重试），无整体超时 |
| `/portfolio/calculate` | 5052ms | 全持仓因子/行情采集（EM 源被拦后重试） |
| `/market/stock-hot-rank` | 4711ms | 东财热度接口被拦后降级 |
| `/market/indices/global` | 4367ms | 全球指数多源降级 |
| `/market/realtime` | 2314ms | 全市场快照 |
| `/market/chart/510050` | 2092ms | K 线源降级 |
| `/market/wind` | 1831ms | 同上 |
| `/portfolio/tasks` | 1387ms | join 多表 |

watchlist 29.9s 与 O9 验收④"<1s"差距 30 倍，且 verify_e2e 对该端点只查 DB 行数（§11），**性能黑洞零门禁**。

---

## 11. 测试防护体系为何未识别（4 类系统性盲区，本轮复诊再添 3 类）

1. **分析 stream 端点无契约测试**：verify_e2e `section_analysis`（720-758 行）只测 llm-report/llm-advice（stream 版也只断言 HTTP 200 不读 SSE 内容），**从不测 symbol-analysis/stream 与 sector-analysis/stream** → O24 回归（rate_limit_cap 参数错误）在 5 类标的分析（A股/港股/美股/ETF/指数）全挂的情况下零拦截；
2. **预热门禁口径错误**：A01 门禁（98-120 行）用 `total_elapsed`（profiler 标注段求和 12.6s <20s → PASS），**刻意不用墙钟**（注释防 instruments 后台任务误报）→ 真实墙钟 37.4s 超 30s 阈值被"洗白"为 12.6s；预热的性能退化对门禁不可见；
3. **watchlist 只查 DB 不调 API**：`section_db_integrity`（1435-1450 行）对 watchlist 断言"行数非空"，从不请求 `/market/watchlist` 测响应时间 → 29.9s 端点从未被拦截（O9 验收④形同虚设）；
4. **容器环境零覆盖**：verify_e2e / perf_diag / 所有历轮验证都在宿主 Windows 本地 uvicorn 上跑，**从未在 docker 容器验证** → C1-C5（compose 解析、Dockerfile CMD、容器内 :: 拒 IPv4、EM TLS 拦截、mootdx 未配置）全部漏检；单测 mock 数据又是"完美形态"（round8 §6 已述，本轮未再扩大）；
5. **IOPV 三级链零单测（§6.5.1-A）**：`_fetch_iopv_from_sina/qq/em` + `fetch_etf_net_value` 是纯函数（输入输出可断言）却零单测 → sina 字段双错位、qq GBK 解码崩溃、em 字段不匹配、TTJ tuple/dict 契约错 4 处 bug 全部存活，折溢价率必然 no_data 而门禁不拦截；
6. **设计报告涨跌数据无断言（§4.3-A）**：verify_e2e 只查「design_text 已持久化 + market_regime 已判定」，从不核对设计报告内涨跌值与行情源一致性 → 560600 幽灵锚、「今日涨跌」无时间戳等错误静默通过；
7. **策略检查完整性无断言（§4.4/§4.5）**：verify_e2e 对 check 记录只查存在性，不查 holdings 每项 tech_signal/industry 非空、「因子数据 N/M 正常」真实性、孤立记录 → 规则引擎骨架缺字段、假正常、组合为空误导均零拦截。

> 共同根因：**门禁验证的是"代码自述的行为"，不是"生产形态（容器）+ 真实数据链路 + 真实用户体验"的验收**。

---

## 12. 优化方案（按优先级，未实施）

### P0（阻断/功能全挂，优先修复）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P0-1 | ~~O24 回归：symbol-analysis 全挂~~ **已实施（round9 §6.1-2）** | 删除 `rate_limit_cap` 透传（llm_complete_stream 无此参数）+ runtime.py 透传白名单过滤（仅 max_retries/retry_delay）+ 回归测试更新 | symbol-analysis/stream 对 5 类标的 SSE 正常出文 ✅（实测 600519 42.8KB 无 STREAM_ERROR） |
| P0-2 | 容器内 EM 源被 TLS 拦截 | a) 容器内 akshare 请求换 curl_cffi（Chrome TLS 指纹）；b) 降级链升级：mootdx（配 bestip）/Sina/腾讯 提为主链，EM 置末；c) 容器出口走宿主代理；三选一 + 兼容组合 | 容器内候选池 ≥100、ETF 数据质量 ≥10 条、个股搜索命中 |
| P0-3 | 容器内 `--host ::` 失效 | 容器内统一 0.0.0.0（已临时实施）；本地 O21 意图保留；新增"容器启动后 127.0.0.1 连通"的 docker 冒烟 | docker e2e 冒烟：容器内 IPv4 直连 200 |
| P0-4 | watchlist 29.9s | 批量行情加整体超时（如 8s）+ 降级链短路（EM 冷却期跳过）；已有 batch 路径复用（market.py:696-703 的 get_realtime_batch）扩到 watchlist | watchlist ≤1s（10 条）；新增 verify_e2e watchlist 耗时门禁 |
| P0-5 | 策略检查 LLM 60s 超时 + 全 hold 模板 | 超时对齐 90s（O7 验收）；规则引擎兜底输出个性化建议（按因子分区间生成差异化操作建议 + 引用技术信号），消除同模板；行业数据缺失时明示而非空转 | ①LLM 可用时 covered_by_llm>0；②无 LLM 时建议非模板化；③与 /signal 信号方向不矛盾 |
| P0-6 | 折溢价率缺 nav：IOPV 三级链 4 处解析 bug（§6.5.1-A） | ①sina：代码从行前缀 `var hq_str_(\w+)` 提取、IOPV 改用含真 IOPV 的接口（实测 sina 实时接口无 IOPV，需换源或删该级）；②qq：`decode("gbk")`；③em：核实 IOPV 字段名（ulist.np/get 返回无 f236，改用 clist/get 或换字段）并补防限流退避；④补单测（P3-7） | 宿主环境下 10 只样本 nav 命中 ≥8，折溢价率 no_data 消除 |
| P0-7 | TTJ 兜底类型契约错：`fetch_fund_nav` 返回 tuple，调用方用 dict（§6.5.1-A-4） | 统一契约：`fetch_fund_nav` 改返回 dict（`{"nav", "daily_change_pct"}`）或调用方解包 tuple；两端改一处并加类型断言单测 | 兜底路径不再静默失败；单测覆盖 tuple/dict 两种历史形态 |
| P0-8 | 560600 幽灵锚：硬编码「中证A500ETF」强制锚，实际为医药白酒ETF/零成交/全源无此证券（§4.3-B） | ①全量清点 560600 硬编码：`MANDATORY_CODES`（allocation_engine.py:218 / market_data_hub.py:107）、`_COMMON_ANCHOR_SYMBOLS`、硬编码锚条目、**定层分支 `code in ("510300","560600")`（market_data_hub.py:836/885/893）**、**prompt 候选锚列表（portfolio_design.md:14）**、**etf_scanner.py:55 的 CORE_REQUIRED**——全部改 159338（真实中证A500ETF华夏，行情可用），并补 159338 归核心层的定层分支；②锚代码加行情身份校验（腾讯/新浪名称 vs instruments，不一致即拦截并告警） | 设计报告无「数据源不可用」锚标的；159338 正确落核心层；强制锚在全部行情源身份一致 |
| P0-9 | 报告「今日涨跌」无数据时间戳，收盘后对照必错位（§4.3-A） | 设计任务记录行情采集时刻；表格列改「今日涨跌（截至 HH:MM）」+ 涨跌来源标注（pool/快照/K线）；生成后修改告警 | 报告可追溯数据时间；与收盘对照差异有解释 |

### P1（数据完整性/正确性）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P1-1 | O2 港股 K 线 0 条 | 修复港股历史数据源链（finnhub→alphavantage→akshare get_k_data），加源差异日志；对 K 线最新价与实时价做一致性校验 | `/history/00700?asset_type=HK` >100 根 |
| P1-2 | O4 A股/美股个股搜索 0 命中 | 容器内 instruments 同步段级超时 + 降级（EM 挂时用 levistock/akshare 兜底）；重灌 instruments；名称搜索门禁从 SKIP 改 FAIL | 茅台/600519/apple 命中非空 |
| P1-3 | O6 负 IC 因子未淘汰 + 文案错误 | 负 IC 且 |IC|≥阈值的因子降权/标记；reason 文案改 `|IC|=0.449 ≥ 0.02（负向）` | factors/active 无"负 IC 标 valid 且文案 ≥阈值"矛盾项 |
| P1-4 | 预热门禁口径 | verify_e2e A01 增加墙钟 elapsed_seconds 的 WARN 线（如 40s）；PROFILE_WARMUP 报告补"未标注段"汇总 | 预热超 30s 时门禁告警（WARN 而非 PASS） |
| P1-5 | 560600 数据缺失仍入核心 | 设计管道对"行情数据不可用"标的不给核心权重（或整仓剔除并标注）；值域/完整性 gate 前置 | design 核心层无数据缺失标的 |
| P1-6 | design 顶层 market_regime 为空 | 详情接口补顶层 market_regime（复用 market_context） | 字段非空 |
| P1-7 | instruments 补名失败（O9） | watchlist_add 的 instruments 查询放宽 market 匹配（如忽略大小写/映射 etf→A） | 不传 name 的新条目显示真实名称 |
| P1-8 | 跟踪误差缺 benchmark_close（§6.5.1-B） | 行业/主题 ETF 补跟踪指数映射（instruments 表加 benchmark 代码字段），宽基逻辑外扩；EM 指数源失败时降级腾讯/新浪指数 | 10 只样本 benchmark_close 命中 ≥6，跟踪误差出 IC |
| P1-9 | 规模变化率缺 shares_change_20d（§6.5.1-B） | `fetch_etf_shares_outstanding` 加降级链：东财份额接口 → 天天基金规模 → 基金规模估算；列名乱码 `_decode_df` 加固；失败时 reason 明确标注"份额源不可用" | 10 只样本 shares_change_20d 命中 ≥6，规模变化率出 IC |
| P1-10 | sentiment 三因子截面恒等（§6.5.1-C，设计缺陷） | ①`panic_greed_diff`/`stock_divergence` 属市场级因子——移出截面因子池（改 regime 输入/组合层因子，参照 static 政策因子不参与截面 IC）；②`news_direction` 在 news_scope=market 时标注"市态级降级，不计算截面 IC"，接入 ETF 级舆情（板块新闻→成分 ETF 映射）后恢复 | 截面因子池无宏观单值因子；因子页 reason 明示"市场级因子不参与截面 IC" |
| P1-11 | 本地快照兜底失效：`etf_scanner._etf_cache_file()` 解析到 backend/app/data/（不存在）（§4.3-B 附带①） | 路径修正 `../../data`（去掉多余一层 app/）；补单测断言解析路径存在 | 宿主环境 `_snapshot_change_pct` 不再恒 None；快照兜底生效 |
| P1-12 | 因子分与涨跌可用性缓存口径不一致：factor 用实时 fetch_history、change_pct 用缓存 get_kline_rows_any（§4.3-B 附带②） | K 线兜底改走同一数据通道（fetch_history 或刷新缓存后取数）；统一「有历史 ⇒ 涨跌可算」 | 因子有分的标的，涨跌不再莫名「数据源不可用」 |
| P1-13 | 策略检查技术信号空：indicators 空 dict 时 technical_signal={}，注入跳过 + 骨架无字段（§4.4-1） | ①`technical_signal` 兜底改为显式 `{"signal": None, "reason": "技术指标不可用"}`（空 dict 也覆盖）；②860-862 注入无论有无真实信号都写 `tech_signal`（无则「数据不可用」）；③`_build_rule_fallback_holdings_analysis` 骨架补 tech_signal 字段 | 任何路径 holdings 每项都有非空 tech_signal（真实值或「数据不可用」标注） |
| P1-14 | 策略检查行业数据空：industry_map 依赖候选池（空则全空）（§4.4-2） | industry_map 增加独立兜底链：候选池 → instruments/sector 表 → ETFClassifier 独立分类，候选池空时仍可注入；骨架 industry 同源 | 数据源可用时行业缺失权重 <20%；候选池空时仍有兜底行业标注 |
| P1-15 | 「因子数据 N/M 正常」假正常：RSI 50/KDJ 50 缺数据默认值计入 filled（§4.4-3） | filled 判定排除兜底默认值（RSI/KDJ 恰为 50、ATR 恰为 0、vol_ratio 恰为 1 等中性默认）；真实值才算 filled；data_quality 增加「兜底占比」字段 | 全兜底时不报「10/10 正常」；报告明示真实数据覆盖率 |
| P1-16 | 「组合为空」裸文案无诊断：strategy_check 空持仓直接返回，不记录查询条件/原因（§4.5-4） | 空持仓时在报告/日志记录诊断：portfolio_type 值、DB 查询行数、is_active 过滤、symbols 列表；区分「真空组合」与「查询条件异常」；孤立 check 记录（无 task）标注来源 | 「组合为空」报告附原因；孤立记录可追溯 |

### P2（质量/体验）
| # | 问题 | 方案 | 验收 |
|---|---|---|---|
| P2-1 | 资讯 level 分级失真（L5 占 50%、无 L1、stars=level） | 重新校准分级规则（来源权重/时效/量级），stars 加独立"新鲜度"维度 | 分布合理（L5 <30% 且有 L1）；stars≠level |
| P2-2 | 新闻智能分析情绪指数与系统不一致 | llm-news-analysis 注入系统 sentiment（37.8）作为基准，要求 LLM 引用而非自估 | 报告情绪与系统口径一致 |
| P2-3 | 板块"单日 13.03%"超界 | O5 值域校验扩展到板块/热度数据（±10% 外标"数据源异常"） | 无超界板块值透传 |
| P2-4 | 策略检查记录缺 portfolio_type | worker 持久化补写字段 | 详情返回 on_exchange |
| P2-5 | MACD histogram 冗余 | indicators 接口截断历史数组（如仅返回末值/短序列） | 响应体积下降 |
| P2-6 | mootdx 探针误报 | source_health 对 mootdx 做实测拉取（或 bestip 未配置时标 unavailable） | 探针状态与实测一致 |
| P2-7 | 镜像携带历史日志 + 预热产物不可取回 | backend/.dockerignore 排除 logs/；`./logs` 加入 volume 挂载（预热产物直接落宿主可见） | 镜像体积下降；预热报告宿主可见 |
| P2-8 | 前端"无数据"口径：7 项无 IC 值 vs summary 计数 6（§6.5.1 触发） | 因子行区分展示：no_data（数据源缺失，标 reason）与 warn（弱 IC，标 IC 值+阈值）；summary 卡片加"待关注（warn）"独立计数 | 页面 6 无数据 + 1 待关注 与 summary 一致，reason tooltip 可见 |
| P2-9 | vol_ratio 弱 IC=0.001（§6.5.1-D） | 核对 IC 计算口径（横截面/时序、窗口、未来收益对齐），确认非方法偏差；确认后按 O6 淘汰线处理（|IC|<0.02 → warn → 降权/淘汰） | vol_ratio 状态与 IC 口径一致（warn 且 reason 含阈值说明，或按 O6 淘汰） |
| P2-10 | 候选池零成交/身份错配标的不设防（560600 零成交仍入核心） | 候选池构建时按行情源交叉校验：零成交（量=0）或名称与 instruments 不一致的标的剔除/降级标注，不入核心层 | 候选池无身份错配标的；核心层全部有有效行情 |
| P2-11 | 前端展示历史孤立 check 记录（#343 类）误导为当前结果（§4.5-3） | 历史/任务列表过滤无 task 关联的孤立 check 记录，或标注「历史异常记录（无任务关联）」；检查详情页展示记录生成时间 | 历史列表无孤立记录；详情时间戳明确 |

### P3（测试防护补强，防再犯）

| # | 方案 | 验收 |
|---|---|---|
| P3-1 | verify_e2e 新增 `section_symbol_stream`：symbol-analysis/stream 对 5 类标的（A股/港股/美股/ETF/指数）断言 SSE 含 full_text 且无 STREAM_ERROR | 本轮 P0-1 修复后全绿；回归必拦 |
| P3-2 | verify_e2e watchlist 加 API 耗时门禁（≤5s WARN / ≤10s FAIL） | 29.9s 必 FAIL |
| P3-3 | A01 门禁加墙钟 WARN 线；预热报告覆盖未标注段 | 37.4s 必 WARN |
| P3-4 | 新增 `docker-smoke` 脚本（compose up + 容器内 IPv4 探测 + 关键端点冒烟），进 CI/发布门禁 | 容器环境 C1-C5 类问题零漏检 |
| P3-5 | 前端标的分析组件补"SSE STREAM_ERROR → 分类失败 + 重试"交互测试 | O24 类回归在组件层可拦 |
| P3-6 | **诊断开关回滚**：`PROFILE_WARMUP=1` 本轮注入 prod backend 属诊断残留——常态运行前回滚该行（dev 侧保留），需要时用 `docker compose run -e PROFILE_WARMUP=1` 临时注入 | prod 无 profiler 开销；产物仅诊断期产生 |
| P3-7 | IOPV 链纯函数单测（§6.5.1-E）：`_fetch_iopv_from_sina/qq/em` + `fetch_etf_net_value` 用 mock 响应文本（含 GBK 字节、无 f236 等反例）断言解析结果 | 4 处解析 bug 类回归零漏检；测试含"接口无 IOPV 字段""GBK 中文""key 不匹配"反例 |
| P3-8 | 因子数据完整性契约门禁：verify_e2e 新增因子断言——no_data ≤2 且 reason 分类正确（数据源缺失/截面无差异/样本不足 三类文案齐备）；`fetch_fund_nav` 返回类型契约断言 | 因子页"7 个没数据"类回归必 FAIL；契约两端类型不匹配必拦 |
| P3-9 | 设计报告涨跌真实性断言（§4.3）：verify_e2e 对最新 design 断言——①报告含数据时间戳字段；②抽样 3 只标的，报告 daily_change_pct 与**报告标注时刻**的行情（设计时缓存/快照值）一致（允许降级源偏差 ≤0.5pct，不对比收盘价——盘中与收盘差异属正常，见 §4.3-A）；③强制锚代码必须通过行情身份校验（无「数据源不可用」入核心） | 560600 类幽灵锚回归必 FAIL；时间戳缺失必 FAIL；涨跌与生成时刻行情脱节必 FAIL |
| P3-10 | 策略检查完整性断言（§4.4）：verify_e2e 对最新 check 断言——①holdings 每项 `tech_signal` 非空（真实值或「数据不可用」标注，不能缺字段）；②「数据不可用」占比 ≤20%；③行业缺失权重 <50%（源可用环境）；④报告不得在因子全兜底时报「N/M 正常」 | LLM 超时/行业空/信号空类回归必 FAIL |
| P3-11 | 场内检查「组合为空」误报门禁（§4.5）：verify_e2e 手动触发 `strategy-check-async {portfolio_type: on_exchange}` 断言 holdings ≥1 且 report 不含「组合为空」（DB 有持仓时） | 组合空误报回归必 FAIL |

---

## 13. 结论

- 前端（Lighthouse 90-100、零 console error、388 单测绿）与设计引擎主体（O18/O19/O22/O26 等 12 项修复确认 + O3/O10 未复现）状态良好；
- **当前阻塞项**：容器内 EM 源（P0-2）、watchlist 29.9s（P0-4）、策略检查全 hold 模板（P0-5）；**O24 已修复**（§6.1-2）；
- **因子模型 7 个无数据因子**：非数据源问题——IOPV 链 4 处代码 bug（P0-6/P0-7）、benchmark/shares 依赖链（P1-8/P1-9）、sentiment 设计缺陷（P1-10）为修复主力，单测与完整性门禁（P3-7/P3-8）防再犯；
- **设计报告涨跌与「数据源不可用」**：560600 硬编码幽灵锚（P0-8）、报告缺数据时间戳（P0-9）、本地快照路径 bug（P1-11）、因子/涨跌缓存口径不一致（P1-12）、候选池身份校验前置（P2-10）、涨跌真实性门禁（P3-9）；
- **策略检查复诊**：LLM 超时（P0-5）、技术信号空与行业数据空（P1-13/P1-14）、因子假正常判定（P1-15）、「组合为空」诊断与孤立记录（P1-16/P2-11）、完整性门禁（P3-10/P3-11）；
- 基础设施层面，历轮"宿主验证"掩盖了容器环境的 5 个基础问题（C1-C5），P3-4（docker 冒烟门禁）是防再犯的关键投入；
- 本方案基线未实施（P0-P3 共 47 项，等待 review 至实施标准）；**例外**：P0-1（O24 回归）、P0-3（容器内 host 绑定）已在复诊轮实施，C1-C3（基础设施）已落地——均见「附改动」。

---

## 附：本轮改动（诊断所需，均已落地并附注释）

1. `docker-compose.yml`：backend-dev command 改 list 形式（修 C1）；prod backend 加 `PROFILE_WARMUP=1`（诊断）；两处 `--host` 容器内改 0.0.0.0（修 C3）；
2. `backend/Dockerfile`：CMD 注释移到独立行（修 C2）+ 容器内 0.0.0.0（修 C3）；
3. 诊断脚本/产物：`diag/` 下 run_design_check.py / run_market_analysis.py / run_hot_watchlist.py / run_step678.py / walk_frontend.cjs / check_round8_extra.py 等，产物在 `diag/out/`；
4. **IOPV 链专项诊断脚本**（§6.5.1，宿主复验用）：`diag/iopv_probe.py` / `iopv_parse.py` / `iopv_parse2.py`（实测 sina/qq/em 三源响应 + 解析函数输出，定位 4 处解析 bug）。
