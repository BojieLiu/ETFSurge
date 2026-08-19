# round30 容器重建全量验收 — 修复与优化方案（2026-08-19）

> 本文档为 round29 R68-R84 全部落地后的**新一轮 Docker 重建 + 16 项动作全量验收**结论与剩余问题修复设计。
> **本文档设计修复方案 + 2026-08-19 实施轮已全部落地**（见文末状态段）。依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」撰写。
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
| 9 | 前后端断裂 | ⚠️ watchlist realtime 结构不一致（3 种形态，R92）；R74 口径四值并存（R87） |
| 10 | round29 落地核验 | 代码级 R68-R84 全在；运行时 9 项生效、2 项部分、1 项目标未达成（R68 因子） |
| 11 | 前端 Lighthouse | ✅ portfolio a11y 100（R64 生效）；⚠️ root perf 73 / portfolio 70、news CLS 0.075 回升 |
| 12 | 后端链路性能 | ✅ 热态全 <0.5s（concept 8-26ms、watchlist 22ms）；❌ 冷态 concept 38.9s / watchlist 18.3s / indicators 23-35s |
| 13 | 测试防护缺口 | ⚠️ 见 §12 |
| 14 | 冗余代码 | ✅ 无新增生产/测试死代码；backend 根散落调试产物（gitignored）+ `backend/E:` 路径残留目录 |
| 15 | 综合结论 + 修复方案 | 本文档（R85-R92；R85/R86/R88/R89 实施级详细设计 §14.4-14.6，R87/R92 已决策口径） |
| 16 | 回收容器 + 归档 + commit/push | 见 §16 |

### 0.3 问题分级（本轮新发现，危害驱动）

- **P0（投资判断/数据可信度）**
  1. **R85 — 因子数据全空，设计用占位因子冒充真实评分（R68 目标未达成）**：因子模型页 `valid=0/no_data=27`，设计 factor_data_quality `valid=0/no_data=182`，但设计仍产出 3 方案且 rationale 用 `RSI 50.0`（无数据默认）、`动量因子 +0.300`、`综合信号 -0.34`（**全标的同值**）冒充真实因子。根因（本轮代码级定位）：`factor_registry._fetch_market_data`（`factor_registry.py:1148`）的数据获取顺序是 ①因子模块自身 `_kline_cache`（`_get_cached_kline`，**从未被预热填充**）→ ②SourceRegistry 电路检查 → ③实时 `market_data_hub.get_history()`（`_kline.py:215`，**live fetch 绕过 hub 已热身的 `_kline_cache_rows`**）。而 design-data warmup（R59④，`main.py:430`）只调用 `market_data_hub.refresh_kline()` 填充 **hub 的 `_kline_cache_rows`**，因子计算路径**不读它**。盘后 live fetch 空 → 因子全空 → 缺数据填 0.0/默认值（`factor_registry.py` 占位逻辑）→ 下游无法区分「真实 0」与「无数据」。**这是「两个缓存域断裂」：hub 缓存热、因子模块缓存冷，同一批 K 线数据两条路径一热一冷。** 佐证：技术信号路径（`signal.py`，读 hub `get_kline`）有真实值（components.technical=0.75/-1.0），因子路径无值。
  2. **R86 — R68 kline_cache.json 落盘路径错误（写到源码目录，非挂载卷）**：容器内实测 `/app/app/data/kline_cache.json` 存在（1.09MB），`/app/data/kline_cache.json`（挂载卷 `./data:/app/data`）不存在。根因：`_kline.py:114-127 _kline_cache_path()` 用 `getattr(settings, "data_dir", None)`，但 `Settings`（`config.py:66`）**无 `data_dir` 属性**（只有 `database_url`）→ 落到 fallback `os.path.dirname(__file__)×3 + "data"` = `/app/app/data`（源码目录，非挂载卷）。后果：R68 落盘「重启后加载磁盘缓存」目标在 Docker 仍未达成——文件写到镜像层，`docker compose down/up` 即丢。
- **P1（正确性/性能）**
  3. **R87 — R74 口径仍未统一（66.5% vs 33.3% vs 26/39 vs 13/13 四值并存）**：策略检查 summary=`因子填充率 66.5%`（键级），factor_availability=`26/39`（键级 66.7%），composite_decision.reason=`分项覆盖 33.3% < 60% 阈值`（类别级 technical/valuation/momentum 1/3），**report_text 正文又写「13/13 只持仓因子数据可用（无兜底）」（第 4 值，持仓级）**。四者底不同，虽已加标签仍易混——专业投资者无法一眼判断因子数据到底「66% 可用」还是「33% 可用」。13 只持仓 composite_decision 全 `degraded=true, signal=null`。**已决策**：统一为分项覆盖率（§14.1）。
  4. **R88 — A股个股/美股 K 线盘后不可用（R60 兜底不覆盖个股）**：600519 realtime 有价（1307.88 +0.76%）但 indicators/signal `data_available=false`（K线<30）；AAPL realtime=null + K线空（美股整链盘后空）；00700 K线完整但 realtime=null。根因：R60 的 Hub 缓存兜底（`analysis.py:688-699` `get_kline_rows_any`）只对 **ETF** 有效（design-data warmup 仅缓存池内 ETF），**个股（600519/AAPL）不在 Hub K 线缓存** → 兜底取空。个股历史源（stock history）盘后可用性需独立排查。
  5. **R89 — 冷路径性能仍慢（热路径已全修复）**：sectors/concept 冷 38.9s、sectors/industry 冷 20s、watchlist 冷 18.3s、indicators/AAPL 冷 35s、indicators/600519 冷 23s、realtime/00700·AAPL 8s、stock-hot-rank 7.5s。热态全部达标（concept 8-26ms、watchlist 22ms、industry 6ms）。冷路径 = 首次 akshare 全量拉取 + 冷 K 线建库，重启后首呼体验差。
- **P2（治理/呈现）**
  6. **R90 — 资讯分类欠分类 + 摘要缺口**：`广州新房五连涨`→level1 other（应利好/市场）；`Iran attacks US targets`→level2 neutral（应风险≥4）；`经济学家评特朗普政策"致命组合拳"`→level4 positive（语义反，应为利空）。ai_summary 仍有 null（macro 1/3、global 1/3 高重要性条目）——R65 rule 兜底未覆盖全部。
  7. **R91 — A股个股中文名搜索 0 结果**：`茅台/A`=0、`腾讯/A`=0、`苹果/A`=0（R76 pinyin 兜底盘后未生效，levistock 空结果）；ETF 名正常（银=30、半导体=15）。
  8. **R92 — watchlist realtime 三形态并存（前端假兼容，估徽标漏显）**：两条 enrich 路径各自拼装 realtime，同一「T-1 收盘估值」语义两种编码（`estimate_source` vs `is_estimated`）；前端只读 `is_estimated` → 形态①（`estimate_source="last_close_cache"`）不显示「估」徽标。属 API 契约不一致（P2 治理）。

### 0.4 验证窗口标注（D3）
本轮执行于 2026-08-19 19:13–19:40（周三盘后）。以下结论含盘后/数据源冷却成分，属「待交易时段复测」：R88（个股 K 线源盘后可用性）、R91（levistock 盘后空）。但 R85（因子缓存两域断裂）、R86（落盘路径错误）、R87（口径四值并存）、R89 冷路径（首次 akshare 全量拉取）、R92（realtime 契约形状）均为**代码级结构事实，不受窗口影响**。

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

#### 2.1.1 为什么标的这么少（机制链 + 历史回归定位）

直接原因不是设计算法变差，而是**上游因子数据没进来（R85 同根因）→ 引擎「盲选」，只能退回静态宽基核心池 + 大比例现金**。

**机制链**：
```
因子数据全空（R85 两缓存域断裂，valid=0）
  → 因子矩阵 valid=0、所有 factor_score 同值占位（RSI 50.0、动量 +0.300、综合信号 -0.34 全标的同值）
  → 引擎无法区分优劣，行业/主题择优不可能
  → 走 Z11 静态池兜底（factor_matrix_empty 触发）
  → 静态池 = 宽基核心 + 黄金/国债（无卫星层）
  → 层预算塞不满 → 39-60% 现金
```
日志佐证：`all non-CASH candidates lack price/return data — skipping stale removal to avoid 100% cash`——R77 守卫生效避免了「100% 现金失败」，但**兜底保住的是「能出方案」，不是「方案质量」**。

**历史回归定位（DB `portfolio_designs`，created_at 为 UTC，+8 = 北京时间；策略内 `etfs` 数组统计非 CASH 数）**：

| 设计 | 时间（北京） | 结果 | 非现金 ETF |
|---|---|---|---|
| 619-623 | 08-18 21:52–22:07 | full/partial，8-10 只 | 510050/512890/512880 证券/513180 恒生科技/159928 消费/159570/159755/511090/518880 等 |
| 626-630 | 08-19 14:01–14:35（**盘中**） | full，8 只 | 同上 + 513050 中概互联/513120 港股创新药/159516 半导体设备 |
| **631** | **08-19 19:19（盘后）** | full/**3-4 只** | 只剩静态：512890/510050/511090/518880（防御）、510300/159915/510500（平衡）、510300/588000（进攻） |
| 611-618 | 08-18 15:52–16:08 | **failed 100% 现金** | 空（round29 R77 修复前） |

**结论：不是渐进劣化，是「进程重启清空因子模块缓存 + 盘后 live fetch 空」的间歇触发**：
1. 因子模块自身 `_kline_cache`（`factor_registry.py:799`，`KLINE_CACHE_TTL=300s`，`:801`）是**进程内存缓存**——只要进程不重启、或 TTL 内有人成功 live fetch 过，因子就有数据 → 能选出行业/主题 ETF。
2. 本轮 `docker compose down/up` 重启容器 → 因子模块缓存清空。
3. 预热（R59④）只填 **hub** 的 `_kline_cache_rows`，**不填因子模块缓存**（两缓存域断裂，R85）。
4. 盘后 live fetch 空 → 因子全空 → 静态宽基兜底 → 3-4 只 + 39-60% 现金。
而 08-18 21:52、08-19 14:35 能恢复 8 只，是因为进程内存缓存还活着（未重启）或盘中 live fetch 成功重新填充。

**「引入时间」的精确回答**：
- **架构缺陷一直存在**：因子模块自建缓存（commit `7ac4a54`，round1/2 时代）起，就从未让因子计算读 hub 缓存——「双缓存域」是历史遗留，平时被「盘中 live fetch 成功 + 进程常驻」掩盖。
- **首次暴露**：**08-18 15:52**（round29 task 571，进程反复重启 + 盘后），表现是 100% 现金失败。
- **本轮再次暴露**：**08-19 19:19**（重启容器 + 盘后首呼），表现是 3-4 只静态兜底。
- 因此 **R85 修复（让因子路径读 hub 缓存）不仅解决「占位因子」，也直接解决「标的少」**——因子数据恢复后，卫星层/行业标的会像 630 之前一样被选出来。

### 2.2 场内策略检查（task 615，✅ full）
`POST /strategy-check-async {"total_capital":500000,"portfolio_type":"on_exchange"}` → 完成，**llm_layer_ok=True、is_fallback=False、report_quality=full、coverage=13/13**（round29 为 0/13）。

- **R57/R70 ✅**：summary 为真实 LLM 输出（含 RSI 44.02、量比 4.17、溢价 7.06%、KDJ J=6.90 等真实值）。
- **❌ R87**：summary=`因子填充率 66.5%` vs factor_availability=`26/39` vs composite.reason=`分项覆盖 33.3%`（§8）。
- **❌ R85 下游**：13 只持仓 composite_decision 全 `degraded=true, signal=null`，components `{technical: 有值, valuation: 0.0, momentum: 0.0}`——因子/基本面组件全空，综合信号退化为纯技术。

#### 2.2.1 报告判断质量评估（record 754，用户提问驱动）

对「中证A500 20% 集中度」「港股 13% 相关性」「红利/恒科偏弱」三条提示的实证核验：

- **① 20% 集中度 ✅ 合理**：`portfolio_etfs` 中 159338 目标权重 0.20 确为最大单一持仓（次大 518880 黄金 10%）；宽基跌 10% → 组合拖累约 2%。但措辞略偏——中证A500 是 500 只大盘股的宽基，「成分股集体现回落」= A 股整体下行，本质是市场级系统性风险而非单一个股集中风险。
- **② 港股 13%「相关性较高」⚠️ 半合理**：权重计算准确（159545 5% + 513120 5% + 513010 3% = 13%），「同一市场系统性风险」成立（美元利率/全球风险偏好/南向资金）。但「相关性较高」**未经实证且以偏概全**——用缓存 K 线 239 个交易日日收益实测：港股创新药(513120) × 红利低波(512890) = **+0.120**（低）、× 中证A500 = +0.428；红利低波 × 中证A500 = **-0.061**（不相关）。恒生红利（高股息低波，防御）与恒生科技（成长）风格相反，历史相关性本就低；真正常见风险因子是「港股市场 beta」而非 pairwise 高相关，且 13% 总权重不构成高集中度。
- **③ 红利类/恒生科技「偏弱」⚠️ 依据真实但口径自相矛盾**：512890/159545/513010 的 `tech_signal=SELL` 是真实信号（signal 路径读 hub K 线有真值），判断方向合理；**但只有技术面支撑**——valuation/momentum 组件全 0.0（R85），无因子/基本面背书。且报告内部矛盾：正文写「因子数据质量：13/13 只持仓因子数据可用（无兜底）」，每只 composite_decision 却写「分项覆盖 33.3% < 60% 阈值」（R87 口径）。**159545 内部 KDJ J 值矛盾**：`factor_summary` 写 `KDJ.J 90.11（超买区）`，建议理由写 `KDJ J值6.90偏弱`——同一指标两个数据路径给出相反结论，恰是 R85 两缓存域断裂的症状。

**改进方向**（并入 R85/R87 验收）：相关性提示改为「港股市场 beta 敞口」或补真实相关性计算；「因子数据可用 13/13」与 composite degraded 必须统一口径；修复 159545 类跨路径指标矛盾。

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
- **watchlist 结构不一致（task 9 断裂，R92）**：3 种 realtime 形态并存——①`{price, change_pct, volume, data_source, as_of, estimate_source}`（id=28）、②`{price, change_pct, is_estimated, estimate_source, as_of}`（id=27，无 volume/data_source）、③`realtime=null + _degraded + data_unavailable`（id=26）。根因：`_watchlist_enrich_items`（market.py:762）与 `_watchlist_close_fallback`（market.py:1004）两条路径各自拼装 realtime，同一「T-1 收盘估值」语义被编码成两种形状（`estimate_source` vs `is_estimated`）——**前端只读 `is_estimated`，形态①的「估」徽标漏显**（假兼容：optional chaining 不崩但不正确）。修复设计见 §14.3 R92。

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
  - **no_data=27 恰好 = 全部「需要行情数据」的因子，无一是「不需要却报缺失」**：

| 类别 | 数量 | 状态 | 原因 |
|---|---|---|---|
| technical（RSI/MACD/KDJ/ATR 等） | 14 | no_data | 需要 close/high/low 数组 |
| etf_specific（折溢价/资金流等） | 10 | no_data | 需要实时价格/净值 |
| style（成长/价值） | 2 | no_data | 需要收益率序列 |
| sentiment | 1 | no_data | 需要涨跌家数等 |
| static（政策对齐 3 + 宏观 5 + 情绪 3） | 11 | static | 不依赖行情数据，恒可用 |

  - 即「哪些因子没数据」的答案是：**所有依赖市场数据的因子都缺**，证明是数据通路（两缓存域断裂）问题而非个别因子 bug。
- 根因链见 §0.3 R85：**因子模块自身缓存冷 + live fetch 空，与 Hub 已热身缓存两域断裂**。
- factor_ic_records 未新增（IC 回填日志 `已回填（242 交易日），跳过`）。

---

## 8. 前后端断裂排查（task 9）

- ✅ R62 生效（00700→HK、AAPL→US、600519→A）。
- ⚠️ **R92 watchlist realtime 3 形态不一致**（§4）——已决策：后端字段对齐（§14.3），不做前端兼容止血。
- ⚠️ **R87 口径四值并存**（§2.2）：summary 66.5% / factor_availability 26/39 / composite 33.3% / report_text「13/13 无兜底」——已决策：统一为分项覆盖率（§14.1）。

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
7. **patrol.py 编排覆盖分析（R85-R92 均无法由 patrol 新增识别）**：patrol 是「编排器」不新增断言，覆盖 = 底层检查覆盖（§12 逐项对照）：
   - **能覆盖（症状层）**：R69/R77（L2-e2e `design-quality` 断言非空方案）、R71/R78/R82 热路径（L3-perf `verify_perf`）、R85 症状（`test_factor_differentiation` 方差 >0.01，`data_health_check.py:76`）——但该测试在**独立子进程**跑，不读容器内已热身的 hub 缓存，盘后因子路径空时同样可能拿到空数据 → 方差 0 FAIL，报告只写 `variance=0.0000`，会被误当成「数据源问题」而非「双缓存断裂」；交易时段 live fetch 成功又假绿。
   - **覆盖不到（根因层 + 本轮全部新增问题）**：R85 双缓存一致性（无测试断言「hub 已热身 + factor 模块缓存空 → 因子全空但设计仍产 full 报告」）；R86 落盘路径（单测在本地 `data/` 恰好存在→绿，容器 `/app/app/data` vs 挂载卷 `/app/data` 差异无覆盖）；R87 四值同底（verify_e2e P3-B 只查「逐项 filled 合计 ≥ 标题」，不查 summary/composite/factor_availability/report_text 四处数值一致）；R89 冷路径（`verify_perf.py:12` 明确「冷缓存首请求为已知」，只测热路径）；R92 realtime 契约形状（无断言「realtime 恒含 7 字段」）；R88/R91 盘后环境相关（断言非空则盘后必 FAIL 误报）。
   - **要让 patrol 真正覆盖需补的负向断言**（当前均不存在）：① `/factors/active` `valid_rate > 0`（盘后/冷启动也不得为 0）；② 跨缓存一致性回归测试：`hub._kline_cache_rows` 已热身时 `factor_registry.compute()` 必须产出非占位因子（R85）；③ kline_cache.json 必须落在 `settings.data_dir`（挂载卷）而非源码目录（R86）；④ verify_perf 加冷路径基准（重启后首呼 concept ≤10s / watchlist ≤6s，R89）。
   - **根本局限**：patrol 退出码 0 只代表「现有检查全绿」，而 R85 恰恰是「现有检查全绿、单测全过、但运行时因子全空、设计用占位值冒充」——patrol 继承了这一盲区，不会新增断言，只重跑已有断言。

---

## 13. 冗余代码排查（task 14）

- ✅ 历史清理全落地（round28 R50/R67 + code-health BE-1~6/BP-1~13），无新增生产/测试死符号。
- ⚠️ backend 根散落调试产物（gitignored）：`bs2.log/cr.log/crash.log/md3.log/rtc.log/xdist1.log/xdist2.log/full_pytest.log/pytest_full*.log/mypy_errors.txt/_debug_*.txt`；**`backend/E:` 为路径错误残留目录**（含 ETF_Surge/ 子目录）。
- ⚠️ `scripts/archive/` 12 个历史探测脚本（可评估精简，非阻塞）。
- ⚠️ 前端 `NewsView.vue:442` `.news-stars` CSS 死类残留（R83 去数字星后未删）。

---

## 14. 修复方案总表（R85-R92，不实施）

### 14.1 正确性 / 数据可信度

| ID | 级 | 问题 | 修复设计 | 验收 | 文件指向 |
|---|---|---|---|---|---|
| R85 | P0 | 因子数据全空，占位因子冒充（两缓存域断裂） | ①**因子路径接 Hub 缓存**：`factor_registry._fetch_market_data`（`factor_registry.py:1148`）在 live fetch 前/失败后，回退 `market_data_hub.get_kline_rows(sym)`（读 hub 已热身缓存，与 R60 symbol-analysis 同款），把 rows 转 close/high/low/volume 数组；②**缺数据填 None 而非 0.0/50.0**：`_compute_*` 缺数据默认值（`factor_registry.py:144-453`，如 `_compute_rsi_14:183-186` 返回 50.0、`_compute_ln_mcap:144` 返回 0.0、`_compute_kdj_*:324-357` 返回 50.0）→ 改填 None，下游区分「真实 0」与「无数据」（gap 机制标缺失）；③**预热填充因子模块缓存**：design-data warmup 除 `refresh_kline` 外，同步 `factor_registry._set_kline_cache`（或让 `_fetch_market_data` 直接读 hub，消除双缓存） | ①盘后首呼 design 产出 `valid>0` 的因子（非占位 RSI 50.0）；②负向：factor_matrix 全空时不得产出「RSI 50.0/信号 -0.34 全同值」冒充；③`/factors/active` valid 数 >0 | `factor_registry.py:1148-1237/144-453`、`hub/_kline.py:225`、`main.py:430` |
| R86 | P0 | kline_cache.json 落盘到源码目录 | ①`config.py` 增 `data_dir` 属性（从 `database_url` 解析 `/app/data` 或显式 `DATA_DIR` env）；②`_kline_cache_path()` 优先读 `settings.data_dir`，缺失时 WARNING + 落到 `database_url` 同目录 | ①容器内 kline_cache.json 写到 `/app/data/`（挂载卷）；②负向：容器内 `/app/app/data/kline_cache.json` 不得再生成 | `config.py:66-68`、`hub/_kline.py:114-127` |
| R87 | P1 | R74 口径三值并存（实际 4 值，含 report_text「13/13 无兜底」） | **✅ 已决策（2026-08-19 会话）：统一为「分项覆盖率」**（technical/valuation/momentum 三分项有真实值占比）。①summary「因子填充率」→ 组合级分项覆盖 = Σ持仓分项有值数/(持仓数×3)；②factor_availability → 每持仓分项覆盖（如 1/3）；③composite.reason「分项覆盖 X%」保持，三处同底；④report_text「13/13 无兜底」删除或改「分项覆盖 X%（技术✓/估值✗/动量✗）」——**呈现增强**：列出具体缺哪个分项，口径不变。理由：分项覆盖是 degraded 门禁的输入（strategy_check.py:755-779），统一后「展示值=决策值」；且 round27 R52 已确立该口径（旧持仓级 100% 掩盖估值/动量恒 0 的教训），本轮只是把展示侧对齐 | ①summary/factor_availability/composite.reason 三处数值一致；②负向：禁止「66.5%」与「33.3%」并存；③report_text 不再出现「N/N 无兜底」持仓级口径 | `portfolio/strategy_check.py:196-232/447-450/512-517/755-779`、`analysis/signal.py:91-95` |
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
| R92 | P2 | watchlist realtime 三形态并存（前端假兼容，估徽标漏显） | **✅ 已决策（2026-08-19 会话）：A' 字段对齐 + 契约固化，不做前端兼容止血**。①**先写契约**：realtime 固定 7 字段 `{price, change_pct, volume, as_of, is_estimated, estimate_source, data_source}`，缺省显式补 `null/false`；②后端两条 enrich 路径统一补字段：close_fallback 缓存命中分支（market.py:1041-1048）补 `is_estimated: true`，enrich 直返分支（market.py:933）补 `is_estimated: false/estimate_source: null/data_source/as_of`；③item 级 `_degraded`/`data_unavailable`/`realtime_unavailable` 标记保留（realtime=null 的顶层语义）；④**否决**：前端归一化（契约仍不一致，只换地方打补丁）、availability 枚举全量重构（改动大 2-3 倍，列软债） | ①三形态统一为「同一字段集不同值」；②负向：形态①（`estimate_source="last_close_cache"`）前端显示「估」徽标（现漏显）；③后端单测断言 realtime 恒含 7 字段；④前端组件测试补「形态①估徽标显示」用例 | `market.py:762-1002`（enrich）、`market.py:1004-1085`（close_fallback）、`frontend/src/components/market/WatchlistPanel.vue:127-164`、`api-contracts/market/` |

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

### 14.5 R88 详细设计（P1，个股 K 线缓存扩展 + 个股历史源排查）

#### 14.5.0 根因链

```
个股 K 线（600519/AAPL）不在 design-data warmup 的 pool 内
  → hub._kline_cache_rows 只含 37 只池内 ETF（main.py:430 refresh_kline）
  → symbol-analysis 的 R60 兜底 get_kline_rows_any（analysis.py:688-699）只查 hub 缓存 → 取空
  → 盘后 indicators/signal data_available=false（K线<30）
  → 个股（600519 技术面空、AAPL 整链空）与 ETF 数据可用性不一致
【未决问题】个股历史源（stock history）盘后可用性未确认——可能是「源盘后不可用」
  也可能是「源可用但缓存未覆盖」，需 D1 探针区分。
```

#### 14.5.1 D1 探针（验证窗口前置，交易时段执行）

| 探针 | 命令/源 | 判定 |
|---|---|---|
| A 股个股 | `fetch_history('600519','A')` 走 mootdx→Sina 降级链（fetch_history:1566 起，个股非 ETF 首环 mootdx） | 源可用 → 问题在缓存未覆盖（方案 A）；源不可用 → 需独立降级链（方案 B） |
| 美股个股 | `fetch_history('AAPL','US')` 走 akshare stock_us_hist(3s)→TickFlow→alphavantage→新浪 stock_us_daily→finnhub 链（fetch_history:1627 起），盘中+盘后各测一次 | 同上 |
| 港股对照 | `fetch_history('00700','HK')`（已知盘后完整，作对照基线） | 排除「HK 源特殊」干扰 |

> 探针遵循 D1 约束：单次探测 + 失败后 ≥60s 间隔，防限流。

#### 14.5.2 缓存扩展（两个方案，探针后择一）

- **方案 A（推荐）：个股纳入 hub K 线缓存**——design-data warmup（main.py:386-436）的 `refresh_kline(_syms[:30])` 符号集合从「pool ETF」扩展为「pool ETF + 自选/持仓个股段（600519 等 A 股 + AAPL 等 US）」，复用同一缓存域与 R86 落盘路径。**与 R85 同哲学：消除第二个缓存域，不新增**。
- **方案 B（备选）：独立 stock kline cache**——模块级 dict + 落盘复用 R86 修复后的 `kline_cache.json` 路径，symbol-analysis/indicators 走它；`get_kline_rows_any` 从「只查 hub cache」扩为「hub cache + stock cache 双查」。
- 两方案均要求：`get_kline_rows_any`（analysis.py:688-699）兜底从「只查 ETF cache」改为「缓存双查 + live fetch 最后兜底」。

#### 14.5.3 验收

- ①盘后 600519 `indicators` `data_available=true`、有 MA/RSI/KDJ 技术面；②负向：个股 K 线不得因「不在 ETF 缓存」而空；③交易时段 AAPL `indicators` 有技术面（正）；④探针结论记录到本文档（源可用性矩阵）。

### 14.6 R89 详细设计（P1，冷路径预热 + ETF_FAST_JSON）

#### 14.6.0 预算冲突与原则

warmup 30s 预算已超（实测 53.8s），**不能往 startup 关键路径内再塞 concept/industry 全量预拉**。原则：**就绪后后台异步预拉，不占 startup 关键路径**——与 `_warmup_market_cache`（main.py:247-258，F17 已验证后台填充安全）同模式。

#### 14.6.1 设计分项

| # | 项 | 设计 | 文件指向 |
|---|---|---|---|
| ① | R85 联动（治本大头） | 因子/设计冷路径读 hub 缓存后，「冷 K 线建库」消除——design-data warmup 已填 hub 缓存，首呼命中 | 依赖 R85（§14.4） |
| ② | concept/industry 冷首呼 | 新增**就绪后后台预拉任务**：`asyncio.create_task` 调 `sector_fetcher.py:240-268` 预拉 concept/industry 并落盘缓存，失败静默（首呼回源兜底）；**不占 warmup 30s 预算** | `main.py`（新增后台任务）、`sector_fetcher.py:240-268` |
| ③ | watchlist 冷首呼 | R78 收盘兜底已实现「缓存快照读缓存」；冷首呼仍回源 → 后台预拉任务触发一次 R78 兜底填充 quote 缓存（`_watchlist_close_fallback`） | `market.py:1004-1085` |
| ④ | THS 阻塞 | 预热/后台 THS 同步改 `run_sync_long`（async_utils.py:121，先例 `sync_indices_meta.py:41-43`），避免阻塞事件循环 | `main.py`、`sync_indices_meta.py:41-43` |
| ⑤ | demjson 21.6s | `ETF_FAST_JSON=1` **默认启用**（main.py:132-133 激活点默认 on，保留 env 显式关闭），消灭纯 Python JSON 解析热点 | `fast_json.py:13`、`main.py:132-133` |

#### 14.6.2 验收

- ①重启后首呼 concept ≤10s、watchlist ≤6s（正）；②负向：冷路径不得与热路径相差 >10x；③负向保障：后台预拉不劣化 warmup 墙钟（不占 30s 预算）；④`ETF_FAST_JSON` 默认 on 后全量 pytest 绿（shim 正确性）。

---

## 15. 分两批实施建议（不实施，等待指令）

- **批1（P0/P1 正确性）**：R85（因子路径接 Hub 缓存 + 缺数据填 None）、R86（落盘路径修正）、R87（口径统一，已决策）、R88（个股 K 线缓存扩展 + 个股历史源排查）。
- **批2（P1/P2 性能/治理）**：R89（冷路径预热 + ETF_FAST_JSON）、R90（分类词表 + 摘要缺口）、R91（个股中文搜索 + instruments 个股段同步）、R92（watchlist realtime 字段对齐，已决策）。
- **测试增强随批1**：patrol 负向断言（§12.7 ①valid_rate>0 ②跨缓存一致性 ③落盘路径 ④冷路径基准）——其中①②③与批1 修复强耦合（修完才有非占位因子/正确落盘可断言），④冷路径基准随批2 R89。

> **当前状态：等待「开始实施」指令，不写任何修复代码。**

---

## 16. 多轮 review 记录

- **Round 1（2026-08-19，实证 + 根因定位）**：对照运行时输出逐条定位 file:line 与数据。确立 R85「两缓存域断裂」框架——`factor_registry._fetch_market_data` 走自身模块缓存 + live fetch，不读 hub 已热身缓存；R86 落盘路径经 `docker exec` 实测证伪（`/app/app/data/kline_cache.json` 存在、`/app/data` 不存在）。R87 三值并存经 strategy-check 响应实证。R88 个股 K 线空经 indicators/600519·AAPL 实测。R89 冷热分测（冷 38.9s/热 8ms）。
- **Round 2（file:line 复核）**：确认 `_kline.py:114-127`（落盘路径 fallback）、`_kline.py:215-222`（get_history live fetch）、`factor_registry.py:1148-1237`（数据获取顺序）、`config.py:66-68`（无 data_dir 属性）、`main.py:430`（refresh_kline 只填 hub 缓存）、`analysis.py:688-699`（R60 兜底只覆盖 ETF 缓存）、`signal.py:91-95` + `strategy_check.py:208-232/512-517`（R74 三值源头）。全部锚点核实无误。
- **Round 3（归因修正：R82 自选「维护中」实为盘前非源故障）**：TSLA realtime=null 的「数据源维护中」文案，经时段判断（19:30 北京 = 美股盘前）修正为「盘前无实时，文案误导」，非 R82 修复失效——R82 的 7s 窗口已在盘中验证（memory 载 TSLA 3.88s→stale 全值）。R82 判定从「❌」修正为「⚠️ 部分（盘前文案误导）」，补入 §4。
- **Round 4（验收口径 + 测试清单补全）**：为每项补「正/负向断言」（防假完成：R85 负向「因子全空不得产占位 RSI 50.0 冒充」、R86 负向「容器内不得再写 /app/app/data」、R87 负向「禁止 66.5% 与 33.3% 并存」）。R89 冷路径阈值明确（concept ≤10s、watchlist ≤6s）。
- **Round 5（用户提问驱动的归因补充，2026-08-19 会话）**：补「为什么标的少」「什么时候引入」「patrol 能否覆盖」三个问题的实证回答（§2.1.1 机制链 + DB 设计历史回归定位、§7 因子类别拆分、§12.7 patrol 覆盖分析）。回归定位结论：非渐进劣化，是「进程重启清空因子模块缓存 + 盘后 live fetch 空」的间歇触发；架构缺陷自 commit `7ac4a54`（round1/2 时代）即存在，首次暴露 08-18 15:52（100% 现金）、本轮 08-19 19:19（3-4 只静态兜底）。另评估 strategy-check 报告判断质量（§2.2.1）：三条提示事实基础准确，但「港股相关性较高」无实证（实测 513120×512890 相关仅 +0.120）、「红利/恒科偏弱」缺因子支撑、报告内部「13/13 无兜底」与 composite「33.3%」自相矛盾（R87 第 4 口径）。
- **Round 6（R87 口径决策，2026-08-19 会话）**：用户采纳「统一为分项覆盖率」（Option A）——summary/factor_availability/composite.reason 三处同底 + report_text 去掉持仓级「13/13 无兜底」+ 呈现增强列具体缺哪个分项（§14.1 R87 行已定稿）。否决键级 66.5%（与决策脱钩，复现「填充率高但综合信号不可用」矛盾）与双指标并存（复杂度高且不符「统一」目标）。
- **Round 7（R92 watchlist 三形态决策 + 全文档一致性 review，2026-08-19 会话）**：用户采纳「A' 字段对齐 + 契约固化」——realtime 固定 7 字段、后端两条 enrich 路径统一补字段、不做前端归一化止血（§0.3/§4/§8/§14.3 R92 已定稿）。否决前端归一化（契约仍不一致）与 availability 枚举全量重构（改动大，列软债）。同步 review：§15 分批并入 R92 + patrol 负向断言随批分派（①②③随批1、④随批2）。
- **Round 8（实施标准补齐 + 锚点复核，2026-08-19 会话）**：①R88/R89 补实施级详细设计（§14.5 个股 K 线缓存扩展：D1 探针前置 + 方案 A 复用 hub 缓存域/方案 B 独立 stock cache 二选一；§14.6 冷路径预热：就绪后后台异步预拉原则规避 30s 预算冲突 + ETF_FAST_JSON 默认启用）；②全文档一致性修正：R87「三值」→「四值」（§0.3/§0.4）、§12.7 覆盖分析并入 R92、§0.2/§14 标题 R85-R92；③锚点批量复核：factor_registry.py:144/183-186/324-357（占位默认值 0.0/50.0）、_kline.py:215-222（get_history live fetch）、analysis.py:688-699（R60 兜底）、sector_fetcher.py:240-268（concept 冷路径）、market.py:379（_search_a_stocks）、news_fetcher.py:265-277（分类）、fetch_history 源链（A 股个股 mootdx→Sina、US akshare→TickFlow→alphavantage→新浪，fetch_history:1566/1627/1718）——全部核实无误；④R88 D1 探针源链修正为代码实际顺序（原写 stooq/yahoo 有误）。

> **当前状态（Round 1-8 完成 + 2026-08-19 实施轮）**：R85-R92 均达实施标准（精确 file:line + 根因 + 验收 + 负向断言）；R85/R86/R88/R89 已展开为实施级详细设计（§14.4-14.6）；R87/R92 口径已决策（§14.1/§14.3）；R88/R91 含「待交易时段复测」验证窗口标注（§0.4/§14.5.1）。
>
> **2026-08-19 实施轮（已实施，commit 见 git log）**：
> - R85：`factor_registry._fetch_market_data` live fetch 前先读 `hub.get_kline_rows_any`（两缓存域打通）；`_compute_*` 缺数据改填 None（RSI/KDJ 50.0、MACD/SMA 0.0、ln_mcap 0.0 等占位消除）；`compute()` z-score 跳过 None、signal/sma20 isinstance 守卫；LLM/engine 消费方（reports.py abs、composite_signal sum、_is_failed_result）补 None 防护。
> - R86：`config.Settings.data_dir` 从 DATA_DIR env / database_url 解析；`_kline_cache_path` 优先读之（容器落 `/app/data` 挂载卷）；global indices cache 同路径。
> - R87：`_component_coverage_stats` 统一分项覆盖率；summary「因子覆盖 X%」/ factor_availability `{filled,total:3,ratio,components}` / composite.reason 三处同底；report_text 删除「N/N 无兜底」。
> - R88：`_kline_warmup_symbols` 预热符号集 = pool ETF + 持仓个股（600519 等 A 股/AAPL 等 US）。
> - R89：`ETF_FAST_JSON` 默认启用（`_fast_json_enabled`）；`_warmup_sector_lists` 就绪后后台预拉 concept/industry（不占 30s 预算）。
> - R90：`_CATEGORY_KEYWORDS` 补「连涨/提价」positive、「威胁/致命」risk、英文 attack(s)/threat risk；`enrich_news_summaries` 配额外 level≥3 全量 rule 兜底。
> - R91：`_STATIC_A_STOCK_BASE` 静态个股基座兜底（instruments+levistock 双空时「茅台」→600519）；同步缺口已由 instruments 启动同步补齐（本地实测 A 股 5546 条）。
> - R92：`_normalize_watchlist_realtime` 归一化 realtime 恒 7 字段；两条 enrich 路径统一；契约 watchlist.md §2.1 固化。
> - 运行时验收（本地 2026-08-19 盘后）：factors no_data 由「数据源未接入」→「IC 积累中（239/250 交易日）」；strategy check summary「因子覆盖 33.3%」三处一致 + LLM full 报告；search 茅台→600519/gzmt→600519；watchlist realtime 恒 7 字段；concept 500 条 0.03s（R89 预拉命中）；level≥3 资讯 ai_summary 非 null。
