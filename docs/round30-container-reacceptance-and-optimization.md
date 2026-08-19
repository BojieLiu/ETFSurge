# round30 容器重建全量验收 — 修复与优化方案（2026-08-19）

> 本文档为 round29 R68-R84 全部落地后的**新一轮 Docker 重建 + 16 项动作全量验收**结论与剩余问题修复设计。
> **本文档仅设计修复方案，不实施**。依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile 重建，后端 `787e58ffe5e4` / 前端 `eae3f8142b20`；`PROFILE_WARMUP=1`。
> 验证窗口：2026-08-19 19:13–19:40（**周三盘后**，A 股收盘后；美股盘前）。盘后/数据源冷却成分见 §0.4。

---

## 0. 执行摘要

### 0.1 本轮性质与核心结论

round29 的 R68-R84 已全部实施（commits `e251928`+`3e342c6`+`bc0c70f`+`d4fdd04`）。本轮用全新镜像复验，**区分「修复已生效」与「运行时目标仍未达成」**。

**核心结论：round29 的 R69/R77/R70b/R57/R70/R71/R78/R79/R80/R82/R83/R84 已真正生效；但 P0 级问题「因子数据全空」仍存在，且发现两个新缺陷（R68 落盘路径错误 + 因子计算路径不读 Hub 缓存），导致「设计/策略检查能产出 full 报告，但因子评分是占位值（RSI 50.0、综合信号 -0.34 全标的同值）冒充真实评分」。**

### 0.2 验证动作与结果

| # | 动作 | 结果 |
|---|---|---|
| 1 | Docker 构建 + 回收老镜像 | ✅ 新镜像 backend `787e58ffe5e4` / frontend `eae3f8142b20`，无 dangling 老镜像 |
| 2 | 预热性能诊断 | ⚠️ 序列 27.3s（market_cache 21.4s 最大）；墙钟 53.8s > 30s 预算 |
| 3 | 组合设计 + 场内策略检查 | ✅ 设计 631 full、检查 615 full（13/13 LLM）；⚠️ **因子 valid=0/no_data=182，占位因子冒充** |
| 4 | A/HK/US 行情分析 | ✅ 综合研判/投顾/腾讯高质量；❌ 600519 技术面空、AAPL 整链空、茅台/腾讯/苹果搜索 0 |
| 5 | 热点 + 自选 | ✅ 热点真实；自选 A 股有价、美股 TSLA 仍「数据源维护中」 |
| 6 | 持仓技术信号 | ⚠️ technical 组件有真实值，但 composite 全 degraded（因子空） |
| 7 | 资讯分级 + 智能分析 | ✅ LLM 摘要大量生效；⚠️ 分类欠分类、部分 ai_summary null |
| 8 | 因子模型页 | ❌ **valid=0/no_data=27/static=11**（与 round29 相同） |
| 9 | 前后端断裂 | ⚠️ watchlist realtime 结构不一致（3 种形态）；R74 口径三值并存 |
| 10 | round29 落地核验 | 代码级 R68-R84 全在；运行时 9 项生效、2 项部分、1 项目标未达成（R68 因子） |
| 11 | 前端 Lighthouse | ✅ portfolio a11y 100（R64 生效）；⚠️ root perf 73 / portfolio 70、news CLS 0.075 回升 |
| 12 | 后端链路性能 | ✅ 热态全 <0.5s（concept 8-26ms、watchlist 22ms）；❌ 冷态 concept 38.9s / watchlist 18.3s / indicators 23-35s |
| 13 | 测试防护缺口 | ⚠️ 见 §12 |
| 14 | 冗余代码 | ✅ 无新增生产/测试死代码；backend 根散落调试产物（gitignored）+ `backend/E:` 路径残留目录 |
| 15 | 综合结论 + 修复方案 | 本文档（R85-R91） |
| 16 | 回收容器 + 归档 + commit/push | 见 §16 |

### 0.3 问题分级（本轮新发现，危害驱动）

- **P0（投资判断/数据可信度）**
  1. **R85 — 因子数据全空，设计用占位因子冒充真实评分（R68 目标未达成）**：因子模型页 `valid=0/no_data=27`，设计 factor_data_quality `valid=0/no_data=182`，但设计仍产出 3 方案且 rationale 用 `RSI 50.0`（无数据默认）、`动量因子 +0.300`、`综合信号 -0.34`（**全标的同值**）冒充真实因子。根因（本轮代码级定位）：`factor_registry._fetch_market_data`（`factor_registry.py:1148`）的数据获取顺序是 ①因子模块自身 `_kline_cache`（`_get_cached_kline`，**从未被预热填充**）→ ②SourceRegistry 电路检查 → ③实时 `market_data_hub.get_history()`（`_kline.py:215`，**live fetch 绕过 hub 已热身的 `_kline_cache_rows`**）。而 design-data warmup（R59④，`main.py:430`）只调用 `market_data_hub.refresh_kline()` 填充 **hub 的 `_kline_cache_rows`**，因子计算路径**不读它**。盘后 live fetch 空 → 因子全空 → 缺数据填 0.0/默认值（`factor_registry.py` 占位逻辑）→ 下游无法区分「真实 0」与「无数据」。**这是「两个缓存域断裂」：hub 缓存热、因子模块缓存冷，同一批 K 线数据两条路径一热一冷。** 佐证：技术信号路径（`signal.py`，读 hub `get_kline`）有真实值（components.technical=0.75/-1.0），因子路径无值。
  2. **R86 — R68 kline_cache.json 落盘路径错误（写到源码目录，非挂载卷）**：容器内实测 `/app/app/data/kline_cache.json` 存在（1.09MB），`/app/data/kline_cache.json`（挂载卷 `./data:/app/data`）不存在。根因：`_kline.py:114-127 _kline_cache_path()` 用 `getattr(settings, "data_dir", None)`，但 `Settings`（`config.py:66`）**无 `data_dir` 属性**（只有 `database_url`）→ 落到 fallback `os.path.dirname(__file__)×3 + "data"` = `/app/app/data`（源码目录，非挂载卷）。后果：R68 落盘「重启后加载磁盘缓存」目标在 Docker 仍未达成——文件写到镜像层，`docker compose down/up` 即丢。
- **P1（正确性/性能）**
  3. **R87 — R74 口径仍未统一（66.5% vs 33.3% vs 26/39 三值并存）**：策略检查 summary=`因子填充率 66.5%`（键级），factor_availability=`26/39`（键级 66.7%），composite_decision.reason=`分项覆盖 33.3% < 60% 阈值`（类别级 technical/valuation/momentum 1/3）。三者底不同，虽已加标签仍易混——专业投资者无法一眼判断因子数据到底「66% 可用」还是「33% 可用」。13 只持仓 composite_decision 全 `degraded=true, signal=null`。
  4. **R88 — A股个股/美股 K 线盘后不可用（R60 兜底不覆盖个股）**：600519 realtime 有价（1307.88 +0.76%）但 indicators/signal `data_available=false`（K线<30）；AAPL realtime=null + K线空（美股整链盘后空）；00700 K线完整但 realtime=null。根因：R60 的 Hub 缓存兜底（`analysis.py:688-699` `get_kline_rows_any`）只对 **ETF** 有效（design-data warmup 仅缓存池内 ETF），**个股（600519/AAPL）不在 Hub K 线缓存** → 兜底取空。个股历史源（stock history）盘后可用性需独立排查。
  5. **R89 — 冷路径性能仍慢（热路径已全修复）**：sectors/concept 冷 38.9s、sectors/industry 冷 20s、watchlist 冷 18.3s、indicators/AAPL 冷 35s、indicators/600519 冷 23s、realtime/00700·AAPL 8s、stock-hot-rank 7.5s。热态全部达标（concept 8-26ms、watchlist 22ms、industry 6ms）。冷路径 = 首次 akshare 全量拉取 + 冷 K 线建库，重启后首呼体验差。
- **P2（治理/呈现）**
  6. **R90 — 资讯分类欠分类 + 摘要缺口**：`广州新房五连涨`→level1 other（应利好/市场）；`Iran attacks US targets`→level2 neutral（应风险≥4）；`经济学家评特朗普政策"致命组合拳"`→level4 positive（语义反，应为利空）。ai_summary 仍有 null（macro 1/3、global 1/3 高重要性条目）——R65 rule 兜底未覆盖全部。
  7. **R91 — A股个股中文名搜索 0 结果**：`茅台/A`=0、`腾讯/A`=0、`苹果/A`=0（R76 pinyin 兜底盘后未生效，levistock 空结果）；ETF 名正常（银=30、半导体=15）。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-19 19:13–19:40（周三盘后）。以下结论含盘后/数据源冷却成分，属「待交易时段复测」：R88（个股 K 线源盘后可用性）、R91（levistock 盘后空）。但 R85（因子缓存两域断裂）、R86（落盘路径错误）、R87（口径三值并存）、R89 冷路径（首次 akshare 全量拉取）均为**代码级结构事实，不受窗口影响**。

---

## 1. 预热性能诊断（PROFILE_WARMUP=1）

**产物**：`logs/warmup_timing.json`、`warmup_cprofile.txt`、`warmup_pyinstrument.txt/html`。

**实测（warmup_timing.json，序列合计 27324.9ms）**：
| 阶段 | 耗时 | 备注 |
|---|---|---|
| init_db | 86.7ms | |
| redis_init | 85.0ms | |
| warmup_etf_cache | 27.6ms | |
| warmup_global_indices | 5752.3ms | 单次（R56 保持） |
| **warmup_market_cache** | **21373.3ms** | 仍最大项 |

**墙钟 53.8s**（`[warmup-budget] 预热总耗时 53.8s 超过预算阈值 30.0s`）。

**CPU 热点（cProfile 54.8s 总）**：
| 热点 | 累计 | 说明 |
|---|---|---|
| `{method 'acquire' of '_thread.lock'}` | 55.1s | **线程池饱和**（64-worker 争抢） |
| `threading.py:wait` | 49.0s | 线程等待 |
| akshare `demjson.py:decode` | 21.6s | 纯 Python JSON 解析（`ETF_FAST_JSON=1` shim 未默认启用） |
| `_ipv4_getaddrinfo`（config.py:29） | ~5.4s（分处） | 强制 IPv4 DNS，每新 host 首次 ~2-4s |
| `_fetch_us_list`（sync_instruments.py:238） | 6.0s | 美股列表拉取（urlopen + DNS） |

**修复设计**：见 §7.2（R85/R89）。

---

## 2. 组合设计 + 场内策略检查

### 2.1 组合设计（task 614，design_id=631，✅ 成功但因子占位）
`POST /design-async {"capital":500000}` → 完成 ~96s（引擎 2.7s + LLM report 90s，配额节流下仍产 full）。

- **R69 ✅**：`off-hours + pool cached — skipping realtime refresh (R59⑤, 37 by_code)` → `pre-allocate 1.54s candidates=29` → `v5 orchestrator generated 3 strategies in 2.7s`。
- **R77 ✅**：`3/3 strategies have valid non-CASH ETFs`；日志 `all non-CASH candidates lack price/return data — skipping stale removal to avoid 100% cash`。
- **R70b ✅**：report_quality=**full**（`generate_design_report` connect 15→60s 生效）。
- **❌ R85（因子占位冒充）**：`factor_data_quality={valid:0, no_data:182, static:11, valid_rate:0.0%}`，但 rationale 全用占位值：
  - `RSI 50.0 中性`（`_compute_kdj` 等无数据时返回 50.0 默认）
  - `动量因子 +0.300`（全标的同值）
  - `综合信号中性（-0.34）`（全标的同值）
  - factor_score 全「偏弱」
- 全部 ETF 为静态宽基（红利低波/上证50/沪深300/创业板/中证500/科创50/30年国债/黄金），**无卫星层、无强势板块标的**（strong_sector_coverage=[]），现金 39-60%。
- **结构告警自曝**：`inv3_satellite_not_monotonic`（satellite_counts 全 0）、`inv5_total_not_monotonic`、`inv6_aggressive_cash_over`（cash 1.0）。

### 2.2 场内策略检查（task 615，✅ full）
`POST /strategy-check-async {"total_capital":500000,"portfolio_type":"on_exchange"}` → 完成，**llm_layer_ok=True、is_fallback=False、report_quality=full、coverage=13/13**（round29 为 0/13）。

- **R57/R70 ✅**：summary 为真实 LLM 输出（含 RSI 44.02、量比 4.17、溢价 7.06%、KDJ J=6.90 等真实值）。
- **❌ R87**：summary=`因子填充率 66.5%` vs factor_availability=`26/39` vs composite.reason=`分项覆盖 33.3%`（§8）。
- **❌ R85 下游**：13 只持仓 composite_decision 全 `degraded=true, signal=null`，components `{technical: 有值, valuation: 0.0, momentum: 0.0}`——因子/基本面组件全空，综合信号退化为纯技术。

---

## 3. A/HK/US 行情分析（AI 内容审阅）

- **综合研判（llm-report）✅ 高质量 + R79/R80 生效**：第 3 章「国内流动性」现含真实 LPR 1年3.0%/5年3.5%、M2 18.88%、M1 20.54%、CPI 0.5%、PPI 3.5%、PMI 49.4、10年国债 1.6831%、美债 4.72%、联邦基金 3.63%、VIX 15.19；报告末尾「基于2026-08-19行情快照」（as_of 标注）。逻辑严谨、数据与最新行情匹配。
- **AI 投顾（llm-advice）✅ 高质量**：三档配置表（进攻/平衡/防御 + 14 类 ETF 权重表 + 权益占比 81%/78%/70%）、分批建仓、再平衡纪律；引用煤炭焦炭提涨、房地产公积金新政、医药中报、农业厄尔尼诺（与热点数据吻合）。
- **个股 00700 ✅ 完整专业**：MA5=443.4/MA10=458.88/MA20=462.12/MA60=453.53 空头排列、RSI 44.37、KDJ K=19.17/J=7.93 超卖、MACD 柱 -8.60 收窄、支撑 436-438/压力 453-462、回购 267.3 亿港元、南向 5.34 亿；诚实标注「PE/PB 数据源不可用」。
- **个股 600519 ❌ 技术面空（R88）**：基本面专业（营收 922.78 亿 +1.30%、归母 445.17 亿 -1.95%、PE_TTM 36.48、动态 PE 18.8-19.1x、46 家机构预测 860 亿），但「历史K线为空，技术指标 {}」——`indicators/600519` 同窗口 `data_available=false`。
- **个股 AAPL ❌ 整链空（R88）**：realtime=null + indicators/signal 全 `data_available=false`。
- **搜索自动补全 ⚠️**：`银`→30 条（银行 ETF）、`半导体`→15 条、`TQQ`→TQQQ（R84 ✅）；**`茅台`/`腾讯`/`苹果` → 0 条（R91）**。

**专业投资者是否接受**：综合研判/投顾/腾讯分析达专业水准；**但设计/策略检查的因子评分是占位值冒充（R85）、A股茅台/美股 AAPL 技术面空（R88）、个股中文名搜不到（R91）**，专业投资者对「因子真实可用性」与「个股技术面缺失」不可接受。

---

## 4. 热点 + 自选

- **热点 ✅**：`hot-plates` 煤炭（宝泰隆/美锦能源/大有能源/陕西黑猫，reason 焦炭提涨+原煤产量新低）；`stock-hot-rank` 50 条（宇树科技 +460% 上市首日、金风科技、京东方A -7.11%、金螳螂 -10.05%）。数据真实。
- **自选 ⚠️**：22 条。A 股有真实价（中际旭创 895.6 -9.36% stale、半导体ETF 1.045 -7.69% last_close）；**美股 TSLA realtime=null +「非交易时段无行情（数据源维护中）」**（美股盘前时段，文案「维护中」误导——实为盘前无实时，非源故障）。
- **watchlist 结构不一致（task 9 断裂）**：3 种 realtime 形态并存——①`{price, change_pct, volume, data_source, as_of, estimate_source}`（id=28）、②`{price, change_pct, is_estimated, estimate_source, as_of}`（id=27，无 volume/data_source）、③`realtime=null + _degraded + data_unavailable`（id=26）。前端需兼容三形态，存在断裂风险。

---

## 5. 持仓技术分析

- 技术信号 ✅：`/market/signal/00700` 返回 `signal=sell score=-2.0 reasons=[MACD死叉空头, MA5<MA20空头排列]` 自洽；600519/AAPL `data_available=false`（K线<30）。
- **❌ 综合信号全降级（R85 下游）**：13 只持仓 composite_decision 全 `degraded=true, signal=null, score=null`，reason「分项覆盖 33.3% < 60% 阈值」。technical 组件有真实值（0.75/-1.0/0.25），但 valuation/momentum 全 0.0 → 综合信号不可用，退化为纯技术信号。诚实但因子面缺失。

---

## 6. 资讯

- ✅ **LLM 摘要大量生效**：headlines/macro 多条 `ai_summary_source=llm`（司法部/沪硅产业/Moderna/宇树科技等真实摘要）。
- ⚠️ **R90 分类欠分类**：`广州新房五连涨`→level1 other（应利好/市场）；`Iran attacks US targets`→level2 neutral（应 risk≥4）；`经济学家评特朗普政策"致命组合拳"`→level4 positive（语义反，应为利空）。`_CATEGORY_KEYWORDS` 未覆盖「连涨/袭击/致命」等。
- ⚠️ **R90 摘要缺口**：macro/global 仍有 ai_summary=null 的高重要性条目（R65 rule 兜底未覆盖全部）。

---

## 7. 因子模型

- ❌ **R85**：`/factors/active` `total=38, static=11, no_data=27, valid=0`——与 round29 相同。etf_specific 10 no_data、technical 14 no_data、style 2 no_data、sentiment 1 no_data。
- 根因链见 §0.3 R85：**因子模块自身缓存冷 + live fetch 空，与 Hub 已热身缓存两域断裂**。
- factor_ic_records 未新增（IC 回填日志 `已回填（242 交易日），跳过`）。

---

## 8. 前后端断裂排查（task 9）

- ✅ R62 生效（00700→HK、AAPL→US、600519→A）。
- ⚠️ **watchlist realtime 结构 3 形态不一致**（§4）——前端需兼容。
- ⚠️ **R87 口径三值并存**（§2.2）：summary 66.5% / factor_availability 26/39 / composite 33.3%。

---

## 9. round29 方案落地核验（完整矩阵，task 10）

| ID | 判定 | 实证 |
|---|---|---|
| R56 预热单次 | ✅ | warmup_global_indices 5752ms 单次 |
| R57 LLM 内层超时 | ✅ | 检查 615 llm_layer_ok=True |
| R58 IC 回填重试 | ⚠️ | 机制在，但因子仍空（R85 根因） |
| R59 设计降级 | ✅ | 设计 631 full 非失败 |
| R60 个股 K 线注入 | ❌ | 600519 仍空（兜底不覆盖个股，R88） |
| R61 港股降级链 | ✅ | 00700 完整技术面 |
| R62 asset_type | ✅ | 00700→HK 等 |
| R63 news CLS | ⚠️ | 0.075（<0.1 但回升自 0.029） |
| R64 a11y | ✅ | portfolio 100 |
| R65 资讯摘要 | ⚠️ | LLM 摘要大量生效，rule 兜底仍有 gap |
| R66 因子分跨屏 | 待复测 | 无新鲜设计跨屏样本（因子空） |
| R67/R50 清理 | ✅ | backend 根仅 conftest.py |
| R68 K 线缓存落盘 | ⚠️→❌ | 缓存热身 OK，但落盘路径错误（R86） |
| R69 设计降级方案 | ✅ | 631 产出 |
| R70 配额诚实降级 | ✅ | summary 三分类 |
| R70b connect 60s | ✅ | 设计报告 full |
| R71 concept 热路径 | ✅ | 8-26ms |
| R74 因子口径 | ⚠️ | 标签改了但仍三值（R87） |
| R75 IC 回填阻塞 | ✅ | /health 6ms，无抢占 |
| R76 中文搜索 | ⚠️ | ETF 名 OK，个股名仍 0（R91） |
| R77 100%现金防御 | ✅ | 3/3 non-CASH |
| R78 自选收盘兜底 | ✅ | A 股有真实价，watchlist 22ms |
| R79 国内流动性 | ✅ | 第3章真实 LPR/CPI/PMI |
| R80 as_of | ✅ | 报告 as_of 标注 |
| R81 板块 AI 分析 | ✅ | 前端写回修复（31 测试） |
| R82 美股自选实时 | ⚠️ | 7s 窗口生效（TSLA 曾 3.88s→有 stale），但盘前 TSLA 仍 null |
| R83 资讯徽章 | ✅ | 去数字星 + 相对时间（但 `.news-stars` 死 CSS 残留） |
| R84 美股搜索 | ✅ | TQQ→TQQQ |

**核验结论**：round29 的 R68-R84 中 **R69/R70/R70b/R71/R74(部分)/R77/R78/R79/R80/R81/R82(部分)/R83/R84 真正生效**；**R68（因子数据可用性目标）未达成**，暴露两个新缺陷 R85/R86；R60/R76 因不覆盖个股而部分失效。

---

## 10. 前端 Lighthouse（4 路由，task 11）

| 路由 | perf | a11y | CLS | 备注 |
|---|---|---|---|---|
| / | 73 | 96 | 0.0007 | perf <90 |
| /market-analysis | 86 | 100 | 0.0007 | |
| /portfolio-analysis | 70 | 100 | 0.0007 | **a11y 100（R64 ✅）**；perf 最低 |
| /news | 91 | 95 | **0.075** | CLS 0.029→0.075 回升 |

- ✅ R64：portfolio a11y 86→100。
- ⚠️ R63：news CLS 0.029→0.075（仍 <0.1 达标，但回升需查因）。
- ❌ F4/F5（Lighthouse perf/a11y 硬门禁）仍未实施；root perf 73 / portfolio 70 无人拦截。
- perf 瓶颈：LCP 3.2-3.7s、TBT 464-760ms（主线程阻塞，疑 ECharts+Vue 大 bundle）。

---

## 11. 后端链路性能（冷/热，task 12）

| 端点 | 冷态 | 热态 | 判定 |
|---|---|---|---|
| /health | 0.06s | 0.00s | ✅ |
| /portfolio/etfs | 3.3s | 2.7-8.5ms | ✅ |
| /market/hot-plates | — | — | ✅ |
| /market/stock-hot-rank | 7.5s | 0.2s | ⚠️ 冷 |
| /market/search | 9.9s（个别词） | 0.5ms | ⚠️ 冷（美股 suggest 兜底） |
| /market/watchlist | 18.3s | **22ms-3.7s** | ✅ 热修复（R78/82）；❌ 冷 |
| /market/indicators/600519 | 23.0s | — | ❌ 冷（个股 K 线空） |
| /market/indicators/AAPL | 35.0s | — | ❌ 冷 |
| /market/indicators/00700 | 0.47s | 0.45s | ✅ |
| /market/realtime/00700、AAPL | 8.0s | — | ⚠️ |
| /market/sectors/industry | 20.0s | 6-449ms | ✅ 热 |
| /market/sectors/concept | 38.9s | **8-26ms** | ✅ 热修复（R71）；❌ 冷 |
| /market/indices/global | 0.6-6.5s | 0.3ms | ⚠️ 周期慢（后台刷新争抢） |
| /factors/active | 36ms | 0.9ms | ✅ |
| /news/headlines | 1.7ms | 1.7ms | ✅ |

**结论**：热态全部达标（除 concept 首呼）；冷态（重启后首呼）仍是痛点——akshare 全量拉取 + 冷 K 线建库，与 R85（因子冷缓存）同源。

---

## 12. 测试防护缺口分析（task 13，为何现有测试未识别）

1. **R85（因子缓存两域断裂）**：R68/R69 测试分别 mock「落盘条件放宽」「降级产出」，但**无集成测试覆盖「hub._kline_cache_rows 已热身 + factor_registry._kline_cache 空 + live fetch 盘后空 → 因子全空但设计仍产占位方案」的跨缓存一致性场景**。单测验「方法已应用」，不验「因子路径读到了 hub 缓存」。
2. **R86（落盘路径错误）**：无测试断言 kline_cache.json 写到「挂载卷 data_dir」而非「源码目录」——`settings.data_dir` 属性缺失未被捕获（容器环境 vs 本地开发环境路径差异，单测在本地跑 `data/` 恰好存在）。
3. **R87（口径三值）**：R74 测试验「summary 含填充率」「composite reason 自描述」，**不验「summary 与 composite 与 factor_availability 三者数值一致性」的跨字段断言**。
4. **R88（个股 K 线）**：R60 测试验「Hub 缓存兜底」，但兜底源是 **ETF** kline cache，不覆盖「个股 symbol 不在 ETF cache + 盘后 stock history 空」。
5. **R89（冷路径性能）**：无性能基准覆盖 sectors/concept、watchlist 冷态首呼（Lighthouse/verify_perf 只测热态与前端）。
6. **共性**：与 round27/28/29 一脉相承——**测试验「方法已应用」非「目标已达成」，mock 快乐路径，不测「前置条件未满足」的级联场景与「跨缓存/跨字段一致性」的结构事实**。本轮新增教训：**R68 修了 hub 缓存持久化，但因子计算走的是另一条缓存域——两条缓存域的一致性从未被测试覆盖**。

---

## 13. 冗余代码排查（task 14）

- ✅ 历史清理全落地（round28 R50/R67 + code-health BE-1~6/BP-1~13），无新增生产/测试死符号。
- ⚠️ backend 根散落调试产物（gitignored）：`bs2.log/cr.log/crash.log/md3.log/rtc.log/xdist1.log/xdist2.log/full_pytest.log/pytest_full*.log/mypy_errors.txt/_debug_*.txt`；**`backend/E:` 为路径错误残留目录**（含 ETF_Surge/ 子目录）。
- ⚠️ `scripts/archive/` 12 个历史探测脚本（可评估精简，非阻塞）。
- ⚠️ 前端 `NewsView.vue:442` `.news-stars` CSS 死类残留（R83 去数字星后未删）。

---

## 14. 修复方案总表（R85-R91，不实施）

### 14.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R85 | P0 | 因子数据全空，占位因子冒充（两缓存域断裂） | ①**因子路径接 Hub 缓存**：`factor_registry._fetch_market_data`（`factor_registry.py:1148`）在 live fetch 前/失败后，回退 `market_data_hub.get_kline_rows(sym)`（读 hub 已热身缓存，与 R60 symbol-analysis 同款），把 rows 转 close/high/low/volume 数组；②**缺数据填 None 而非 0.0/50.0**：`_compute_*` 缺数据默认值（`factor_registry.py:144-453`，如 `_compute_rsi_14:183-186` 返回 50.0、`_compute_ln_mcap:144` 返回 0.0、`_compute_kdj_*:324-357` 返回 50.0）→ 改填 None，下游区分「真实 0」与「无数据」（gap 机制标缺失）；③**预热填充因子模块缓存**：design-data warmup 除 `refresh_kline` 外，同步 `factor_registry._set_kline_cache`（或让 `_fetch_market_data` 直接读 hub，消除双缓存） | ①盘后首呼 design 产出 `valid>0` 的因子（非占位 RSI 50.0）；②负向：factor_matrix 全空时不得产出「RSI 50.0/信号 -0.34 全同值」冒充；③`/factors/active` valid 数 >0 | `factor_registry.py:1148-1237/144-453`、`hub/_kline.py:225`、`main.py:430` |
| R86 | P0 | kline_cache.json 落盘到源码目录 | ①`config.py` 增 `data_dir` 属性（从 `database_url` 解析 `/app/data` 或显式 `DATA_DIR` env）；②`_kline_cache_path()` 优先读 `settings.data_dir`，缺失时 WARNING + 落到 `database_url` 同目录 | ①容器内 kline_cache.json 写到 `/app/data/`（挂载卷）；②负向：容器内 `/app/app/data/kline_cache.json` 不得再生成 | `config.py:66-68`、`hub/_kline.py:114-127` |
| R87 | P1 | R74 口径三值并存 | ①统一「因子可用性」单一口径：summary 与 composite.reason 与 factor_availability 用同一数值（推荐「分项覆盖率」：technical/valuation/momentum 有值类别占比）；②summary「因子填充率」改为「因子分项覆盖率 X%」，与 composite reason「分项覆盖 X%」同底；③或删除键级 factor_availability 展示，只保留分项口径 | ①三处数值一致；②负向：禁止「66.5%」与「33.3%」并存 | `portfolio/strategy_check.py:196-232/512-517`、`analysis/signal.py:91-95` |
| R88 | P1 | 个股 K 线盘后空（兜底不覆盖个股） | ①**个股 K 线缓存扩展**：design-data warmup / symbol-analysis 将个股（A 股 600519 等）也纳入 K 线缓存（或独立 stock kline cache + 落盘，复用 R86 修复后的路径）；②**个股历史源降级链排查**：盘后实测 `fetch_history('600519','A')` 各源可用性，确认是「源不可用」还是「未缓存」；③AAPL 美股历史源盘后可用性探针（D1） | ①盘后 600519 indicators data_available=true；②负向：个股 K 线不得因「不在 ETF 缓存」而空 | `analysis.py:672-699`、`main.py:386-436`、`china_market.py`（个股 history） |
| R91 | P2 | A股个股中文名搜索 0 | ①R76 pinyin 兜底未生效排查：`_search_a_stocks` 空结果时先试 `Instrument.pinyin/first_letter`（表内个股若 0 条则 pinyin 无从查）；②**补 instruments 表 A 股个股段同步**（当前 0 条是数据缺口）；③levistock 空结果 WARNING（已加）+ 盘后降级到静态个股基座（若存在） | ①「茅台」→600519；②负向：levistock 空结果不得静默 | `market.py:379-435`、`sync_instruments.py` |

### 14.2 性能

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R89 | P1 | 冷路径慢（concept 38.9s / watchlist 18.3s / indicators 23-35s） | ①**冷路径与热路径同源**：R85 修复后，因子/设计冷路径读 hub 缓存，消除冷 K 线建库；②concept/industry 冷首呼 = akshare 全量拉取，**预热期后台预拉 + 落盘缓存**（同 kline_cache 模式）；③watchlist 冷 18.3s → R78 收盘兜底缓存快照读缓存而非实时拉（已部分实现，冷首呼仍回源）；④预热 THS 同步改 `run_sync_long` + `ETF_FAST_JSON=1` 默认启用（demjson 21.6s） | ①重启后首呼 concept ≤10s、watchlist ≤6s；②负向：冷路径不得与热路径相差 >10x | `main.py:238-245/386-436`、`sector_fetcher.py:240-268`、`market.py:973-1033`、`config.py`（ETF_FAST_JSON） |

### 14.3 治理 / 呈现

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R90 | P2 | 资讯分类欠分类 + 摘要缺口 | ①`_CATEGORY_KEYWORDS` 补词：「连涨/提价/超预期」→positive≥3；「袭击/致命/威胁」→risk≥4；「收跌/连跌」→negative；②`_rule_news_summary` 扩展到 macro/global 全部高重要性（level≥3）条目；③`经济学家评特朗普政策"致命组合拳"` 语义反 → 标题情感词「致命」应判 negative，排查分类器是否只读首句/关键词命中顺序 | ①广州新房→positive、伊朗袭击→risk≥4；②负向：macro/global level≥3 条目 ai_summary 非 null | `levistock_fetcher.py:25-145`、`news_fetcher.py:265-277`、`_news.py` |

### 14.4 R85/R86 详细设计（P0，级联根因 + 两缓存域断裂）

#### 14.4.0 根因链（代码级 + 运行时实证）

```
【两缓存域断裂】design-data warmup (main.py:430) → market_data_hub.refresh_kline()
  → 填充 hub._kline_cache_rows（37 只 ETF，日志「37 pool symbols kline cached」）
  但 factor_registry._fetch_market_data (factor_registry.py:1148) 的数据获取顺序：
    ① factor_registry._get_cached_kline（模块级 _kline_cache，从未被预热填充）
    ② SourceRegistry.health("factor.history") 电路检查
    ③ market_data_hub.get_history()（hub/_kline.py:215 → china_market.fetch_history LIVE fetch）
       —— 绕过 hub._kline_cache_rows，盘后 live fetch 空
  → factor_registry 缺数据填 0.0/默认值（RSI 50.0、动量 +0.3、信号 -0.34 全标的同值）
  → 因子模型 valid=0/no_data=27；设计 factor_data_quality valid=0
  → 下游：composite 全 degraded；设计 rationale 占位因子冒充真实评分
【佐证】技术信号路径（signal.py 读 hub get_kline）有真实值（technical=0.75/-1.0），
  因子路径无值——同一批 K 线数据两条路径一热一冷。
【落盘路径错误】_kline_cache_path() (_kline.py:114-127) getattr(settings,"data_dir",None)
  → Settings 无 data_dir 属性 → fallback os.path.dirname(__file__)×3 + "data"
  → /app/app/data（源码目录，非挂载卷 /app/data）→ 重启即丢。
```

#### 14.4.1 修复优先级

| # | 优先级 | 优化 | 设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| ① | P0 | **因子路径接 Hub 缓存** | `_fetch_market_data` 在 live fetch 前先试 `market_data_hub.get_kline_rows(sym)`（rows→close/high/low/volume），失败再 live fetch；或直接统一 `get_history` 读缓存 | 盘后 factor compute 命中 hub 缓存，valid>0 | `factor_registry.py:1148-1237`、`hub/_kline.py:215-239` |
| ② | P0 | **缺数据填 None** | `factor_registry.py` 各 `_compute_*` 缺数据默认值（`144-453`：RSI/KDJ 返回 50.0、ln_mcap 返回 0.0 等）→ 改 None，`_compute_*` 守卫 None→gap 标注 | 占位因子不再出现（RSI 50.0 全同值消失） | `factor_registry.py:144-453` |
| ③ | P0 | **落盘路径修正** | `config.py` 增 `data_dir` 属性；`_kline_cache_path` 优先读之 | 容器内落盘到挂载卷 | `config.py:66-68`、`_kline.py:114-127` |

**优先级关系**：①治本（因子路径读 hub 缓存，valid>0 激活全部下游）；②防「占位冒充」（即使①未覆盖，缺数据诚实标 None 而非 0.0）；③治 R86（落盘真正持久化）。

---

## 15. 分两批实施建议（不实施，等待指令）

- **批1（P0/P1 正确性）**：R85（因子路径接 Hub 缓存 + 缺数据填 None）、R86（落盘路径修正）、R87（口径统一）、R88（个股 K 线缓存扩展 + 个股历史源排查）。
- **批2（P1/P2 性能/治理）**：R89（冷路径预热 + ETF_FAST_JSON）、R90（分类词表 + 摘要缺口）、R91（个股中文搜索 + instruments 个股段同步）。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**

---

## 16. 多轮 review 记录

- **Round 1（2026-08-19，实证 + 根因定位）**：对照运行时输出逐条定位 file:line 与数据。确立 R85「两缓存域断裂」框架——`factor_registry._fetch_market_data` 走自身模块缓存 + live fetch，不读 hub 已热身缓存；R86 落盘路径经 `docker exec` 实测证伪（`/app/app/data/kline_cache.json` 存在、`/app/data` 不存在）。R87 三值并存经 strategy-check 响应实证。R88 个股 K 线空经 indicators/600519·AAPL 实测。R89 冷热分测（冷 38.9s/热 8ms）。
- **Round 2（file:line 复核）**：确认 `_kline.py:114-127`（落盘路径 fallback）、`_kline.py:215-222`（get_history live fetch）、`factor_registry.py:1148-1237`（数据获取顺序）、`config.py:66-68`（无 data_dir 属性）、`main.py:430`（refresh_kline 只填 hub 缓存）、`analysis.py:688-699`（R60 兜底只覆盖 ETF 缓存）、`signal.py:91-95` + `strategy_check.py:208-232/512-517`（R74 三值源头）。全部锚点核实无误。
- **Round 3（归因修正：R82 自选「维护中」实为盘前非源故障）**：TSLA realtime=null 的「数据源维护中」文案，经时段判断（19:30 北京 = 美股盘前）修正为「盘前无实时，文案误导」，非 R82 修复失效——R82 的 7s 窗口已在盘中验证（memory 载 TSLA 3.88s→stale 全值）。R82 判定从「❌」修正为「⚠️ 部分（盘前文案误导）」，补入 §4。
- **Round 4（验收口径 + 测试清单补全）**：为每项补「正/负向断言」（防假完成：R85 负向「因子全空不得产占位 RSI 50.0 冒充」、R86 负向「容器内不得再写 /app/app/data」、R87 负向「禁止 66.5% 与 33.3% 并存」）。R89 冷路径阈值明确（concept ≤10s、watchlist ≤6s）。

> **当前状态（Round 1-4 完成）**：R85-R91 均达实施标准（精确 file:line + 根因 + 验收 + 负向断言）；R85/R86 已展开为实施级详细设计（§14.4）。本文档除设计外**不写任何修复代码**，等待「开始实施」指令。
