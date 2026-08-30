# round34 容器全链路复验轮 — R102 容器内首验 + R103-R122 新发现（2026-08-22 周六；§9 UI/性能走查，§10 已采纳实施方案，§11 测试命名重组方案）

> 本文档为 **R102 实施轮（commit `38a194d`，2026-08-22 本地落地）之后的 Docker 全新构建 + 全链路复验结论**。
> 与 round33 分离：round33 承载 R99-R101 复验（全 PASS）与 §8 R102 方案（未实施）；实施轮 `38a194d`
> 落地后**容器镜像从未重建**——本轮全新 prod 镜像首次在容器内实证 R102，并产出独立 round34 文档。
> 依据 AGENTS.md「反假完成机制」「性能软门禁」「设计流程」+ 容器全链路诊断模板撰写。
> 验证环境：Docker Engine 29.7.2 / Compose v5.4.0，prod profile。
> 验证窗口：2026-08-22 12:58–14:00（**周六非交易时段**）。IC 历史回填读历史 K 线无窗口依赖
> （round33 §8.6 已标注）；实时行情/盘中类结论标注「待交易时段复测」。

---

## 0. 执行摘要

### 0.1 核心结论

1. ✅ **R102 在容器内真实生效且跨环境可复现**：全新后端镜像内 grep 三处修复全部烤入
   （§1.1）；启动日志「历史回填完成：499 个交易日」；DB `COUNT(DISTINCT trade_date)=502`
   （2024-08-01..2026-08-22）；`/factors/active` census **valid=0 / warn=12 / no_data=15 /
   static=11** —— 与本地 R102 验收口径逐项一致；受控 restart 后 distinct 恒 502、总行数恒
   6705（upsert 幂等）。
2. ✅ **R93-R101 回归矩阵全 PASS**（除 R95 连续第三轮受限）：data_dir 挂载卷落盘、检查复合动量
   真实值（0 个 0.300 占位）、搜索四符号内容命中、global level≥3 摘要全覆盖、momentum 无占位 +
   china.policy 独立三维、产出率两维并列诚实、宽基 ≤4 且 correlation_warnings 首次带实测相关
   系数（0.949/0.945）触发。
3. ⚠️ **R95 仍受限**：策略检查 820 LLM 第三轮超时（opencode_zen 主源 400 Bad Request →
   DeepSeek 兜底 81.4s 超时 JSONDecodeError → 规则兜底），LLM 正文数值一致性路径仍不可复现。
4. 🆕 **新发现 6 项（R103-R108）**：
   - **R103（P2）IC 历史回填每启重跑**——场外联接基金 019633 净值序列 658 点击穿动态跳过阈值；
   - **R104（P2）设计 factor_data_quality.ic_accumulation 口径错位**——读到的「样本数」实为
     compute 截面计数（≤15）而非累计交易日（444-502），note 文案恒报「积累中」永不翻转；
   - **R105（P2）M7/P1-1 强制核心锚未落地防御型方案**——159338 已可用但三方案核心层无一持有，
     verify_e2e 四连 FAIL；round31/33 的「环境性缺锚」归因失效；
   - **R106（P3）fund_fetcher 收到非代码 symbol**——etf_index_mapping.json 脏值「黄金9999」被
     当基金代码传参 → URL 含中文 ascii 编码崩、无效请求每刷新轮重放；
   - **R107（P2）策略检查报告表格「因子分」与理由「因子分」同页异源**——表格列为原始因子非零值
     简单平均（混杂量纲），理由列为 composite 复合分，用户可见自相矛盾（如 159992 表格 +1.63 vs
     理由 -2.43）；
   - **R108（P2）R102 回填管道丢弃 OHLCV 列**（2026-08-22 会话追问追加）——`main.py:858` 回填
     kline 只装 {close, dates} 两键，high/low/volume 在重放中恒空 → atr/vol_ratio/vwap/
     amount_stability/kdj×3 **七个**纯 K 线因子无法享受历史回填（IC 仅 n≈7-9，vwap 冻结 245），
     而 12 个 close-only 因子被补到 444-502 天——「新因子为什么不能像 R102 一样补历史」的根因。
5. 📐 **配套改进方案追加（讨论级，随本节整理入档）**：
   - **T-A / S-A 数据源债修复设计**——round33 §8.3「R102 不解决」的 tracking_error/shares_change
     两笔数据接入债首次给出可实施方案（T-A 基准收盘管道接通即可回填；S-A 份额快照表前向积累）；
   - **大面积 warn 的结构性归因 + M-A 多窗口 IC 改进方向**——门槛严/池同质化/window 错配三层
     拆解，含实测证据（相关对 0.945/0.949、return_3m t=0.29、signal.overall IR=0.061）。
   见 §4.6-4.8。
6. ⚠️ 环境性观察（非代码回归）：ETF 记录数稀疏 ×4（周末源中断）、etf_specific no_data=6（较
   round33 的 10 改善）、sentiment news_heat no_data=1、timeline e2e 1.9s 负载伪失败（同轮冷态
   10ms PASS）、Lighthouse 首页 67-68 较 round33 的 76 回落（负载态采样，硬门禁 ≥60 仍过）。

### 0.2 关键判定表

| 判定 | 项目 |
|---|---|
| ✅ 容器内复验 PASS | R93、R94、R96、R97（茅台/00700/AAPL/SPY 内容命中）、R98、R99、R100、R101、**R102（本轮首验）** |
| ⚠️ 受限验证 | R95（LLM 正文路径，连续第三轮超时→规则兜底） |
| 🆕 本轮新发现 | R103（回填每启重跑）、R104（ic_accumulation 口径）、R105（M7 锚未落地）、R106（fund_fetcher 中文名传参）、R107（报告双「因子分」异源）、R108（回填丢 OHLCV 列，7 个纯 K 线因子无法补历史） |
| 📐 追加方案（讨论级） | T-A/S-A 数据源债修复设计、M-A 多窗口 IC 评估口径、warn 结构性归因（§4.7/§4.8） |
| 📐 巡检体系优化设计 | 六类结构性盲区（时间维度/启动行为/日志消费/跨源一致/容器降级态/证据留存）+ P0 三件套（startup 行为审计、样本增长率、日志噪声）/P1 三项/纪律两条，全部讨论级未实施（§12） |
| 📐 pre-commit 门禁评估 | 15 段实测清单 + 合理性总评（结构健康、定位清晰）+ 5 个卫生级改进点（cd 子 shell 化/mypy 缺失提示补齐/13 段数字漂移/skip 不对称标注/verify_perf 移交标注），明确不为 R 系列新增门禁段（§13） |
| 环境性观察 | ETF 记录稀疏 ×4、etf_specific no_data=6、sentiment no_data=1、timeline 1.9s 负载、首页 Lighthouse 回落 |

### 0.3 验证窗口标注（D3）

本轮执行于周六。以下结论**待交易时段复测**：实时行情字段新鲜度、watchlist 冷缓存路径的真实
源耗时、etf_specific 因子产出恢复情况。以下结论无窗口依赖：R102 回填与幂等、R93-R101 结构性
断言、R103-R108 代码级发现（均有 file:line + 运行时证据）。

---

## 1. 环境构建与启动（阶段 1）

| 项 | 结果 |
|---|---|
| Docker | Engine 29.7.2 / Compose v5.4.0（Docker Desktop 冷启动 ~35s 后引擎就绪） |
| 本地遗留清理 | 先停本地 uvicorn(:8000, PID 24020) 与 vite(:5173, PID 9164)（上午 R102 本地验证遗留）——防端口冲突与共享 DB 写竞争；80/8000/5173 全释放后再起容器 |
| 构建命令 | `docker compose --profile prod up --build -d`（延续 round33 教训：`--profile` 为全局标志须置于 `up` 前） |
| 构建+启动耗时 | **~15s**（requirements 层缓存命中，仅源码层重建） |
| 后端镜像 | `etf_surge-backend` **ea946ed7510c**（全新构建 2026-08-22 12:58:26，含 38a194d） |
| 前端镜像 | `etf_surge-frontend` **2880d5ad2e7c**（CreatedAt 2026-08-19 19:12:34 复用；ID 变化为 BuildKit 元数据差异。按 memory 教训核实源码 diff：`git show --stat 38a194d` 仅 backend×3 + tests×2 + docs×1，**零前端改动 → 复用安全**） |
| 容器组 | backend(:8000) + frontend(:80, nginx) + redis:8-alpine |
| 就绪时间 | /health :8000 启动后 **5s** 200；nginx :80 health 200（warmup 后台继续，就绪判据为 liveness） |
| 老镜像回收 | 构建前 `docker image prune -f`（0B 可回收） |

### 1.1 镜像源码实证（memory 教训：勿只信 commit hash）

运行容器内 grep 源码，确认 R102 三处修复烤入镜像：

```
/app/app/fetchers/china_market.py:536:  _datalen = "500" if period == "daily" else "240"
/app/app/fetchers/china_market.py:544:  ...getKLineData?symbol={pref}{symbol}&scale={scale}&datalen={_datalen}
/app/app/main.py:831:  kline_depth = max(
/app/app/main.py:837:  if _existing >= max(kline_depth - 30, 200):
/app/app/main.py:909-912:  cnt = await ic_tracker.backfill_ic_history(db, kline, factor_scores_by_index, max_days=n)
```

`scripts/data_health_check.py` 不在镜像内（host 侧脚本）；其探针 URL 同步（datalen=240→500）
在 38a194d diff 中确认（backend/scripts/data_health_check.py | 4 ±）。

---

## 2. R102 容器内验证（本轮主目标）

### 2.1 证据链

| 验收项 | 预期（round33 §8.5） | 本轮容器实测 | 结论 |
|---|---|---|---|
| 回填日志 | 「历史回填完成：N 个交易日」，预期 N≈490 | `[ic_backfill] 历史回填完成：499 个交易日` @13:01:46（首次 boot） | ✅ |
| DB distinct trade_date | ≥250（跨有效门槛） | **502**（总行数 6705，范围 2024-08-01..2026-08-22） | ✅ |
| /factors/active census | ~14 因子从「积累中」翻 valid/warn，0 假 valid | **valid=0 / warn=12 / no_data=15 / static=11**（summary 字段实测） | ✅ 与本地验收逐项一致 |
| warn 因子诚实性 | t≥2 且 \|IR\|≥0.5 才 valid，弱因子落 warn 非 bug | 12 个 warn 全部 n=444-502、t/IR 为真实统计量（如 etf.change_pct t=5.41 但 IR=0.29<0.5→warn；sma_5 t=-3.58 IR=-0.17→warn），无一同时达标 | ✅ 诚实 warn |
| 重启幂等 | 重启不重跑风暴 / 数据不重复 | 受控 restart 后 distinct 恒 **502**、总行数恒 **6705**（upsert 幂等生效） | ✅ 数据面幂等 |
| kline 缓存深度 | 卷内 500 根 | data/kline_cache.json rows 42/50 标的 =500 根（另有 453×2、658×1 等，见 §4 R103） | ✅ |

**注意**：两次 boot 均**未出现 skip 日志**而是执行了完整回填（13:01:46 与 restart 后 13:16:07 各一次）——动态阈值按其自身逻辑正确工作（见 §4 R103：阈值被 658 深度的场外净值序列顶高），数据无损但违背 R102「重填后应 skip」意图。

### 2.2 结论

R102 四处改动（datalen=500 / max_days=n / 动态阈值 / 探针同步）在容器内全部真实生效；
distinct trade_date 245→502 的跃升可跨环境精确复现（本地 502 = 容器 502）。

---

## 3. 对照 round33 验证矩阵（R93-R101 + 环境观察项）

| round 项 | round33 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|
| R93 | data_dir 绝对路径 + 挂载卷落盘 | 卷共享双侧实证：容器内查 `/app/data/portfolio.db` distinct=502/6705，宿主侧同文件查询结果**完全一致**（502/6705）；kline_cache.json 卷侧持续新写 | ✅ PASS | §2.1 |
| R94+R87 | 检查复合 momentum 真实差异化、覆盖率同口径 | 检查 820：26 持仓 momentum 值 {-1.0,1.0,-0.443,-0.748,-0.993,0.443,0.038…} **0 个 0.300 占位**；11 个零值均为场外联接基金（degraded=true 诚实标注，非占位污染）；正文「分项覆盖 38.5%」与 round32/33 同口径 | ✅ PASS | §6.2 |
| R95 | LLM 正文数值一致 | opencode_zen 400 → DeepSeek 81.4s 超时(JSONDecodeError) → is_fallback=True；covered_by_llm=0 | ⚠️ 受限（第三轮） | §4/日志 13:56:53 |
| R96/R100 | 两维口径并列诚实 | 设计 697 fdq：data_available_pct=**0.1868** = actual_output_rate=**0.1868** ≠ definition_ready_pct=**0.967**；verify_round32_runtime PASS×4 | ✅ PASS | §6.1 |
| R97 | 符号搜索命中 | keyword 参数下：茅台→600519(A)、00700→腾讯控股(HK)、AAPL→苹果(US)、SPY→SPDR S&P 500(US) 全内容命中（探测须带 market 参数，空参数返回默认列表属契约行为非缺陷） | ✅ PASS | §3.1 |
| R98 | global level≥3 摘要非 null | level≥3 共 3 条，ai_summary 3/3 非 null（当日资讯构成变化，round33 为 5/5） | ✅ PASS | §3.1 |
| R99 | momentum 无占位 + china.policy 独立维度 | 设计 697 factor_breakdown 并集**无 momentum 键**（整组缺失=显式不可用）；china.policy.{dual_circulation,five_year_plan,strategic_emerging} 三维独立在列 | ✅ PASS | §6.1 |
| R100 | 产出率字段存在 + 两维并列 | actual_output_rate 存在且 =data_available_pct；负向（退化态对齐）经 runtime 脚本 PASS | ✅ PASS | §6.1 |
| R101 | 宽基数量上限 ≤4 + 高相关提示 | 三方案核心宽基计数 1/2/3 均 ≤4；correlation_warnings 带**实测相关系数**（159915×563360=0.949、159338×510500=0.945，round33 时 corr_matrix 为空无提示）——R101 提示链首次在非空 corr 下实证 | ✅ PASS | §6.1 |
| E2（159338 缺锚） | 待交易时段复测 | **已缓解**：159338 出现在设计相关性宇宙（near_substitute 对）且 563360（A500ETF华泰柏瑞）进入平衡型核心 w=20% —— 但 M7 门禁仍 FAIL，升级为新发现 **R105**（§4.3） | 归因更新 | §4.3 |

### 3.1 关键端点打点（周六盘后）

| 端点 | 实测 | 对比 round33 | 结论 |
|---|---|---|---|
| /health :8000 与 :80 | 200 / 200 | 同 | ✅ |
| watchlist 冷 | **2690ms** | 5300ms | ✅ 改善（<3s 软门禁） |
| watchlist 热 | 23-28ms | 11-21ms | ✅ |
| search（keyword 正确参数） | 20-35ms | — | ✅ |
| signal 600519 | sell/-1.5/data_available=true | 完全一致 | ✅ |
| factors/active | 97ms；census 见 §2.1 | census 由 valid=0/no_data=27 变 warn=12/no_data=15（R102 生效的直接体现） | ✅ |
| news/global | 8 条、level≥3 摘要 3/3 | 5/5 | ✅ 口径满足 |
| WS /ws/news | 单条推送 {type:'news', data:{title,content}} 内容真实 | 快照 886B | ✅ |
| WS /ws/portfolio | hello connected | 同 | ✅ |
| 刷新循环 | 板块 61s×3 连续、市态+情绪 ~120s、资讯 ~125s，数据非空（30 momentum rows / 11 hot plates / h15-m6-g8） | 同周期 | ✅ |
| data_health_check | **PASS 10/10** | 10/10 | ✅ |

---

## 4. 新发现问题（阶段 4）

### 4.1 R103（P2）：IC 历史回填每启重跑——动态跳过阈值被场外净值序列击穿

**症状**：两次 boot（12:59 首启、13:12 受控 restart）均执行完整回填并打印「历史回填完成：499
个交易日」，skip 分支日志「已回填…跳过」从未出现。每次重跑 ≈500 次 `_reg.compute()`，纯计算
实测 ~56s 后台 CPU。

**根因链（file:line + 数值）**：

1. 用户持仓含场外联接基金 **019633 国泰中证半导体材料设备主题ETF发起联接C**
   （portfolio_etfs 实测 28 只之一）；
2. 其 K 线缓存条目为净值序列 **658 点**（data/kline_cache.json rows['019633'] len=658，
   行内无 day 字段——走基金净值链路，不受新浪 datalen=500 管控）；
3. `main.py:831` `kline_depth = max(len(rws) for rws in rows.values())` = **658**；
4. `main.py:837` skip 判据 `_existing >= max(kline_depth - 30, 200)` = `502 >= 628` **恒假**；
5. 回填 upsert 幂等（ic_tracker.py:328 on_conflict_do_update）→ 数据无损、distinct 恒 502，
   但每次启动都白跑一次回填（IC-below-threshold 告警流 13:00:50→13:01:46 即 compute 主段
   ≈56s，整窗含池等待 ~2 分钟），**违背 R102 方案③「重填至 ≥ 深度-30 → 跳过（不每启重跑）」
   的设计意图**——该意图隐含假设「所有序列深度 ≈ datalen 上限」，场外净值序列打破之。

**归因**：架构边界遗漏（R102 方案评审 Round 1 曾预警「池含大量新 ETF 时误触发每启重跑」，
本例为其镜像变体：池含**超深历史**标的时永不收敛）。

**修复方案**：

- **方案 A（推荐）**：`main.py:831` kline_depth 只统计「K 线行」（行内含日期字段的序列），
  排除净值点列——生成器条件加一行过滤（如仅计 `rws[0]` 含 `day`/`date` 键的序列）。
  单点改、语义正（回填消费的 dates_ref 本就来自 K 线标的）。
  - 验收：restart ×2 出现「已回填（502 交易日 ≥ 可用 N-30），跳过」；负向：fresh 库（改名
    factor_ic_records 表模拟）仍触发完整回填至 ~499。
- 方案 B：阈值钳制 `min(kline_depth, 500)-30`——治标，把 500 写成新魔数，未来 datalen 再调
  又会失同步。
- 方案 C：DB 记录 watermark（app_config 存上次回填覆盖深度）——最准但引入持久化状态，超出
  最小修复原则。

**测试缺口映射**：test_r102_sina_datalen.py / test_ic_tracker.py 的注入工厂只造「均匀深度
K 线」标的（n_symbols×n_days 同深），无「混入超深净值序列」用例 → 阈值逻辑对异构深度无守卫
（详见 §7）。

**实施细化（Round 8，已达实施标准）**：

main.py:831-834 改后：

    kline_depth = max(
        (len(rws) for sym, rws in rows.items()
         if isinstance(rws, list) and rws and str(rws[0].get("date") or "").strip()),
        default=0,
    )

判据依据：`_sina_history_cb` 返回行统一规整为 `{"date": d["day"], "open": …}`（china_market.py:549，
date 恒非空）；场外净值序列行无 `date` 键（019633 实测仅旧格式 `day:""`）→ 被过滤。与回填
日期轴消费语义一致（main.py:856 同取 `r.get("date")`）。
守卫测试 `backend/tests/test_r103_mixed_depth_rows.py::test_kline_depth_ignores_nav_rows`：
rows={"510300":[500×含date行], "019633":[658×净值行]} → kline_depth==500；负向
test_all_nav_rows_falls_back：全净值行 → depth==0 → max(-30,200)=200 兜底不崩溃不误跳过。
边界：baostock/netease 路径同样产出 date 键（china_market.py:315 已核）。

### 4.2 R104（P2）：设计 factor_data_quality.ic_accumulation 口径错位——截面计数冒充交易日累计

**症状**：设计 697（full）`factor_data_quality.ic_accumulation` = `{median_samples: 14,
max_samples: 15, target_days: 250, note: "IC 积累中（中位 14/250 交易日…）"}`；而同刻
`/factors/active` 12 个 warn 因子 sample_count=444-502。**偏差 30-33×**，且 note 分支
`max_samples < MIN_TRADING_DAYS` 因 max≤池规模恒真 → **文案永远报「积累中」永不翻转**。

**根因链（file:line）**：

1. `strategy_design.py:1048` `_sample_counts = getattr(_freg, "_sample_counts", {})` ——
   读 registry 内存属性；
2. `factor_registry.py:1674-1681`：每次 `compute()` 产生有效 IC 批次时 `_sample_counts`
   被**整体覆盖**为其推导式结果——该值语义是「本批截面中该因子有非零值的 symbol 数」（≤池规模
   ~15），**不是累计交易日数**；
3. 启动 restore（factor_registry.py:1759-1764）曾从 DB sample_count（F25① 后语义=distinct
   trade_date）恢复正确值，但首个 compute() 即污染；
4. `/factors/active` 不受影响——`routers/factors.py:369/:392-394` 优先读 DB
   `count(distinct trade_date)`，仅在 DB 缺失时回退内存 → 双路径单一事实源分裂。

**归因**：「正文/meta 与结构化数值不同源」系统性根因（R95 类）的新变种；R96 加 ic_accumulation
维度时接错了数据源（出生即错）。

**影响**：设计元数据向用户谎报因子成熟度（实际已跨 250 门槛仍称「积累中 14/250」）。

**修复方案**：

- **方案 A（推荐）**：`strategy_design.py:_factor_data_quality_report` 改读与
  /factors/active 同源的 DB 口径（复用 `routers/factors._db_ic_sample_counts(db)` 或
  ic_tracker 等价查询；函数当前为纯计算无 I/O，需注入 db 会话或改为接收调用方传入的 counts）。
  - 验收：有回填历史的库上设计 fdq.ic_accumulation.max_samples≥250 且 note 翻转「样本充足」；
    负向：fresh 库 median=0 且 note 报「积累中」。
- 方案 B：registry 内拆分两个字典（截面计数改名 `_last_batch_symbol_counts`，不再占用
  `_sample_counts` 名字承载两义）——治本但动 compute 热路径与 restore 两处，影响面大。

**实施细化（Round 8，已达实施标准）**：

调用链事实：唯一生产调用点 strategy_design.py:924，位于 **async** `_build_market_context`
（:839）内 → 可直接 await DB。三处改动：

① ic_tracker.py 新增全量计数助手（单一事实源；routers/factors._db_ic_sample_counts 的同款
   SQL 迁移至此、router 改转发）：

       async def get_sample_counts_by_code(self, session) -> dict[str, int]:
           stmt = select(FactorICRecord.factor_code,
                         func.count(func.distinct(FactorICRecord.trade_date))
                         ).group_by(FactorICRecord.factor_code)
           return {c: int(n) for c, n in (await session.execute(stmt)).all()}

② 调用点 :924 改为：

       _db_counts: dict[str, int] | None = None
       try:
           from ..database import async_session
           async with async_session() as _db:
               _db_counts = await _ic_tracker.get_sample_counts_by_code(_db)
       except Exception as _e:
           logger.debug("[strategy_design] db sample counts unavailable: %s", _e)
       _fdq = _factor_data_quality_report(db_sample_counts=_db_counts)

③ `_factor_data_quality_report(db_sample_counts=None)`：:1048 改为
   `_sample_counts = dict(db_sample_counts) if db_sample_counts is not None else getattr(_freg, "_sample_counts", {}) or {}`
   ——注意该源同时喂 :1072 `_status_of(samples=…)` 分类与 :1082-1084 ic_accumulation；
   注入后 fdq 的 warn=0 vs /factors/active warn=12 分裂一并修复（预期，待单测验证）。

测试（扩 test_r96_factor_data_quality.py）：test_ic_accumulation_prefers_db_over_memory
——注入 {codeX:300} 且篡改内存计数为 5 → max_samples==300 且 codeX 分类非 no_data；负向
test_none_override_keeps_legacy——override=None 回退内存行为不变。

### 4.3 R105（P2）：M7/P1-1 强制核心锚未落地防御型方案（「环境性缺锚」归因失效）

**症状**：verify_e2e 四连 FAIL：
① `M7 defensive 核心层数 [2] ∉ [3,5]`（core=[512890,510050]）；
② `M7 defensive 含宽基锚(中证A500/沪深300)` FAIL（core_syms∩{510300,159338}=∅）；
③ P1-1 所有方案核心层含宽基锚 FAIL（防御型缺锚）；
④ P1-1 至少一方案核心层含中证A500 FAIL（159338 未进入任何方案的核心层）。

**证据更新（为何归因失效）**：round31/33 将 M7 FAIL 归因「159338 环境性缺锚」。本轮实证锚
**可用**：设计 697 correlation_warnings 含 [510300,159338]、[159338,510050] 近替代对（带实测
相关系数）→ 相关性宇宙包含 159338；平衡型核心已有 563360「A500ETF华泰柏瑞」w=20%（同指数不同
基金）。锚在池、在宇宙，却不在任何方案的核心层持仓。

**机制链（2026-08-22 会话第二轮排查修订——原「candidates 切片丢锚」假说已被证据推翻）**：

> **关键反转**：三处独立痕迹证明锚**曾被成功注入 allocs**——①strategy2 的
> wide_basis_high_corr 警告含 [159338,510500] r=0.945，而 `_correlation_matrix_for`
> 的键域仅限方案 allocs（strategy_design.py:1288-1291 实读，candidates 形参未参与
> codes 构建）；②strategy0 的三对 near_substitute（[510300,159338]/[510300,510050]/
> [159338,510050]，combined_weight≈当时权重和）意味着计算时 strategy0 核心层同时存在
> 这三只；③near_substitute_pairs(allocs) 宇宙同为 allocs（allocation_engine.py:805/
> :1616）。即：allocate() 的强制注入工作正常，**锚是在警告计算之后的某道后置工序被
> 剥除的**。

两段式缺陷（分属两个进程的独立证据线，任一单独成立即足以清空方案锚）：

- **段一（池层静默丢弃｜本地后端日志铁证）**：`backend.log.1` 当日 5 次池重建全部只出现
  `enforced mandatory 518880 -> defense`，510300/159338 从未被 enforce——它们未进入全市场
  扫描结果 flat（源降级态下 `etf_scanner` 成交额/规模门禁把真锚当「幽灵锚」剔除，即 P2-10
  防线误伤真锚），`ensure_mandatory` 的 `found=None` 分支**静默跳过、无任何 WARNING**
  （pool_balancing.py:141-160）。
- **段二（设计层后置剥除｜容器内设计 697 反推）**：allocs 中已注入的锚（强制注入权重档）
  在 wide_basis/near_substitute 警告计算之后被剥除。头号嫌疑 =
  `apply_risk_controls` 内 `remove_stale_candidates`（risk_controls.py:160 段——
  factor_matrix 缺 price/return 即逐标的剔除，round29 R77 全删事故同款条件；周末降级态
  恰好触发）；备选嫌疑 = P1-5 gate（三源拿不到涨跌 → 核心权重清零）。容器日志随资源回收
  灭失，无法直锤具体函数——实施时先在该路径补一行 removed 日志即可定位。

**门禁侧盲区（同记本项）**：P1-1 的 A500 断言只认 symbol∈{510300,159338} 或名称含
「中证A500」字面子串——563360 名称「A500ETF华泰柏瑞」不含「中证A500」→ 同指数合规锚被判缺。
门禁语义与 engine 的指数去重口径（`_dedup_same_index` 按 tracked_index/裸指数名归一）不一致。

**修复方案（2026-08-22 排查后修订版）**：

- **方案 A'（推荐，治段二设计层剥除）**：`remove_stale_candidates` 与 P1-5 gate 对
  MANDATORY_CODES **豁免删除**——锚无数据时保留 + WARNING 标注 degraded（对齐既有
  `MANDATORY_FLOOR=0.05`「强制锚永不被削减到地板下」的既有哲学，allocation_engine.py:303）。
  - 验收：降级态（周六盘后）提交设计任务 → 三方案核心层含 510300/159338 至少之一；
    verify_e2e M7/P1-1 四连转 PASS；**负向**：非锚标的缺数据仍正常剔除（防豁免扩大化）。
- **方案 B'（治段一池层静默跳过）**：`ensure_mandatory` 的 `found=None` 分支改为 WARNING
  （含 code/pool 状态）+ 用静态元数据构造兜底条目注入 core 层，K 线由后续 refresh_kline 补齐。
- **方案 C'（可选，治本）**：`etf_scanner` 成交额/规模门禁对 CORE_ANCHORS 白名单豁免——
  幽灵锚防线当年防的是 560600 冒充锚，白名单化不损失该防线。
- 门禁配套（原方案 B 保留）：verify_e2e 锚识别放宽为 tracked_index 归一化匹配（563360 类
  同指数基金计入「含 A500 锚」，与 `_dedup_same_index` 口径对齐）。

**实施细化（Round 8，已达实施标准）**：

A'-1 remove_stale_candidates 豁免——risk_controls.py 逐标的循环内（has_price 判定前）插入：

    if etf.get("symbol", "") in MANDATORY_CODES:
        logger.warning("[risk] mandatory anchor %s lacks price/return — kept (degraded)",
                       etf["symbol"])
        filtered.append(etf)
        continue

模块已可用 MANDATORY_CODES（risk_controls.py:71 既有引用）✓。
A'-2 P1-5 gate 豁免——strategy_design.py:615 `_degraded_core.append(...)` 前对
MANDATORY_CODES 成员跳过清零并 WARNING（services→engine import 方向合法）。

B' ensure_mandatory 兜底条目——pool_balancing.py found=None 分支改为：

    logger.warning("[pool] mandatory %s missing from scan — injecting static entry", code)
    pool[target].append({"symbol": code, "name": _STATIC_ANCHOR_META[code]["name"],
                         "tracked_index": _STATIC_ANCHOR_META[code]["tracked_index"],
                         "layer": target})

_STATIC_ANCHOR_META 定义于本模块顶部（两锚两条静态元数据；不从 allocation_engine 导入防
循环依赖）。K 线由后续 refresh_kline 补齐；若 K 线持续缺失，段二豁免（A'-1）保证不被剥除。

C' etf_scanner 白名单——成交额门禁判定处（etf_scanner.py:54 MIN_AVG_AMOUNT 常量、:259 附近
filter 表达式）对 symbol ∈ CORE_ANCHORS 豁免门槛（常量本地复制并注释同步义务，防引擎反向依赖）。

测试 test_r105_anchor_survives_degraded.py 三用例：①remove_stale 对缺数据锚保留、普通缺数据
标的仍剔除（负向防豁免扩大化）；②ensure_mandatory 在 flat 无锚时注入静态条目并 WARNING；
③scanner 白名单零成交放行 + 普通零成交标被剔。验收联动：降级态设计任务 → e2e M7/P1-1
四连转 PASS。

### 4.4 R106（P3）：fund_fetcher 收到非代码 symbol——脏映射值穿透到网络层

**症状**：后端日志每 60-120s 重复
`WARNING [fund_fetcher] HTTP/JSON error for 黄金9999: 'ascii' codec can't encode characters...`
——无效请求周期性重放 + 日志噪声。

**根因链（file:line）**：

1. `backend/data/etf_index_mapping.json` 存在脏映射 `518880 → "黄金9999"`（把上金所现货合约
   Au9999 当作 tracked_index 值）；
2. 组合定价链 `pricing.py:133-148`：收集持仓的 tracked_index →「黄金9999」不在指数行情 map
   → 进入 NAV 兜底 `:140 get_fund_nav("黄金9999")`；
3. `china_market.py:1452` 主源失败后 fallback `fund_fetcher.fetch_fund_nav("黄金9999")`；
4. `fund_fetcher.py:35` URL `fundCode=黄金9999` 含原始中文 → urllib ascii 编码异常 → None
   （优雅降级，但下一轮刷新原样重来，无记忆/无熔断）。

**归因**：数据质量（映射脏值）× 代码健壮性（入参无形态校验）复合缺陷。影响限于 518880 的
tracked_index 定价路径退化为 last_close 与日志噪声，不阻塞功能。

**修复方案（推荐 A+B 组合，均为小改）**：

- A：`etf_index_mapping.json` 修正 518880 映射值（黄金 ETF 的 tracked_index 应指向可用指数
  行情键，或置空走 NAV）；
- B：`fund_fetcher.fetch_fund_nav` 入口加形态守卫：symbol 非纯 6 位数字直接返回 None 并
  DEBUG 日志（fail-fast 不发无效请求）；
- 验收：重启后日志无该 WARNING；518880 定价仍有值（last_close 或 NAV）；负向：传入中文
  symbol 不再产生网络调用。

**实施细化（Round 8，已达实施标准）**：

守卫 fund_fetcher.fetch_fund_nav 入口首行（fund_fetcher.py:76 包装层）：

    if not (isinstance(symbol, str) and symbol.isdigit() and len(symbol) == 6):
        logger.debug("[fund_fetcher] skip non-code symbol %r", symbol)
        return None

映射修正：etf_index_mapping.json `"518880"` 值改为空串或规范指数名（走 NAV/last_close 定价）。
测试 test_fund_fetcher_guard.py::test_non_code_symbol_no_network——传「黄金9999」/None/
7 位数字 → urlopen mock 断言调用次数 0、返回 None；负向 test_valid_code_still_fetches：
合法 6 位码仍走网络路径（mock 200 正常解析）。

### 4.5 R107（P2）：策略检查报告表格「因子分」与理由「因子分」同页异源

**症状**：检查 820（规则兜底）逐标的表第 3 列「因子分」与同行理由中的「因子分 X.XX」数值不一致
甚至符号相反：159338 表格 1.02 vs 理由 0.02；512890 1.92 vs 0.02；159992 **1.63 vs -2.43**；
512000 -0.11 vs 0.61；019633 7.97 vs 0.60。读者可直接看到同页两个「因子分」打架。

**根因链（file:line）**：

1. 表格列：`strategy_check.py:1385-1393` —— `avg = mean(factor_breakdowns[sym].factor_scores
   的非零值)`：把 RSI(0-100)、KDJ(0-100)、动量 z-score 等**混杂量纲原始值直接算术平均**，
   且 `:1387` 剔除零值使 OTC 基金（全零）不参与、均值进一步漂移；
2. 理由列：同文件 `:1247/:1255/:1273` 用 `_score`（composite 复合评分，holdings_analysis.
   composite_decision.score 同源，如 159338=0.02/0.352 口径族）；
3. 两处同名「因子分」、异源异义——R95「正文 vs 结构化不同源」的规则报告内部变种。

**影响**：规则兜底报告（当前 LLM 受限时的常态输出）可读性受损，可能误导调仓判断。

**修复方案**：

- **方案 A（推荐）**：表格列改用与理由同源的 composite score（`s.get("composite_score")`），
  列头保持「因子分」单义；
- 方案 B：保留均值列但改名「原始因子均值（参考）」并在表尾注明口径——信息量更大但仍易误读。
- 验收：同一标的两处数值一致；负向：构造 composite≠mean 的用例断言不再出现双值。

**实施细化（Round 8，已达实施标准）**：

数据可得性已验证：表格所在函数 `_build_rule_fallback_report`（strategy_check.py:1183）仅服务
规则兜底路径（LLM 模式不生成此表，本轮实测 is_fallback=True 全 26 条均 rule 生成），其输入
merged_suggestions 全部来自 `_rule_based_suggestion`（:1150）——该函数体内 `_score` 即
composite 复合分（:1244-1277 reason 引用的同一变量），作用域直接可用。

两处改动：
① `_rule_based_suggestion` 返回 dict 增加键 `"composite_score": round(_score, 4)`；
② 表格列 strategy_check.py:1387-1388 改为：

       comp = s.get("composite_score")
       avg = comp if isinstance(comp, (int, float)) else 0.0

   （删除 fs_vals/avg 三行均值计算；fs/fb 变量若他处不用一并清理。）

测试 test_strategy_check_table_score.py::test_table_score_equals_rationale_score——构造
composite=0.5、factor_scores 均值 7.97 的输入 → 解析生成的 markdown 表格列 == 0.5 且与理由中
「因子分 0.50」同值；负向 test_no_double_value——同页不存在第二个不同数值的「因子分」引用。

### 4.6 R108（P2）：R102 回填管道丢弃 OHLCV 列——非 close-only 因子整体无法回填

> 2026-08-22 定稿后会话追问「新因子为什么不能像 R102 一样获取历史数据补齐」溯源产生，经与
> 用户讨论确认后追加本节。该发现同时暴露 round33 §8.3「受益因子 ~14 个」口径下的隐含盲区。

**症状**：15 个 no_data 因子中，凡输入含 high/low/volume 的纯 K 线因子——atr_14、vol_ratio、
vwap、amount_stability（volume fallback）、kdj_k/d/j 共 **7** 个——IC 样本仅 n=7-9
（vwap 冻结于旧积累期 n=245），而 close-only 因子 12 个被 R102 回填至 444-502 天。

**根因链（file:line）**：

1. `main.py:851-858` 构造回填用 kline 只装两键：`kline[sym] = {"close": closes, "dates":
   dates}` ——缓存行内明明携带 open/high/low/volume，被丢弃；
2. `main.py:888-892` truncated 展开写的是 `kd["open"][: i+1] if kd.get("open") else []`
   ——kd 恒无该键 → open/high/low/volume 恒为空数组；
3. 重放历史时：atr/kdj 输入 high=[] → pandas-ta 全 NaN → None；vol_ratio/vwap/
   amount_stability 的 volume fallback 遇 volume=[] → 长度不足 → None → 无 IC；
4. 日线持续循环走列式缓存（六列齐全，`_kline.py:83 _rows_to_columns`）→ 这些因子「今天能算、
   历史补不了」，只能从各自 daily 路径起点慢慢攒。

**证据链（三线独立印证）**：

| 证据 | 内容 |
|---|---|
| DB 日期分布 | 7 因子 IC 全部自 **2026-08-14** 起、n=7-9；对照 change_pct n=502（2024-08-01 起）、sma_5 n=499——回填只对 close-only 族生效 |
| 冻结样本 | vwap n=245 = 旧积累期整年长度（2025-08-22..2026-08-22），两次全量重放均未扩展它 |
| 家族分界 | 12 个 warn 清一色 close-only 族（sma×4/rsi/macd/bollinger/change_pct/return_1m/3m/price/signal.overall）；未回填族清一色依赖 high/low/volume |

**边界诚实（D2）**：这批因子 daily 路径起点 2026-08-14 对应的触发 commit 未逐一考证（候选
解释：symbol_extra 字段可达性变化或零占位行为修复）；不影响根因结论——backfill 缺列使其无法
获得历史，由源码 + DB 双证。

**修复方案**：

- **方案 A（推荐）**：`main.py:851-858` kline 构造带齐五列（行内已有数据），truncated 按索引
  直接切片。改动集中在两处 dict 构造。
  - 验收：单测注入含五列的 rows → 回填后 atr_14 等 7 因子 distinct trade_date ≥ 250；
    **负向**：仅 close 列时这些因子保持 no_data（防回归现状）。
- **与 R103 强联动**：修 R108 后下次启动将触发真正意义的全量重放（7 因子历史首次入算），
  必须与 R103（skip 阈值修复）**同批落地**，否则每启重放成本翻倍；upsert 幂等保证数据安全。
- 成本：pandas-ta ATR/KDJ 使单次 compute 变重，回填窗口较当前 ~56s 显著上升（量级实施时实测）。

**效果预期**：7 因子立即跨过 250 门槛进入显著性判定。「自然积累中 13」的精确拆解 =
**7（R108 可立即回填）+ 6（premium_discount/ln_mcap/ln_float_mcap/news_heat/
institutional_holdings_change/industry_diversification，静态快照类只能前向）**。

**实施细化（Round 8，已达实施标准）**：

main.py:851-858 改后（四列与 close 同条件收集，列长恒等）：

    kline[sym] = {
        "close": closes,
        "dates": dates,
        "open":   [r.get("open")   for r in rws if r.get("close") is not None],
        "high":   [r.get("high")   for r in rws if r.get("close") is not None],
        "low":    [r.get("low")    for r in rws if r.get("close") is not None],
        "volume": [r.get("volume") for r in rws if r.get("close") is not None],
    }

sina 行实测携带全部五列（china_market.py:549）；truncated 展开（:887-893）的 `kd["open"]`
条件展开自此自然生效、无需改动。
守卫测试 = G6（§6.4）：工厂五列化 + test_backfill_covers_high_low_volume_factors——注入含
high/low/volume 的 rows → 回填后 atr_14/kdj_k distinct trade_date ≥250；负向：仅 close 列
时保持 no_data。与 R103 同批实施（见上强联动说明）。

### 4.7 数据源债修复设计（T-A / S-A，回应 round33 §8.3「R102 不解决」遗留）

**T-A：tracking_error 基准收盘管道**

- 现状：`factor_registry.py:468` 需要 `data["benchmark_close"]`，系统无任何提供方 → 函数返回
  0.0 → 被零值过滤器吞掉 → 永不产 IC（实测 n=0）。
- 方案 T-A：池内 ETF 已有 tracked_index 字段（etf_index_mapping.json + F10 enrich）→ 新增
  「基准名 → 指数代码」解析层（常用基准可枚举：沪深300→sh000300 等）→ 复用既有 CN 指数 K 线
  降级链（Sina s_sh → mootdx → Tencent）拉基准收盘 → compute 数据装配处注入 benchmark_close。
- **关键红利**：指数历史 K 线可得 → 管道接通后立即可回填 ~500 天 TE IC（无需等一年）。
- 前置探针（D1，实施前必做）：①池内 tracked_index 覆盖率与规范化程度（已知脏值「黄金9999」
  ——与 R106 同源，共用映射治理）；②常用基准代码枚举覆盖率抽测；③指数历史深度 ≥250 天验证。
- 风险边界：境外/商品 ETF 基准（纳指、金价）境内指数源不可得 → 诚实降级标注，不硬凑代理。

**S-A：shares_change 每日份额快照表**

- 现状：`factor_registry.py:489` 需要外部字段 `shares_change_20d`，无提供方 → 恒 0.0（n=0）。
- 方案 S-A：每日定时任务抓取 akshare `fund_etf_spot_em` 最新份额字段 → 落 `(symbol, date,
  shares)` 快照小表 → 因子 = 当前份额 / 20 交易日前份额 − 1。
- **无法回填**：免费源无逐日份额历史 → 上线起前向积累，~20 交易日后开始产出、~250 天达标。
- ~~前置探针：确认 spot_em 份额字段存在性与单位（份/亿份）。~~
  **✅ 探针已通过（2026-08-22 单次实测，akshare 1.18.81）**：`fund_etf_spot_em` 返回 1584 行
  ×37 列，含 **「最新份额」** 字段——单位为**份**（510300 实测 237.4 亿份；全池中位 2.4e8、
  最大 7.6e10，量级判定非亿份）；另有 `数据日期`/`更新时间` 字段可直接作快照表的日期轴。
  **附带发现**：同源含 **IOPV实时估值 / 基金折价率** 列 → 同一张快照表可顺带为
  `etf.premium_discount` 提供真实 IOPV 输入（当前其 nav 走 fund NAV 链路，快照表可作为
  盘中增强源）。成本注意：全量抓取 ~19s（15 页分页），每日单次任务可接受，须以
  `asyncio.wait_for` 包裹（复杂度审计约定）。

**T-A 实施细化（Round 8：探针规格 + 注入点锚定；最终代码待探针通过后出，D1 门控）**：

D1 探针脚本规格（一次性，`scripts/probe_t_a.py`）：
① 从 data/kline_cache.json + instruments 表导出池内 tracked_index 清单 → 规范化（剥「指数」
   后缀/公司名，复用 `_extract_index_concept` 口径）→ 与内置 INDEX_CODE_MAP 匹配 → 输出
   覆盖率报告（目标：池权重覆盖 ≥80%）；
② 对命中 top-10 指数代码逐个拉新浪日 K（datalen=500）验证可得性与深度 ≥250；
③ 结果 JSON 存 diag/out/probe_t_a.json 作为实施依据。

注入点锚定：compute() 的 per-symbol enriched 装配处 factor_registry.py:1600-1616
（`enriched = dict(market_data.get(sym, {}))` 起）追加：

    enriched["benchmark_close"] = benchmark_closes.get(sym, [])

benchmark 序列来源 = hub 新缓存 `_benchmark_close_cache`（tracked_index→指数代码→既有指数
K 线链拉取，60 日窗与列式缓存对齐）。装配前置校验 `len(bench)==len(close)` 否则不注入
（_compute_tracking_error 自带长度守卫 :477）。
开放问题（探针回答）：①行业/主题 ETF 基准名规范化命中率；②境外基准占比（决定豁免清单规模）。

**S-A 实施细化（Round 8：探针已过，设计至实施标准）**：

① 表 DDL——models 新增 FundShareSnapshot（随现有建表模式）：

       fund_share_snapshots(symbol TEXT NOT NULL, date TEXT NOT NULL,
                            shares REAL NOT NULL, updated_at DATETIME,
                            PRIMARY KEY(symbol, date))

② 抓取器 fund_fetcher.py 新增 fetch_fund_share_snapshot() -> list[dict]：run_in_thread 包裹
   ak.fund_etf_spot_em()（~19s/15 页分页），抽取 [代码, 最新份额, 数据日期] →
   [{symbol, date, shares}]；timeout=60。
③ 调度：main.py lifespan 注册独立后台任务 _fund_share_snapshot_task——while True: sleep(3600)
   + 北京时间当日未抓过才抓的日期守卫，复用既有后台任务注册模式。
④ 因子接线：hub._build_symbol_extra（hub/_kline.py:352）增加 shares_change_20d 字段——读快照表
   （当日 vs 20 个交易日前），样本不足 20 日返回 None；`_compute_shares_change` :491-494 对
   None 返回 0.0 → 进零值过滤器不产 IC ✓ 语义正确（不写假 0 天）。
⑤ IC 自动接入：daily persistence loop 经 compute_periodic_ic 正常消费，零额外管道。
验收：上线 ~20 个交易日后 shares_change 的 n 开始 >0；负向：akshare 挂掉时任务静默重试
不崩、不阻塞主流程。

### 4.8 大面积 warn 的结构性归因与评估口径改进（M-A，讨论级）

本轮 12 warn / 0 valid 引出「是否候选池/设置不合理」的讨论，结论分三层：

1. **门槛严（设计使然）**：|IR|≥0.5 要求 mean(IC)/std(IC) 过半——截面 N≈30 时单日 IC 随机
   波动 std 理论约 0.19，隐含需平均 |IC|≥0.08 且长期方向稳定，属「强因子」标准（F25① 虚假
   翻绿教训后的刻意收紧）。0 valid 属诚实结果，非故障。
2. **候选池同质化（固有权衡，非 bug）**：实测近替代对相关性 159915×563360=0.949、
   159338×510500=0.945；return_3m t=0.29 连均值显著性都无——动量在同质化 ETF 截面上区分度
   塌缩的直接实证。扩池可增截面信息但会把低流动性标的引入配置建议，trade-off 不建议先动。
3. **可改进的两处设置**：
   - **M-A 多窗口 IC 并列**：现所有因子按 window=1（次日收益）考核，与系统配置型定位（周-月
     调仓）错配——return_3m 这类配置信号天然吃亏。`compute_periodic_ic` 已支持 window 参数
     （ic_tracker.py:194），可并列展示 window=1/5/20 三档。统计功效边界：window=20 有效样本
     ≈25 期，需依赖既有 Newey-West 修正并接受更长积累期——实施前须探针验证功效。
   - **技术族正交化合成（远期）**：signal.overall IR=0.061 低于多数单因子——sma/rsi/macd/
     bollinger 高度共线，简单加权合成等于同一信号重复计数，噪声未被分散；正交化/残差化后再
     合成才有效（改动大，仅记录方向）。

### 4.9 环境性观察（非 R 系列）

- **O1 timeline e2e 1.9s > 1.0s gate**：诊断负载态伪失败（round31 已记载同类）；同轮
  round19 边界用例 timeline 冷态 **10ms** PASS、metrics 5ms PASS → 服务本身健康。
- **O2 Lighthouse 首页回落**：67-68 vs round33 的 76（TBT 0→~650ms、SI 4.8→9.0s）；采样期间
  后端正并发 IC 回填重跑 + 设计/检查任务 + 刷新循环 → 负载态采样。Dashboard 99/100/100/91 与
  round33 持平。硬门禁 Performance≥60、CLS<0.0007<0.1 均过。**已知性能债登记**：首页 TBT
  待空闲态复测。
- **O3 ETF 记录稀疏 ×4 / etf_specific no_data=6 / sentiment no_data=1**：周末源中断 + IC
  积累期（no_data 由 round33 的 10 降至 6，方向改善），待交易时段复测。
- **O4 LLM 主源故障链**：opencode_zen 400 Bad Request（13:51:01）→ DeepSeek 兜底但配额节流
  （llm_quota_gate 多次 throttle 6.3s/0.5s）→ strategy_check LLM 81.4s 超时。属外部服务
  可用性问题，R95 维持「待 LLM 恢复复测」。

---

## 5. 分析结果质量审查（阶段 3，四问法）

**审查对象**：设计 697（full）三方案 + 策略检查 820 报告逐句。

### 5.1 判断质量矩阵

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论 | 修复建议 |
|---|---|---|---|---|---|
| 设计 697「当前市态未触发预期收益调整（震荡市态调整机制）」 | 事实引用 | structured market_regime="range_bound"；check 820 市态=震荡；两路径一致 | ✅ 一致 | 合理 | — |
| 设计 697 防御型「核心 45% · 卫星 20% · 防御 10% · 现金 24%」 | 事实 | structured positions Σ=0.75+cash 0.242≈0.99（舍入） | ✅ 自洽 | 合理 | — |
| 设计 697 平衡型核心含 563360 A500ETF w≈20% | 事实 | strategies[1].core 含 563360 | ✅ | 合理 | — |
| 设计 697 correlation_warnings「159915×563360 相关 0.949 高相关削减」 | 事实（实测相关） | corr 基于池 K 线实算；周末历史数据可得 | ✅ | 合理 | — |
| 设计 697 ic_accumulation「IC 积累中（中位 14/250）」 | **错误事实**（口径错位） | 实际 444-502（§4.2） | ❌ 与 DB 矛盾 | **失效 → R104** | 方案 A 修源 |
| check 820「159338 因子分 0.02（中性），信号 buy，hold」 | 事实（composite 0.02/structured 0.352 族） | holdings_analysis composite_decision.score | ✅ | 合理（但见表格分叉行） | — |
| check 820 表格「159992 因子分 1.63」vs 理由「因子分 -2.43（偏弱）」 | **内部矛盾** | §4.5 异源实锤 | ❌ 自相矛盾 | **需修正 → R107** | 方案 A 统一同源 |
| check 820 场外联接 11 只统一「-0.20 中性 hold」 | 事实（诚实降级） | degraded=true + momentum=0（无盘中行情可评） | ✅ 周末盘后合理 | 合理 | — |
| check 820「关注 RSI 进入超卖区（<30）」 | 事实核对 | strategy_check.py:1270 模板原文正确（初读 mojibake 误判「超买」已排除——四问第 1 问防臆断的价值案例） | ✅ | 合理（排除嫌疑） | — |
| check 820「分项覆盖 38.5%」 | 事实 | coverage.coverage_pct 与结构化一致；round32/33 同口径 | ✅ | 合理（R87 持续成立） | — |

### 5.2 汇总

- **可采信 N=8** / **需修正 M=2**（R104 ic_accumulation 失效、R107 双「因子分」矛盾）/
  臆断 K=0 / 失效并入 M。
- 总体评价：设计/检查的**分配与建议主干可信**（权重自洽、信号有源、降级诚实）；两处 meta/
  表格层口径病（R104/R107）不影响配置逻辑但直接误导阅读——与 R94/R95 同族的「多路径数值
  不同源」根因第三次显形，应在防护体系中升格为一类专项守卫（见 §7.3）。

### 5.3 数据准确性抽查

- 权重和：三方案 Σweights+cash ≈1（0.99-1.00，舍入内）✅；权重未归一化约定未被破坏 ✅
- 占位检测：momentum 0 个 0.300；technical.signal.overall 有真实分布 ✅
- 新鲜度：fdq.data_available_pct=0.1868 与 degradation.pool_degraded=true 诚实并存；
  data_precision mode=coarse（81.3% 缺失→粗档展示）链条自洽 ✅
- 价格/涨跌：设计表今日涨跌列有真实值（-1.06%~+1.96%）✅（周五收盘快照，周末合理）

---

## 6. 测试防护体系缺口分析（阶段 4 强制）

### 6.1 防护体系现状（本轮实测）

| 层 | 状态 | 本轮抓到 | 抓不到 |
|---|---|---|---|
| 后端单测（2537 passed @38a194d） | ✅ 已知绿 | R102 URL 守卫/回填跨门槛 | 异构深度缓存（R103）、_sample_counts 双义（R104）、报告双「因子分」（R107） |
| verify_e2e（279/291） | ⚠️ 12 FAIL | **M7/P1-1 四连 FAIL 抓到 R105** ✓；timeline/记录稀疏等环境噪声 | R103（回填行为无断言）、R104（fdq 无数值断言）、R106（日志噪声无守卫）、R107（报告文本无数值一致性断言） |
| data_health_check（10/10） | ✅ | 源可达性/池健康 | 因子元数据口径类（R104） |
| patrol --full | 未重跑（沿 round33 先例，引 38a194d pre-commit 全绿基线） | — | — |
| runtime 验收脚本（verify_round32_runtime） | ✅ PASS=5 FAIL=0 | R99-R101 | M7 SKIP 分支的池来源与 e2e 不同（工具间口径差，记待办） |
| 前端 npm test（499）/Lighthouse | ✅/⚠️ 负载回落 | — | — |

### 6.2 逐发现映射（为什么现有防护没拦住）

| 发现 | 最应拦截的防护层 | 为何未识别（具体断言/阈值） | 应补的守卫 |
|---|---|---|---|
| R103 每启重跑 | 单测（回填行为） | test_ic_tracker 工厂只造同深 K 线；无「skip 分支被异构深度击穿」用例；e2e 不看回填日志 | 单测：混入 len=658 无日期序列 → 断言第二次调用走 skip（mock depth 计算） |
| R104 ic_accumulation 口径 | 单测（fdq 数值） | test_r96_factor_data_quality 只断言字段**存在**与两维并列形状，未断言数值与 DB 同源 | 单测：注入已知 DB counts（如 300）→ fdq.ic_accumulation.max_samples==300；负向：compute 覆盖后 fdq 不随之漂移 |
| R105 锚未落地 | verify_e2e M7/P1-1 | 门禁在跑且抓到了（本轮唯一立功防线）；但根因侧（candidates 切片丢锚）无单测定位 | 单测：池含锚 → allocate 结果三方案至少一个 core 含锚；后置校验 WARNING |
| R106 fund_fetcher 中文名 | 单测（入参校验） | fetch_fund_nav 无形态守卫测试；日志噪声无任何门禁监听 | 单测：fetch_fund_nav("黄金9999") 不触网返回 None（mock urlopen 断言 0 次调用） |
| R107 双「因子分」 | 报告文本断言 | e2e 对 report_text 只验「非空/含关键字」（HTTP 200 式宽松断言），无数值一致性检查 | 单测：构造 composite=0.5、raw_mean=7.97 用例 → 断言表格值==composite（或列名已区分口径） |
| R108 回填丢列 | 单测（回填覆盖面） | test_ic_tracker 工厂只构造 {close, dates} 两键——**测试数据形状镜像了生产缺陷**，断言「distinct 提升」被 close-only 因子满足，缺列完全无感（§6.3 第 2 类根因的元案例） | G6：工厂五列化 + 非 close 因子覆盖断言 |

### 6.3 系统性根因归并

1. **【round2/31 已归纳，本轮第 3 次显形】多路径数值不同源**（正文 vs 结构化 vs meta）：
   R94→R95→R104→R107 同族。守卫停留在「字段存在性」层，缺「跨路径同源性」断言。
   **结构性缺口：缺一类「同一业务量在不同出口必须同值」的专项测试基座**。
2. **【新】测试工厂数据同质化**：K 线工厂全同深、因子值分布理想 → 异构/退化输入（超深净值
   序列、全零 OTC、混杂量纲）路径零覆盖。R103/R107 皆源于此。
3. **【新】「静默跳过型」分支无行为断言**：ensure_mandatory/强制注入/回填 skip 都是「不满足
   即静默 return」，单测只测 happy path，else 分支永不被执行检验（R103/R105 共性）。

### 6.4 补齐设计（独立方案，随各 R 修复并行实施）

- G1（R103）：`tests/test_ic_tracker.py::test_backfill_skip_with_mixed_depth_rows`——
  mock rows={A:[500 K线行], B:[658 净值行]}，断言 depth 取 500（过滤后）而非 658。
- G2（R104）：`tests/test_r96_factor_data_quality.py::test_ic_accumulation_matches_db_counts`
  ——注入 DB counts 断言同值；负向：篡改 registry._sample_counts 后 fdq 不变。
- G3（R105）：`tests/test_allocation_anchor_injection.py::test_core_anchor_reaches_core_layer`
  ——池含 510300/159338 的 allocate 冒烟 → 断言至少一方案 core 含锚；后置校验分支单测。
- G4（R106）：`tests/test_fund_fetcher.py::test_non_code_symbol_no_network`——中文/空 symbol
  直接 None，urlopen mock 计数为 0。
- G5（R107）：`tests/test_strategy_check_report.py::test_table_factor_score_matches_rationale`
  ——解析生成的 markdown 表格列 == 理由中引用值（负向：旧实现必 FAIL）。
- G6（R108）：test_ic_tracker 工厂 rows 扩展为五列（close/open/high/low/volume）+ 新增用例
  `test_backfill_covers_high_low_volume_factors`——断言 atr_14/kdj_k 等回填后 distinct
  trade_date 同步 ≥250；负向：仅 close 列时保持 no_data。现有工厂只造 close/dates 两键，
  守卫形状镜像了生产缺陷——这正是它抓不到 R108 的原因。
- **负向约束**（防过度断言）：G1-G5 全部基于注入/mock 数据，不断言真实数据源行为（吸取 R4-07
  极端行情误报教训）；数据源类波动继续走「诚实降级标注」而非硬 FAIL。

---

## 7. 待交易时段/后续复测项

- **R95 LLM 正文路径**（连续第三轮受限）：LLM 服务恢复后提交策略检查，验证
  `_reconcile_report_numbers` 一致性覆盖。
- **O2 首页 Lighthouse 空闲态复测**：容器静置 5 分钟后采样，对照 round33 基线 76。
- **O3 etf_specific 因子产出**：交易日盘中复测 no_data 是否继续收敛（6→更低）。
- **E1 HK/US 中文名搜索**（沿 round33 待办）：akshare 港股源恢复后复测腾讯中文名解析。
- **patrol --full**：下一实施轮验收期执行（本轮沿 round33 先例引用 38a194d 全绿基线）。
- **M-A 功效探针**：现有 502 天样本上 window=20 重叠 IC 序列的功效验证（决定多窗口并列是否
  值得实施，见 §4.8）。
- **T-A/S-A 前置探针**：tracked_index 规范化覆盖率普查（与 R106 映射治理合并）、
  fund_etf_spot_em 份额字段确认~~——探针通过才进实施清单（D1 约定）~~
  **（S-A 探针已于 2026-08-22 通过，见 §4.7；T-A 待做）**。
- **§12 巡检 P0 三件套立项决策**：startup 行为审计 / 因子样本增长率 / 日志噪声检测——
  纯脚本 ~300 行，建议随第一批实施（R104+R107）捎带或独立成批，等用户拍板。
- **§13 pre-commit 卫生级微调**：①mypy 缺失静默跳过补 WARNING（2 分钟）；②AGENTS.md
  「13 段」数字漂移修正为 15 段清单——建议随第一批捎带；③子 shell 化重构单独一个 commit
  （纯结构重构需独立验证）。

> **当前状态**：容器全链路复验完成。R102 容器内首验通过；R93-R101 无回归；新发现
> R103-R108 已细化至方案级（含 file:line 根因链 + 方案 A/B + 验收负向断言）；数据源债与
> 评估口径改进给出 T-A/S-A/M-A 讨论级设计（S-A 探针已过）；§12 巡检体系优化设计与
> §13 pre-commit 门禁评估（15 段实测，5 个卫生级改进点）已入档。R105 断点经第二轮排查
> 闭合为两段式缺陷。
> **未写修复代码、未 merge、未 push**。等待用户决策：
> ① 是否「开始实施」，推荐批次：**第一批 R104+R107**（治误导元数据与报告矛盾，改动小收益
> 直接，可捎带 §12 P0 三件套 + §13 微调①②）→ **第二批 R103+R108 同发**（回填批次必须捆绑，
> 否则重放成本翻倍）→ 第三批 R105 → 第四批 R106 → T-A/M-A 探针后再定；
> ② 资源回收（docker compose down，已执行）；③ 旧轮归档（round33 已移入 docs/archived/，
> 工作区待 commit）。

---

## 8. 多轮 review 记录（阶段 5，Round 1-3）

### Round 1（事实核对：file:line / 数字 / commit 与代码与 git 比对）

- **发现清单**：
  ① F1：§4.3 原稿「防御锚 518880/511090 三方案均在持」不实——实测 strategy0=[511090,518880]、
     strategy1/2=[518880]（511090 仅防御型，符合 round22 defense_count 门控设计）；原表述会
     误伤「强制标的链路存活」论证的精度；
  ② F2：§4.1「白跑 ~56s CPU」量纲含混——56s 是 IC-below-threshold 告警流标定的 compute 主段，
     整窗含池等待 ~2 分钟；
  ③ F3：§3 R93 行证据为容器侧单边查询，卷共享可双向加固。
- **修改清单**：F1 → §4.3 重写第 1/3 步（defense 门控事实 + 断点定位措辞收敛为「②→③ 之间
  候选切片环节，待实施轮单测定位」）；F2 → §4.1 第 5 步改写并标注告警流起止时间戳；
  F3 → §3 R93 行补宿主侧同文件查询一致（502/6705 双侧实证）。
- **其余抽检全对账**：china_market.py:536/:544、main.py:831/:837/:909-912、
  strategy_design.py:1048、factor_registry.py:1674-1681/:1759-1764、routers/factors.py:369/
  :392-394、pricing.py:133-148、fund_fetcher.py:35、strategy_check.py:1385-1393/:1270、
  pool_balancing.py:136-160、allocation_engine.py:392-412/:300 与源码逐一相符；数字类
  （distinct=502/rows=6705/range、census 四值、momentum 值域、fdq 0.1868/0.967、corr
  0.949/0.945、Lighthouse 全套、watchlist 冷热、e2e 279/291、镜像 ID/时间戳、commit 38a194d
  diff stat）与接口响应/日志/git 输出逐一相符。

### Round 2（逻辑一致性）

- **发现清单**：无新增修改项。专项核查：①数字口径跨章节一致（502/6705 出现于 §0.1/§2.1/
  §4.1 同值；fdq 两值同源引用；census 四值三处一致）；②结论-证据互证（R105 的「归因失效」
  由相关性宇宙 + 563360 在持双证据支撑，未越界断言根因已闭合——末端断点诚实标注待实施轮）；
  ③§6.2 防线映射与实测表现吻合（唯一立功防线 verify_e2e 抓 R105，其余四项均为「宽松断言
  抓不到」类别，与 §6.3 根因归并自洽）；④§7 实施顺序理由与 §4 各项影响面一致。
- **修改清单**：无。

### Round 3（完整性）

- **发现清单**：模板要素逐项盘点——环境构建✓、对照矩阵✓（含修复前后对比：245→502、
  no_data=27→15）、新发现机制链+方案A/B+负向验收✓、四问矩阵✓、防护缺口分析✓、D3 窗口
  标注✓（§0.3 + §7）、资源回收与决策点✓（§7 末状态块）。补一处完备性增强：runtime 验收
  脚本与 e2e 的池来源口径差已在 §6.1 记为待办，避免下轮误读 SKIP 语义。
- **修改清单**：无正文改动（完备性确认通过）。

### Review 结论

三轮共修正 3 处（1 处事实错误 + 2 处表述加固），逻辑一致性与完整性通过。文档达到
「可交付实施决策」标准：R103-R108 方案均带 file:line 根因链 + 方案 A/B + 含负向断言的
验收标准，等待用户「开始实施」指令。（Round 4 追加 R108 后同标准，见下。）

### Round 4（追加轮：R108 + T-A/S-A/M-A 整入，2026-08-22 会话追问）

- **触发**：定稿后用户追问两问——「新因子为什么不能像 R102 一样获取历史数据补齐」「数据源
  未接入能否修复」——溯源产生 R108；讨论确认后用户指示整理入档。
- **事实核对**：
  - `main.py:851-858`（kline 两键构造）与 `:888-892`（条件展开恒空）源码复核 ✓；
  - DB 日期分布实测复核 ✓：7 因子 IC 全部自 2026-08-14 起 n=7-9、change_pct n=502、
    sma_5 n=499、vwap n=245 冻结于旧积累期整年；
  - `factor_registry.py:468/:489` 缺失输入返回 0.0 → 被零值过滤器吞掉的行为链复核 ✓；
  - 12 个 warn 因子逐一对码确认 close-only 族属性 ✓。
- **数字勘误**：会话中曾把 R108 影响面误计为 5 个因子（kdj 三码误当一个 + 漏 amount_stability
  的 volume fallback 与 vwap），文档定为 **7**；「自然积累 13」= 7（R108 可回填）+ 6（真前向）
  校验通过（15 no_data − 2 个 n=0 数据源债）。
- **一致性**：§0 摘要（新发现 6 项）、§0.2 判定表、标题（R103-R108）、§4.6-4.8 新节与原
  环境性观察节重编号为 §4.9、§6.2 映射行 + §6.4 G6 守卫、§7 待办与决策批次、末尾状态块已
  同步更新；文件名同步改为 round34-container-reacceptance-r102-r108.md。
- **诚实标注**：7 因子 daily 路径起点 2026-08-14 对应的触发 commit 未逐一考证（不影响 R108
  根因结论）；M-A/T-A/S-A 均为讨论级方案，实施前各需前置探针（D1 约定）。

### Round 5（追加排查轮：R105 断点闭合 + 遗留疑点清账，2026-08-22 晚）

> 用户授权「需要继续排查的部分，现在可以排查」后执行；结论已回写 §4.3（机制链修订），
> 本节存排查过程与剩余项。

- **✅ task 734 终态闭环**：DB tasks 表实测 `status=completed`（created 06:09:47Z → completed
  06:11:25Z，**98 秒**，record_id=705，stage=报告完成）。e2e「120s 未完成」FAIL 定性为
  「full 质量 LLM 报告耗时贴近轮询窗口边缘的竞争」，非任务挂死——与 R95 的 LLM 慢同源，
  归类环境性负载。
- **✅ R105 断点闭合（重大修订）**：原「candidates 切片丢锚」假说被三处痕迹推翻（详见
  §4.3 修订版机制链）——锚曾被注入 allocs，系警告计算后被后置工序剥除；两段式缺陷 =
  ①池层 flat 缺锚 + ensure_mandatory 静默跳过（本地 backend.log.1 铁证：当日 5 次池重建
  仅 enforce 518880）；②设计层 remove_stale_candidates/P1-5 gate 降级态剥除（头号嫌疑，
  容器日志灭失未直锤）。修复方案替换为 A'/B'/C'。
- **✅ R106 映射全量扫描**：etf_index_mapping.json 共 80 条，真脏值仅 `518880→黄金9999`
  一条；另 `159087→细分化工`、`512400→有色金属` 缺「指数」后缀属规范化欠佳（低危）；
  境外基准（日经×3、纳指×3 等）8 条归 T-A 探针边界处理。治理范围比预想小。
- **✅ R108 起点考古**：IC 起点 2026-08-14 与 round22/23 批次（3269c8b..8841dda，2026-08-13/14
  落地，含 6e6f2be「factors IC pipeline」、e9e4f5c「factor stats P0」）时间吻合——最可能
  触发为该批因子统计修复使这些因子的 daily IC 开始产出。精确到 commit 的考证不阻塞 R108 修复。
- **✅ runtime vs e2e 口径差澄清**：verify_round32_runtime.py 无独立池查询代码——其 M7 SKIP
  判据来自设计响应侧信息，与 e2e 的差异实为「设计时池快照 vs 脚本判断逻辑」的时间差/口径差，
  非双数据源 bug。降级为备注，不立专项。
- **❌ 未排查（证据灭失）**：`/health` e2e 运行中超时 ×2——容器日志随 docker compose down
  灭失，无法回溯阻塞源。下轮容器诊断空闲态+负载态对照复现；若复现即升级新 R。
- **边界**：本轮文档已被并行会话追加 §9 前端 UI 诊断（R109-R121，Playwright 实测 + 代码级
  静态验证，同样只方案未实施）——R109 起编号已被占用，本节排查结论均并入既有 R 编号，
  不新增系列号。

### Round 6（追加轮：§12 巡检体系优化设计，2026-08-22 晚）

- **触发**：用户要求 review 巡检体系（「运行过程中的问题尽量通过巡检就能发现」）。
- **事实核对**：patrol 九 stage 清单经 patrol.py:56-80 实读核实（L1-unit/L2-e2e/L2-health/
  L2-smoke/L3-perf/L4-routes/L4-purity/L4-async/L5-frontend，diff 模式含 L2-smoke 与否以
  :72 注释为准）；data_health_check 输出结构实读核实。
- **内容**：漏检对照表以 R103-R108 + vwap 冻结 + /health 超时为样本；盲区归纳六类；
  改进方案 P0 两件套/P1 三项/P2 方向，落点均为新脚本或既有脚本扩展，零生产代码改动。
- **一致性**：P0 各断言与 §4 的 R103/R105段一/R106 根因一一对应；G1-G6 单测守卫与 §12 巡检
  分工互补不重叠（单测管函数级、巡检管行为级）；WARN 起步纪律与性能软门禁哲学一致。
- **完整性**：§0.2 判定表、§7 待办、末尾状态块已同步。

### Round 7（追加轮：§13 pre-commit 门禁体系评估，2026-08-22 晚）

- **触发**：用户要求评估 pre-commit 门禁合理性并找改进点。
- **事实核对**：`.githooks/pre-commit` 全文 487 行实读，15 段清单、触发面、跳过开关逐段
  过堂（含 :86-88 顺序设计、:245 mypy 静默跳过、:286-299 daemon case 分支、:355 凭据
  三重校验、:412 verify_perf 自指触发等行号级证据）。
- **关键结论**：结构健康定位清晰；R103-R108 经绿灯提交非其失职（守代码结构与提交纪律，
  运行时行为归 patrol/e2e）；改进全为工程卫生级——P1 两项（子 shell 化重构/mypy 缺失
  提示）、P2 三项（13 段数字漂移/skip 不对称标注/verify_perf 移交标注）；明确不建议
  为 R 系列新增门禁段或塞 e2e 进 pre-commit。
- **一致性**：与 §12 分工互补——pre-commit 管提交纪律（快），巡检管运行时行为（全）；
  G 系列单测落地后自然获得 pytest 档拦截力，无需新门禁段（符合治理约定①）。
- **完整性**：§0.2 判定表、§13 新节、末尾状态块决策点已同步。

### Round 8（方案达标度审计 + 细化至实施标准，2026-08-22 深夜）

- **触发**：用户要求对全文档多轮 review+修改，重大修改细化到实施标准、不开始实施。
- **达标度审计结论**（对照 round33 §8.2 先例：file:line 锚 + 改后代码 sketch + 含负向测试
  断言 + 边界条件）：R103/R104/R105/R106/R107/R108 六项由「方向级」补齐至「实施级」——
  各节新增**实施细化**块（精确改后代码 / 守卫测试名含负向 / 边界与成本）；T-A 给出 D1 探针
  脚本规格与注入点锚定（factor_registry.py:1600-1616 enriched 装配处），最终代码按约定探针
  通过后再出；S-A 探针已过、DDL/调度/接线细化完成达实施级；M-A 维持功效探针门控；§12 P0
  补状态文件 schema 与 patrol 接线规格。
- **事实核对新增**：_build_market_context 为 async（strategy_design.py:839）✓ 支撑 R104
  await 设计；sina 行规整为 date 键（china_market.py:549）✓ 支撑 R103 判据与 R108 五列；
  _correlation_matrix_for codes 仅取 allocs（:1288-1291）✓ R105 反转依据；
  _rule_based_suggestion/_score 同域（strategy_check.py:1150/:1244-1277）✓ 支撑 R107；
  P1-5 清零点 :615、scanner MIN_AVG_AMOUNT :54/:259 定位 ✓；enriched 装配点
  factor_registry.py:1600-1616 ✓ T-A 注入锚。
- **结构性修正**：并行会话插入其 §10 前端优化实施安排导致撞号——我方巡检节重编号 §12
  （内部小节 10.x→12.x）、pre-commit 节重编号 §13（11.x→13.x），全文交叉引用批量同步；
  并行会话已更新标题至 R103-R122（R122 归属以其内容为准）。
- **遗留**：M-A 功效探针、T-A 覆盖率普查仍为实施前置门（D1）；R105 段二直锤日志随实施补。

---

## 9. 前端 UI/性能走查审计（追加节，2026-08-22 会话二，R109-R121）

> 触发：用户要求「自己查看各张页面内容，找可优化点（性能/布局/样式/按钮/图片），目标
> 性能尽量好、页面美观且专业性强」。本节为 Playwright 实测走查 + 代码级交叉验证的审计结论，
> **未写任何修复代码**，全部为方案级建议（与 §4 同标准：file:line 根因链 + 方案 A/B + 负向验收）。

### 9.0 方法与口径标注（D2/D3）

- **工具**：Playwright MCP headless Chromium 1440×900；逐页 navigate → wait → snapshot +
  screenshot（视口+整页）→ console 全量 → network 请求清单 → Performance API 计时。
- **范围**：7 路由全走查——`/`、`/portfolio-analysis`、`/market-analysis`、`/news`、
  `/token-monitor`、`/source-monitor`、`/admin/config`。
- **代码级交叉验证**：explore 子代理全仓扫描（45 个 .vue、theme.css 705 行 token 体系、
  vite.config.js / nginx.conf / index.html、stores/composables 定时器与 WS 生命周期、
  v-for key / deep watch / img 标签普查），关键 file:line 逐条人工复核。
- **口径标注（D3，防误读）**：
  ① 走查于**周六非交易时段**——行情类 API 走 T-1 快照/降级链，耗时偏高含环境成分，
  绝对值打标「待交易日复测」；
  ② dev server（vite :5173）非 prod build——首屏资源数字不代表生产包体（生产分包策略见
  vite.config.js:95-104 manualChunks，echarts/marked/axios/vue 独立 chunk 已就位）；
  ③ 本轮未重跑 Lighthouse（沿 §7 O2 待办口径）；
  ④ **重复请求/console 错误/DOM 结构类结论不受时段影响**，可直接进实施清单。
- 截图存档：项目根 `audit-{dashboard,portfolio,market,news,token,source,config}-*.png`
  （dashboard/portfolio 为整页图，其余视口图），供实施轮对照。

### 9.1 发现总表

| 编号 | 级别 | 一句话 | 类别 | 关键证据 |
|---|---|---|---|---|
| R109 | P1 | 「导入」按钮死链：handler 未定义，点击无响应 | 功能/反假完成 | PortfolioManager.vue:204 |
| R110 | P1 | API 慢路径实锤 + 同端点重复请求 ×2~3 | 性能 | calculate 7127ms / watchlist 7139ms / indices/global ×3 |
| R111 | P1 | 图表在隐藏容器初始化 → 0×0 canvas 不渲染 | 渲染/UX | Dashboard 实测 5 canvas 中 2 个 0 尺寸 |
| R112 | P2 | AppTabs `:role="tabpanel"` 属性绑定错误（全站 console 噪声源） | a11y/console | AppTabs.vue:69 |
| R113 | P2 | favicon/PWA 图标文件缺失（public/ 目录不存在） | 图片/资源 | vite.config.js:29,36-37；每页 favicon 404 |
| R114 | P2 | router-view 直嵌 transition 反模式（弃用警告 + 切页白屏间隙） | console/UX | App.vue:61-62 |
| R115 | P2 | Skeleton rows prop 类型错（字符串传 Number 位） | console | Dashboard.vue:25,41,53,82,101 |
| R116 | P2 | Token 页 Y 轴刻度格式化 bug（3.9e18 天文数字标签） | 渲染 | TokenMonitor.vue:227/:271 + 截图实证 |
| R117 | P2 | ConfigView 并行深色主题脱离 token（236 处硬编码 hex/23 文件） | 样式一致性 | ConfigView.vue:172-342（42 处） |
| R118 | P2 | emoji 当图标（导航/按钮/行操作），专业度不足 | 样式 | App.vue:125-133 等 |
| R119 | P3 | WS realtime 合并循环内整组数组拷贝 O(n²) | 性能 | stores/market.js:101,:118 |
| R120 | P3 | 字体 token 引用从未加载的 Inter/JetBrains Mono | 样式诚实性 | theme.css 字体栈 vs 无 @font-face |
| R121 | P3 | 数据源监控卡片分项和 > 总数（11+3=14 > 13）口径疑问 | 数据一致性 | source-monitor 截图 |
| R122 | P2 | 移动端（375px）宽表溢出视口 + 导航项拥挤 | 响应式 | audit-dashboard-mobile.png（详见 §9.18） |

### 9.2 R109（P1）：「导入」按钮死链——handler 未定义

- **证据链**：PortfolioManager.vue:204 `<AppButton ... @click="importFileClick">`；
  全文件 grep `importFileClick` 仅此一处（script 段无定义）→ 组合页实测 console
  `Property "importFileClick" was accessed during render but is not defined` ×8，
  点击按钮无任何行为。同族：AppTabs.vue:69（R112）。
- **违反**：反假完成「真实调用点」原则的 UI 版——入口存在但行为断裂（死交互）。
- **方案 A**：补实现——隐藏 `<input type="file" accept=".csv">` + 解析后调
  `POST /portfolio/import`（后端契约已存在，api-contracts/portfolio/）。
- **方案 B**：若导入功能已由「偏离检查/均分权重」等替代覆盖，删按钮并同步契约文档。
- **负向验收**：点击导入弹出文件选择器，选择 CSV 后持仓更新；console 无该 warning。

### 9.3 R110（P1）：API 慢路径实锤 + 同端点重复请求

- **实测耗时**（2026-08-22 周六 dev 环境，D3 打标待交易日复测）：

| 端点 | 实测 | 阈值/基线 |
|---|---|---|
| POST /portfolio/calculate?portfolio_type=on_exchange | **7127ms** | — |
| POST /portfolio/calculate?portfolio_type=off_exchange | 5087ms | — |
| GET /market/watchlist?limit=100&offset=0 | **7139ms** | ≤3s（AGENTS.md 软门禁） |
| GET /portfolio/pnl-history?period=3m | 3383ms | — |
| GET /market/indices/global | 2956ms | — |
| POST /portfolio/daily-pnl?on_exchange | 2125ms | — |

- **重复请求**（与时段无关，结构问题）：
  - `/market/indices/global` 单次 Dashboard 加载 **×3**（多组件各自拉取，未走共享 store）；
  - `/portfolio/tasks?limit=10&offset=0` 每页 **×2**（全局 TaskIndicator 与页面各自轮询）；
  - 组合页 `/portfolio/etfs?portfolio_type=on_exchange` **×3**、159338 的 indicators/chart 各 **×2**
    （PortfolioManager 与 AnalysisView 双路拉取）。
- **方案**：
  A. 前端去重——indices/tasks 提升到 pinia store 单飞（in-flight dedup：并发请求复用同一 Promise）；
  B. 后端排查 calculate 慢段（pricing.py fund NAV 链路与 R106 同域，怀疑场外净值逐只串行外呼）；
  C. watchlist 登记已知性能债（round31 已有先例），交易日复测后再定优化批次。
- **负向验收**：Dashboard 单次加载 indices/global 请求数 ==1；交易日盘中 watchlist p50 ≤3s。

### 9.4 R111（P1）：图表在隐藏容器初始化 → 0×0 canvas

- **证据链**：Dashboard 实测 `document.querySelectorAll('canvas')` 共 5 个，其中 2 个
  clientWidth/Height == 0；console `[ECharts] Can't get DOM width or height` ×2（Dashboard）、
  ×3（组合页）。整页截图对应区域（场内/场外分配饼图、每日盈亏分布）空白。
- **根因假设**：图表组件在非激活 tab（v-show/display:none 容器）或路由 out-in 过渡空窗期
  init，容器尺寸为 0；后续无 resize 补偿（vue-echarts autoresize 未启用或未覆盖该场景）。
- **方案 A**：图表统一启用 autoresize + 监听 tab 激活事件手动 `chart.resize()`；
- **方案 B**：懒挂载——tab 激活才渲染 chart 子树（v-if 由 activeTab 驱动）。
- **负向验收**：切换 组合/场内/场外 tab 后 canvas 尺寸 >0 且无 ECharts warning。

### 9.5 R112（P2）：AppTabs role 属性绑定错误（全站 console 噪声源）

- **证据链**：AppTabs.vue:69 `:role="tabpanel"` ——把字面量写成属性绑定，而组件内无
  `tabpanel` 定义 → 每个使用 tabs 的页面每次重渲染都产生
  `Property "tabpanel" was accessed during render but is not defined`（Dashboard 单页 23 条
  warnings 的主力；7 页走查中 4 页出现）。连带 a11y 断链：`:aria-controls="panel-${tab.value}"`
  引用的 panel id 在 DOM 中不存在。
- **方案**：改静态 `role="tabpanel"`；panel 容器补 `:id` + `tabindex="0"` 形成完整 tablist/tab/tabpanel 语义。
- **负向验收**：任意页面 console 无 tabpanel warning；axe 扫描无 orphaned aria-reference。

### 9.6 R113（P2）：favicon/PWA 图标缺失

- **证据链**：vite.config.js:29 `includeAssets:['favicon.ico']`、:36-37 manifest icons
  `/icon-192.png`、`/icon-512.png` ——但 **frontend/public/ 目录不存在**（全仓 glob 实证），
  index.html 亦无 `<link rel="icon">` → 每页 console error `favicon.ico 404`（本轮唯一
  稳定复现的 console error），PWA 安装流程图标断链。
- **方案**：生成品牌 favicon（SVG 源 → ico/png 192/512 三件套入 public/）+ index.html 补
  `<link rel="icon">` 与 apple-touch-icon。
- **负向验收**：任意页 network 无 404；Lighthouse PWA 类不再报 missing icon。

### 9.7 R114（P2）：router-view 直嵌 transition 反模式

- **证据链**：App.vue:61-62 `<transition name="page" mode="out-in"><router-view /></transition>`
  → vue-router 弃用警告每页必现（7 页全中）；且 out-in + lazy chunk 使每次路由切换出现
  白屏间隙（旧页卸载完才挂新页）。
- **方案**：改 slot 写法
  `<router-view v-slot="{ Component }"><transition name="page" mode="out-in"><component :is="Component" /></transition></router-view>`。
- **负向验收**：导航时 console 无 router warn；切页无可感知白屏（过渡衔接）。

### 9.8 R115（P2）：Skeleton rows prop 类型错

- **证据链**：Dashboard.vue:25,41,53,82,101 `<Skeleton type="table" rows="6" />` 传字符串，
  Skeleton.vue props 声明 Number → 加载期 type check warn ×4。
- **方案**：改 `:rows="6"`（5 处）。
- **负向验收**：加载期 console 无 prop type warning。

### 9.9 R116（P2）：Token 页 Y 轴刻度格式化 bug

- **证据链**：token-monitor 截图左轴标签 `3,918,751,499,999,999,953`（≈3.9e18；本月 Token
  总量 1,436,812，正常轴上限应 ≈1.65e6 量级）；右轴「调用次数」标题与刻度值重叠。
  根因链：TokenMonitor.vue:227 `maxTokens = Math.max(...series.map(s => s.total_tokens), 1)`
  ——若 series 元素 total_tokens 为**字符串拼接产物**（后端 timeseries 数值类型漂移或前端
  reduce 未强转），Math.max 按字典序比较得天文数字 → :271 `max: maxTokens * 1.15` 放大至
  3.9e18。精确污染点需实施轮 D1 探针确认（打印 series[0].total_tokens 的 typeof）。
- **方案 A**：前端 `Number()` 强转 + axisLabel formatter 千分位（`toLocaleString`）；
- **方案 B**：后端 admin/token-usage timeseries 保证数值类型（治本，防其它消费方再踩）。
- **负向验收**：Y 轴最大刻度与本月 Token 总量同数量级；右轴标题不压刻度。

### 9.10 R117（P2）：ConfigView 并行深色主题脱离 token 体系

- **证据链**：config 页截图——API Key 卡片为暗色块（#1e1e1e 族），与全站浅色主题割裂；
  ConfigView.vue:172-342 共 **42 处硬编码 hex** 构成一套平行暗色调色板。全仓普查：
  **23 个 .vue 文件共 236 处硬编码色值绕过 theme.css token**（次高：StrategyCheckResult 25、
  DesignResult 21、DesignHistory/DesignLoading 各 15、SourceMonitor/NewsView/TaskIndicator/
  TechnicalAnalysisModal 各 14）。theme.css 本身已有完整 token 体系（brand/success/danger/
  neutral/surface/border/text 全谱系），替换成本主要是机械映射。
- **方案**：分批 token 化——第一批 ConfigView（视觉割裂最重、用户可见度低风险小）；
  第二批 design/* 结果组件（StrategyCheckResult/DesignResult 的 regime/risk/action 徽章色
  映射到 --color-success/--color-danger/--color-warning 语义 token）。
- **负向验收**：ConfigView 硬编码 hex 计数降至个位数；config 页观感与全站一致（浅色卡片）。

### 9.11 R118（P2）：emoji 当图标（专业度短板）

- **证据链**：顶部导航 7 项全部 emoji 图标（App.vue:125-133：📊📁📈📰🔑📡⚙）、页面标题
  emoji（📊 Dashboard / 📈 行情分析）、主按钮内嵌 🤖（生成A股研判 / AI 智能分析）、
  自选表行操作 emoji（WatchlistPanel 操作列）。跨平台渲染不一致（Win/macOS 表情字形不同），
  与「专业金融终端」定位不符。项目已有内联 SVG 先例（AppTabs.vue:46 滚动箭头、App.vue logo）。
- **方案**：建统一 `Icon.vue`（name → SVG path 映射，lucide 风格线性图标），按
  导航 → 按钮 → 行操作顺序渐进替换；emoji 仅保留在内容文本（资讯正文等）。
- **负向验收**：导航/按钮/表格操作列 grep 零 emoji 字符。

### 9.12 R119（P3）：WS realtime 合并 O(n²)

- **证据链**：stores/market.js:92-103 逐条合并循环内 `realtimeData.value = [...realtimeData.value]`
  （:101；:118 同型）——N 条报价每帧触发 N 次全数组拷贝 + N 次 reactive 触发。
- **方案**：循环内改原地写（`realtimeData.value[i] = {...}` 或 Map 索引），循环外一次性
  触发响应式（整体赋值一次）。
- **负向验收**：构造 50 条 batch 推送，Performance 面板无 >16ms 长任务归因于该循环。

### 9.13 R120（P3）：字体 token 幽灵引用

- **证据链**：theme.css 字体栈声明 'Inter'/'JetBrains Mono'，但全仓无 @font-face、index.html
  无字体 link → 实际永远回退系统字体。对性能无害（零 FOIT），但 token 名误导后来者以为
  已加载品牌字体。
- **方案 A**：自托管子集化 woff2（font-display: swap，仅拉丁字符集，<30KB）；
- **方案 B**：从栈中移除两个名字，如实声明系统字体栈。
- **负向验收**：computed font-family 与设计意图一致。

### 9.14 R121（P3）：数据源监控卡片分项和 > 总数

- **证据链**：source-monitor 截图——总数 13 / 可用 11 / 熔断中 3，11+3=14 > 13。
  四问第 3 问（内部矛盾）触发：要么「可用」含降级态子源、要么「熔断中」计历史态，
  口径未在 UI 说明。
- **方案**：核对 backend source_health 统计语义（admin/sources 契约），卡片加 tooltip
  注明口径；若确属 bug 修计数。
- **负向验收**：Σ分项 == 总数，或每卡带口径说明。

### 9.15 正面清单（回归基线，实施时勿破坏）

- 路由 7 页全 lazy-load（router/index.js）✓；echarts 全 modular `use()` 注册 ✓；
- vite manualChunks 四路分包 + terser drop_console ✓；nginx gzip ✓；
- 定时器/WS/SSE 生命周期全部有清理与退避（Dashboard 30s 轮询、warmup 自限 24 次、
  WS 重连 1s→8s 抖动退避、SSE AbortController）✓；
- v-for 64 处全带 :key、零 deep watch、零 <img> 标签（无 CLS 源）✓；
- 红涨绿跌全站一致（theme.css --color-text-up/down）✓；权重不归一化 banner 诚实提示
  （82.6%≠100% 黄条）✓；news 利好红/利空绿符合国内惯例 ✓；
- 资讯页 API 快（headlines 123ms）✓；四态 UI（loading skeleton/空态/错误 toast）骨架在位 ✓。

### 9.16 推荐实施顺序（待用户决策）

1. **第一批·console 卫生快修（半天量级）**：R112 + R114 + R115 + R113 + R109
   （三个 warning 源清零 + favicon 补齐 + 死按钮接通）——改动小、收益直接、零风险；
2. **第二批·渲染体验**：R111（图表 resize/懒挂载）+ R116（Token 轴 bug，先 D1 探针）；
3. **第三批·性能债**：R110（前端 in-flight 去重 + calculate/watchlist 后端慢段排查，
   交易日窗口复测）+ R119（WS 合并）；
4. **第四批·设计系统**：R117（token 化分批）+ R118（SVG 图标体系）；
5. **第五批·小项**：R120 + R121。

> **§9 状态**：审计完成，未写修复代码。截图存档于项目根 audit-*.png。等待用户
> 「开始实施」指令及批次选择；交易日复测项（R110 绝对耗时、O2 Lighthouse）列入 §7 待办。

### 9.17 审美专项评估（会话追问：主题要不要优化 + 审美问题清单）

**主题层结论：底子不需要推倒，需要「收口」。** 三层判断：

| 层 | 现状 | 判定 |
|---|---|---|
| Token 层（theme.css 705 行） | brand 色阶/语义色/字阶/间距/圆角/阴影/动效/组件 token 全谱系 | **资产，保留** |
| 执行层 | 236 处硬编码 hex 绕过 token（23 文件）；ConfigView 平行暗色主题；regime/risk 徽章 Material 硬编码色 | **断裂，需收口**（R117） |
| 决策层 | ①暗色模式 token 已写好但被强制关闭（theme.css:445 定义 vs :493-495 `color-scheme: light`）；②字体栈声明 Inter/JetBrains Mono 但从未加载（R120） | **两个悬置决策待拍板** |

**审美问题清单（按杀伤力排序，前 3 项决定「专业感」成败）：**

1. **Emoji 图标全站散布**（=R118）——导航 7 项、页面标题、主按钮内 🤖、表格行操作。
   任何一屏出现 emoji 图标，「专业金融终端」观感即刻归零，且跨平台字形不一致。最高优先级。
2. **Dashboard 布局密度失衡**——全球指数卡片 ~190px 挤在行左侧、右侧大片留白；
   总仓位单卡独占整行；当日盈亏 2 卡 + 空白；累计盈亏 3 卡 + 空白。信息密度低 + 视觉重心
   偏左，像未完成态而非设计态。改法：`repeat(auto-fill, minmax(180px, 1fr))` 填满行宽，
   或指数区改紧凑条带式布局。
3. **删除按钮 = 大红实心块 ×N 行**（组合页每行一个）——警报色常态化造成视觉疲劳，
   且与权重 slider 同行加剧拥挤。专业做法：ghost/icon 危险按钮（hover 显红）+ 二次确认。
4. **空状态无设计**——AI 研判大空白卡仅一句提示；图表空白区（R111 加重观感）。
   应有图标/插画 + 引导文案 + 主行动按钮的层次化空态。
5. **Token 页轴标签天文数字**（=R116）——比任何样式问题都伤专业度，用户直接看到「坏了」。
6. **ConfigView 明暗割裂**（=R117 视觉面）——浅色页内嵌深色卡片组，像两个产品拼接。
7. **数字排版缺 tabular 特性**——全站无 `font-variant-numeric: tabular-nums`（grep 实证零命中），
   价格/盈亏列数字宽度不一、列内不对齐。金融 UI 基本功缺失；JetBrains Mono 自托管或
   tabular-nums 一行 CSS 可解。
8. **间距节奏不均**——添加 ETF 表单右侧字段挤压（slider 标签贴边）vs 区块间距宽松，
   8px 网格执行不稳定。

**视觉方向建议（若追求 Linear/Stripe 级）**：现有「蓝色品牌 + 白底浅灰面层」基调是对的，
不需要换框架/UI 库；收紧三件事（SVG 图标统一、卡片网格填满行宽、危险操作降权 ghost）、
补两件事（tabular 数字、暗色模式做完或明确不做并清理死代码）即可跨过专业感门槛。

### 9.18 用户旅程与信息架构评估（会话追问二）

**用户画像**：单人使用的半专业投资者/量化爱好者；产品信条「AI 辅助但可审计」（README §Why）。
核心 JTBD 七件：①每日看全球市场状态 ②管理持仓与仓位 ③AI 设计三套组合并应用
④验证策略/检查持仓健康 ⑤追踪资讯及对持仓的影响 ⑥深研单个标的 ⑦建立系统信任（可审计性）。

**旅程映射与断点**：

| 旅程 | 现路径 | 断点 |
|---|---|---|
| 新用户冷启动 | 打开→Dashboard 指数+空仓位表格 | 无引导无 CTA；样例数据载入（PortfolioManager loadSampleData）埋没；饼图空白（R111）放大荒凉感 |
| 核心·AI 设计 | 导航组合与分析→切 AI工具 tab→向导→异步等待→设计历史找结果 | Hero 功能埋 2 层 tab；README 第二卖点因子模型藏在 AI工具默认视图（FactorModelView 仅由 DashboardAiTools.vue:119 挂载）；结果送达依赖全局 TaskIndicator，闭环松 |
| 日常盯盘 | Dashboard 指数→行情分析切自选 tab | 最高频动作跨页；无全局符号搜索（useMarketSearch 仅局部表单用） |
| 新闻→行动 | 资讯→单条 AI 影响分析 | 文本结论即终点，无「去调整持仓」衔接（断头路） |
| 信任建立 | 因子/数据源/token 三页并列主导航 | 审计能力是卖点但与投资流程平铺混排稀释定位；R121 口径疑问反伤信任 |

**移动端实测（375×812 抽样，Dashboard 整页截图存档 audit-dashboard-mobile.png）**：
导航项挤压换行；场内 ETF 目标分配/每日盈亏明细等 7-8 列宽表溢出视口无横向滚动提示；
0×0 canvas 问题在窄屏复现——响应式只有骨架（global.css 栅格到 lg）没有打磨。
定级并入 R111 批次处理，另立 **R122（P2）：移动端宽表溢出与导航拥挤**。

**信息架构问题**：①Dashboard 的分配/盈亏表 vs 组合页持仓管理职责重叠，边界靠用户猜；
②「组合与分析」单页塞资金输入+AI工具+持仓+技术分析四个心智模型；③「行情分析」5 个子 tab 过深；
④监控三页混入主导航。

**改进建议（按投入产出）**：
- 快赢（不动架构）：冷启动分层空态（图标+「添加第一只 ETF」+「试试 AI 设计」双 CTA+一键样例）；
  AI 设计提权（Dashboard 快捷卡或升一级导航）；全局 Ctrl+K 符号搜索；资讯分析尾部加
  「去调整持仓」锚点；≤md 宽表转卡片式或 sticky 首列横滚。
- 结构性（需拍板）：方案 A——Dashboard 收敛为市场概览（指数+自选摘要），组合页独揽持仓+
  盈亏，监控三页收进「系统」分组；方案 B（保守）——保持 7 页仅加交叉链接与职责说明；
  外加暗色模式拍板（§9.17）。

---

## 10. 前端优化实施方案（2026-08-22 用户采纳定稿，待「开始实施」）

> 用户已采纳 §9 全部建议。本节为整合 R109-R122 + UX 快赢层的**统一实施计划**：
> 七个批次，每批可独立交付验收；开发期只跑受影响测试 + mypy（沿 round33 节奏），
> 验收期全量 1 次 + patrol。**本节为方案，未写任何代码。**

### 10.0 执行原则

1. 每批次独立 commit + 可回滚；TDD 先红后绿（守卫用例随批落地，对齐 §6.4 风格）；
2. 反假完成双证：每项改动有真实交互/调用点验证 + 负向断言（能抓假的测试）；
3. 不动后端 API 契约（R110 后端慢段排查除外，若需改契约先补 api-contracts/）；
4. 性能为软门禁：超阈值登记已知性能债，不阻塞交付；
5. D3 窗口：涉及真实行情耗时的验收（R110）须在交易日 9:30-11:30/13:00-15:00 复测。

### 10.1 批次计划总表

| 批次 | 内容（发现号） | 量级 | 核心文件 |
|---|---|---|---|
| B1 console 卫生+死按钮 | R112/R114/R115/R113/R109 | 0.5 天 | AppTabs.vue、App.vue、Dashboard.vue、vite.config.js、index.html、public/（新增）、PortfolioManager.vue |
| B2 渲染体验 | R111/R116（+R122 图表部分） | 1 天 | AllocationPieChart.vue、PnLBarChart.vue、ChartPanel.vue、TokenMonitor.vue |
| B3 UX 快赢层 | 冷启动空态/AI 提权/全局搜索/资讯衔接 | 1-2 天 | Dashboard.vue、DashboardAiTools.vue、App.vue（Ctrl+K）、NewsView.vue、新 GlobalSearch 组件 |
| B4 性能债 | R110/R119 | 1 天 + 交易日复测 | stores/market.js、api/index.js（去重）、后端 pricing.py 排查 |
| B5 设计系统 | R117/R118/R120/R121 | 2-3 天渐进 | theme.css、ConfigView.vue、新 Icon.vue、design/* 结果组件 |
| B6 移动端打磨 | R122（表格/导航部分） | 1 天 | global.css 栅格、App.vue 导航、各宽表组件 |
| B7 结构性 IA 重组 | §9.18 方案 A | 单独细化轮 | 路由/导航/Dashboard/PortfolioAnalysis 大改 |

依赖关系：B2 依赖 B1（AppTabs 修好后 tab 事件才可靠）；B6 部分依赖 B2（canvas 问题同源）；
B7 依赖 B3/B5 先稳定组件边界。B1-B3 建议连续执行（合计 ~3 天，用户可感知改善最大）。

### 10.2 各批次改动清单与验收标准

**B1 console 卫生 + 死按钮（0.5 天）**
- R112：AppTabs.vue:69 `:role="tabpanel"` → 静态 `role="tabpanel"`；panel 容器补 `:id`/`tabindex`。
  验收：任意页 console 零 tabpanel warning；axe 无 orphaned reference（负向：改前必现）。
- R114：App.vue:61-62 改 `<router-view v-slot="{ Component }">` slot 写法。
  验收：导航零 router warn；切页无可感知白屏。
- R115：Dashboard.vue 5 处 `rows="6"` → `:rows="6"`。验收：加载期零 type warning。
- R113：新增 frontend/public/（favicon.ico + icon-192.png + icon-512.png，SVG 源生成）；
  index.html 补 `<link rel="icon">`。验收：network 零 404；manifest icons 可达。
- R109：PortfolioManager.vue:204 接通导入（隐藏 file input + CSV 解析 → POST /portfolio/import）
  或删按钮（实施时按契约确认二选一）。验收：点击弹出文件选择，导入后持仓刷新；
  console 零 importFileClick warning。
- **批次总验收**：7 页走查 console = 0 error 0 warning（基线：23 warnings/页 + 1 error/页）。

**B2 渲染体验（1 天）**
- R111：图表组件统一 autoresize + tab 激活时 resize()（或 v-if 懒挂载，实施时按组件结构选）。
  验收：Dashboard/组合页切换 tab 后全部 canvas clientWidth>0；ECharts 零宽高 warning；
  375px 窄屏同验（负向：改前 2/5 canvas 为 0 尺寸）。
- R116：先 D1 探针（打印 series[0].total_tokens 的 typeof 与值）定位污染点 → Number() 强转 +
  axisLabel toLocaleString 千分位；右轴 nameGap 调整。验收：Y 轴上限与本月 Token 总量同数量级；
  轴标题不压刻度（负向：改前截图对照）。
- 守卫：TokenMonitor 单测注入字符串型 total_tokens 数组断言轴 max 为数值（能抓回归）。

**B3 UX 快赢层（1-2 天）**
- 冷启动分层空态：持仓为空时 Dashboard 分配区/组合页显示「图标 + 引导文案 +
  『添加第一只 ETF』+『试试 AI 设计』双 CTA + 一键载入样例」。
  验收：清空持仓后空态含可点击双 CTA；样例一键载入后表格有数据（负向：空态不得是纯空白）。
- AI 设计提权：Dashboard 顶部加「AI 设计组合」快捷卡（直达 DesignWizard）；
  验收：首页一次点击进入向导（当前路径 3 步）。
- 全局搜索：App.vue 挂 Ctrl+K 命令面板（复用 useMarketSearch + marketApi.search），
  选中跳转对应页面/标的。验收：任意页 Ctrl+K 输入 510300 可跳转；ESC 关闭。
- 资讯衔接：NewsView AI 影响分析结果尾部加「去调整持仓」按钮 → 路由跳组合页。
  验收：分析完成后一键可达持仓管理。
- 守卫：组件测试覆盖空态渲染与搜索跳转路由断言。

**B4 性能债（1 天 + 交易日复测）**
- R110 前端侧：indices/global 与 portfolio/tasks 收敛到 store 单飞（in-flight Promise 复用 +
  短 TTL 缓存）。验收：Dashboard 单次加载 indices/global 请求数 ==1（基线 ×3）、tasks ==1（基线 ×2）。
- R110 后端侧：calculate 7.1s 慢段定位（pricing.py fund NAV 链路嫌疑，与 R106 同域探针合并）；
  定位后登记性能债或排期修复；watchlist 7.1s 同法。
- R119：market.js:101/:118 循环外一次性赋值。验收：50 条 batch 推送无 >16ms 长任务。
- D3：绝对耗时验收限交易日盘中；周末数据仅作回归对照。

**B5 设计系统（2-3 天渐进）**
- R117：第一批 ConfigView.vue 42 处 hex → token 映射；第二批 design/* 徽章色 →
  --color-success/danger/warning 语义 token。验收：ConfigView 硬编码 hex 降至个位数；
  config 页观感与全站一致。
- R118：新建 ui/Icon.vue（name→SVG path，lucide 风格），替换顺序：导航 → 按钮 → 行操作。
  验收：nav/按钮/表格操作列 grep 零 emoji。
- R120：拍板后执行——自托管 JetBrains Mono 子集（<30KB，font-display: swap）或移除幽灵引用；
  全站数字列加 `font-variant-numeric: tabular-nums`。验收：font stack 与实际渲染一致；
  盈亏列数字列内对齐。
- R121：核对 admin/sources 计数语义，卡片补口径 tooltip 或修计数。验收：Σ分项==总数或有说明。

**B6 移动端打磨（1 天）**
- R122：≤md 断点宽表（ETF 目标分配/每日盈亏明细/持仓列表）转卡片式堆叠或 sticky 首列横滚；
  导航折叠为汉堡/抽屉式。验收：375px 下无横向溢出（document.scrollWidth <= viewport）；
  关键表格数据可读（负向：改前 scrollWidth 溢出实证）。

**B7 结构性 IA 重组（单独细化轮，方向已定方案 A）**
- Dashboard 收敛为市场概览（指数+自选摘要+AI 快捷卡）；持仓+盈亏全权归组合页；
  监控三页收进「系统」分组；AI 设计升一级导航。
- **前置条件**：出子方案文档（页面职责矩阵 + 迁移清单 + 回归测试范围）评审后再实施；
  不与 B1-B6 混批。

### 10.3 全局验收口径（全部批次完成后）

1. 7 页 Playwright 走查：console 0 error 0 warning；network 无 404/重复同端点请求；
2. Lighthouse 复测：首页 perf ≥76（round33 基线，当前负载态 67-68）、dashboard 维持 ≥99；
3. `patrol --diff` 全绿 + 验收期 `patrol --full` 1 次（沿 round33 方案 B 凭据机制）；
4. verify_e2e 不低于 round34 基线（279/291，M7/P1-1 四连 FAIL 为 R105 已知项非回归）；
5. npm test 全绿（499+ 新增用例）；
6. 交易日盘中复测：watchlist ≤3s、calculate 登记值 vs 修复值对照。

### 10.4 残留决策点（不阻塞 B1-B3）

- 暗色模式：做完（token 已备好，补切换开关 + 组件走查）或明确不做（清理 theme.css:445-496
  死代码）——建议做完，盯盘场景价值高，可在 B5 后插入；
- B7 细化子方案的评审时间点；
- R110 后端慢段若定位到契约级问题（如需批量 NAV 接口），按契约先行流程补 api-contracts/。

---

## 11. 测试命名重组方案：round 编号测试并入业务维度（2026-08-22 追加，待「开始实施」）

> 触发：用户要求把 test_roundXX 类测试合并进业务维度命名的测试代码。本节为现状盘点 +
> 评估 + 迁移方案。**纯移动/改名/加指针，不改任何断言与被测行为。**

### 11.1 现状盘点（2026-08-22 实测）

后端 `backend/tests/` 共 **238 个** test_*.py，round/finding 编号以四种模式存在：

| 模式 | 数量 | 例 | 评价 |
|---|---|---|---|
| A. 独立 round 文件 | **16 个** | test_r74/r85-r98/r102_*.py（注意 r75-r84、r99-r101 缺位——该模式从未严格执行） | ❌ 待迁移主对象 |
| B. 业务文件 + 编号类名 | **25+ 处 / 12+ 文件** | TestR64AvgCostWithoutShares ∈ test_cumulative_pnl_estimation.py；TestP1_1MaxCorrelation ∈ test_allocation_engine_fixes.py | ✅ 目标模式雏形，保持 |
| C. 业务名+r 后缀混合文件名 | ~11 个 | test_design_degrade_r69.py、test_watchlist_concurrency_r78_r82.py、test_f25_ic_daily_pipeline.py 等（F 系列同族） | ⚠️ 可保留（编号在后无害），低优先级 |
| D. 前端 finding 前缀文件名 | 4 个 | marketStore.p1-1.spec.js、PnLDetailTable.p0-14.spec.js、TechnicalAnalysisModal.p5.spec.js、p1k-pnl-color.spec.js | ❌ 归位 |
| E. 前端主流：业务 spec + finding describe | 全部 spec 文件 | 'FactorModelView — F22 政策 static 展示'、'SummaryCards 累计盈亏估算标注 (R66/R67)' | ✅ 保持 |

**工具链依赖核查（迁移安全性关键证据）**：
- patrol.py:133-175 按**变更文件路径泛匹配**收集 test_files → pytest_subset，无 test_r 硬编码 ✓
- pre-commit:315-339 同为 staged 路径泛检测 ✓
- pytest.ini/conftest 无文件名级逻辑 ✓
→ 结论：改名/移动对 CI 工具链**零功能影响**。

### 11.2 评估

**收益（支持合并）：**
1. **可发现性**：改 pricing.py 时应能直接定位 test_portfolio_* / -k fund_nav，而不是背
   「r96=因子数据质量」的历史映射——round 编号是历史坐标不是业务坐标，且随轮次增长衰减
   （AGENTS.md 已确立 docs 为唯一事实源，测试名不应承担记忆职责）；
2. **文件数收敛**：「每轮一文件」已致 238 个文件的碎片化；按业务域归并后稳态收敛，
   新用例有明确宿主；
3. **一致性**：与 §6.4 G1-G6 守卫命名（test_allocation_anchor_injection.py 等业务命名）对齐；
4. 合并冲突面减小（同域用例集中）。

**成本与风险（可控，均有缓解）：**
1. 追溯性损失 → 类名保留 R/F/P 编号 + docstring 首行指针（`R94 (round31 §5.2) — 动量跨路径守卫；
   迁移自 test_r94_momentum_cross_path.py`）；memory/docs 的 round→finding 映射不受影响；
2. review 噪声 → T2 按业务域拆 2-3 个 commit 分批迁移；
3. pre-commit P3-6 测试基线为提示不阻断，若引用旧路径同步即可。

**明确不做**：不动任何断言/fixture 内容；类名原样保留（避免无功能收益的行级 churn）；
C 类混合文件名本轮不动（见 T3 决策）。

### 11.3 目标命名规范 v1

- **文件**：`test_{业务域}_{行为}.py`；优先并入既有业务文件，确无宿主才新建；
- **类**（仅新增守卫适用）：`Test{行为}_R{N}` ——业务在前、编号在后（对齐 G 系列与
  TestEnforceMaxCorrelationR24 先例）；存量类名迁移时**原样保留**；
- **docstring 指针（强制）**：迁移用例模块头注明来源轮次与原路径；
- 前端维持 E 模式（describe 内带编号即可）。

### 11.4 迁移批次

| 批次 | 内容 | 量级 | 验收 |
|---|---|---|---|
| T1 前端归位 | D 类 4 个 spec 并入对应业务 spec 或改名 | 0.5 天 | npm test 用例数不变全绿 |
| T2 后端 16 文件归宿 | git mv + 合并进宿主 + docstring 指针；按业务域拆 2-3 commit | 1 天 | 见 §11.5 |
| T3 混合命名决策 | C 类 + F 系列：建议保留现状（编号在后无害可追溯），仅新增遵守 v1 | 0.5h 决策 | — |
| T4 工具文档同步 | AGENTS.md 加「测试命名惯例」段；P3-6 基线同步；下轮 memory How-to-apply 指向新路径 | 0.5 天 | grep 旧路径仅剩历史文档 |

**T2 宿主映射初稿**（实施时以 import 依赖/被测模块微调）：

| round 文件 | 业务域宿主（并入或新建） |
|---|---|
| r93 data_dir_container | 新建 test_config_container_paths.py（config/database 域） |
| r94 momentum_cross_path | strategy_check 域（test_strategy_check_* 或新建） |
| r95 report_number_consistency | test_report_quality.py / report format 域 |
| r96 factor_data_quality | factor 家族（test_factor_integration.py 等） |
| r97 stock_search_fallback + （既有）test_search_a_stocks_r76 | 搜索域合并（test_search.py 或合并新文件） |
| r98 news_global_summary | test_news_classification.py 域 |
| r92 realtime_contract | contract/realtime 域 |
| r91 static_a_stock_base | test_search.py 域 |
| r74/r85-r90/r102 | 各自域（china_market/kline/factor/news/fast_json）实施时定 |

### 11.5 验收口径（含负向断言）

1. 全量 pytest 用例数迁移前后一致（基线 2537 passed ± §10 B 批新增；迁移零增减）——
   「数变少 = 丢用例」即 FAIL；
2. `-k "R9"` 查询命中数迁移前后一致（编号可检索性守卫）；
3. patrol --diff 对 backend/app/pricing.py 的改动能选中迁移后的业务宿主文件（工具映射正确性）;
4. `grep -r "迁移自 test_r" backend/tests` 命中 16 处（指针完整性）；
5. vitest 用例数不变全绿（T1 后）。

### 11.6 与 §10 批次的关系

独立于 B1-B7 可并行推进；建议排在 B1 之后执行（避开同一批文件的同时变更冲突）。
总工作量 ~2 天（T1 0.5 + T2 1 + T4 0.5，T3 仅决策）。

---

## 12. 巡检体系优化设计（2026-08-22 会话追加，讨论级未实施）

> 用户要求 review 巡检体系，目标是「运行过程中的问题尽量通过巡检就能发现」。以本轮
> R103-R108 六项发现 + 遗留疑点为实测样本做漏检对照，归纳结构性盲区，给出分级改进方案。
> **全部为设计，未写任何代码。**

### 12.1 现状盘点（patrol 九 stage 已核实）

| 层 | 组件 | 检什么 |
|---|---|---|
| L1-unit | pytest（2537 例） | 函数级正确性 |
| L2-e2e | verify_e2e（291 检查） | 端点链路内容 |
| L2-health | data_health_check（10 项） | 数据源可达性/因子方差/层深 |
| L2-smoke | smoke_startup | 进程能起来 |
| L3-perf | verify_perf（软门禁） | watchlist≤3s 等 |
| L4-routes/purity/async | 静态门禁 ×3 | 契约、引擎纯度、同步 IO |
| L5-frontend | npm test+build | 前端 |
| pre-commit | 13 段门禁 | 提交时全量 |
| 应用内常驻 | token/source monitor、120s 探针 | 运行时可观测 |

**公允评价**：编排成熟（diff/full 双模式、按变更选层、条件触发）；R105 是 e2e M7/P1-1
成功抓到的唯一案例。问题不在已有层质量，在**覆盖维度**。

### 12.2 漏检对照（六项发现逐一过堂）

| 运行时问题 | 现有体系表现 | 漏检原因 |
|---|---|---|
| R103 回填每启重跑 | ❌ 零感知 | 无任何层看「启动后干了对什么」 |
| R108 回填丢列（7 因子补不了历史） | ❌ n=9 停滞 9 天无人知 | 单测工厂镜像缺陷；无增长率检测 |
| vwap 冻结 n=245 一整年 | ❌ 同上 | data_health 只查方差不查增长 |
| R106 WARNING 每 60-120s 重放数月 | ❌ 日志无人消费 | 日志未接入任何门禁 |
| R104 设计元数据谎报积累中 | ❌ fdq 只验字段存在 | 无跨源数值一致性断言 |
| R107 报告双「因子分」矛盾 | ❌ e2e 只验非空 | 同上 |
| /health 超时 ×2 | ⚠️ 抓到但根因随容器灭失 | 容器态巡检缺位+日志不留存 |
| R105 锚剥除 | ✅ e2e M7/P1-1 抓到（唯一立功） | 但只给 FAIL 不给归因——多轮误读「环境性」 |

### 12.3 结构性盲区归纳（六类）

1. **时间维度缺失**：九层全是瞬时快照断言，不查变化率/重复模式——R103（每启重复）、
   vwap 冻结、R106（周期重放）都是时间序列模式，快照型巡检结构性看不见。
2. **启动路径只验「能起来」**：L2-smoke 边界=进程存活+健康端点；回填行为、池 enforce
   都在启动后 2 分钟窗口——唯一零覆盖的行为区间。
3. **日志是金矿但没有消费者**：本轮三个关键结论全来自日志考古（enforced mandatory
   不对称/ic_backfill 双次全量/ascii 周期重放），信号早就写在 backend.log 里，任何一层
   门禁做一次 grep 即可提前发现——巡检与日志完全脱钩。
4. **跨出口一致性无成对断言**：R94→R95→R104→R107 四进宫，「同一业务量两个出口说不同的
   话」；单点断言天然抓不到，需要配对断言。
5. **容器态与降级态无 profile**：patrol 九层全跑本地进程；「本地绿≠容器绿」（R93 教训）
   靠手工诊断轮兜底；降级态恰是质量门禁误杀高发场景（R105），但 e2e 在降级态要么环境性
   FAIL 淹没真问题要么 SKIP 关键断言。
6. **证据生命周期 = 容器生命周期**：/health 超时根因随 docker down 灭失，排查断头。

### 12.4 改进方案

**P0（纯脚本低成本 ~300 行，一个 commit）**

- **P0-1 `check_startup_behavior.py`**（新 stage `L2-startup`，复用 smoke 日志管道）：
  ① `[ic_backfill]` 必须出现「完成|跳过」之一，连续两次启动均「完成」→ WARN（R103 信号，
  依赖 .patrol_state.json 记上次模式）；② MANDATORY_CODES 逐成员审计「在池 OR 有 enforce
  日志」，皆无 → FAIL（直接抓 R105 段一静默跳过）；③ WARNING 指纹（logger+去参模板）
  重复 ≥K 次/h → WARN（抓 R106）。
- **P0-2 `factor_sample_growth_check`**（data_health 第 11 项）：per-factor distinct
  trade_date 对比上次快照；停滞 ≥N 天且 n<250 → 列「输入缺失观察名单」（vwap 冻结一年、
  R108 七因子停 9 天都会第一时间点亮）。

**P1（中等投入）**

- **P1-1 `verify_consistency.py` 跨源一致性断言集**：fdq.ic_accumulation vs DB distinct
  （R104）、报告表格分 vs composite（R107）、正文数值 vs 结构化 summary（R95）、rationale
  动量 vs factor_matrix（R94）。可作 e2e 新模块或独立 patrol 层。
- **P1-2 `patrol --container` profile**：起 prod 容器 → 核心子集（L2-health/L3-perf/e2e
  核心模块/P0-1）→ **容器日志归档 `logs/patrol/<date>/`** → down。一次解决盲区 5+6，
  且周末也能跑全链路。
- **P1-3 降级态场景巡检**：显式屏蔽单一数据源跑设计链路，断言三方案仍产出、MANDATORY 锚
  不被剥除、fdq 诚实降级——把 R105 回归从单测提升为常态化场景。

**P2（记录方向暂不排期）**：design/check 任务耗时 p95 入 metrics（治 734 类边缘竞争可见性）；
巡检自身可信度自检（输出检查数下限，防 R4-18 式空转）；关键行为日志结构化（P0 检测从正则
升级为字段匹配）。

**P0 实施规格补充（Round 8）**：

- 状态文件 `logs/patrol/startup_behavior.json`：`{"last_backfill_mode": "completed|skipped",
  "ts": "<iso>", "head": "<sha>"}`；
- check_startup_behavior.py 断言源 = backend.log 自最近启动标记起；backfill 连续 completed
  ≥2 → WARN（R103 信号）；WARNING 指纹 = logger 名+去参消息模板，阈值默认 K=5/h（env 可调）；
- factor_sample_growth_check 快照存 `data/patrol_factor_growth.json`；首跑建基线并记 PASS；
  停滞判定 = 连续 ≥2 次巡检 n 无增长且 n<250 → WARN 列观察名单；
- 接线：patrol.py STAGES 增加 `"L2-startup": {"timeout": 60, "backend_dependent": false}`
  插在 L2-smoke 后；data_health 第 11 项随既有 PASS/FAIL 汇总输出。

### 12.5 设计纪律（沿用项目既有约定）

1. 新检测默认 **WARN 级起步**，观察期后再升 FAIL——防降级态误报刷屏（R4-07 极端行情误报
   教训）；缺数据时诚实降级标注而非硬 FAIL。
2. 新门禁必须自带**可信度自证**（输出检查数下限）——防 R4-19 式「门禁存在但从未真正跑过」。

### 12.6 优先级建议

P0 三件套一批（纯脚本合计 ~300 行）→ P1-2 容器 profile（下轮容器诊断前就位，直接受益）
→ P1-1/P1-3 随 R104-R108 实施批落地（其验收本身就需要这些检查确认）。等待用户拍板是否
立项 P0 批次。

---

## 13. pre-commit 门禁体系评估（2026-08-22 会话追加，讨论级未实施）

> 用户要求评估 pre-commit 门禁合理性并找改进点。`.githooks/pre-commit` 全文 487 行实读，
> 15 段逐一过堂（非文档转述）。**全部为设计，未写任何代码。**

### 13.1 体系全景（15 段实测清单）

| # | 段 | 触发面 | 阻断 | 跳过开关 |
|---|---|---|---|---|
| 1 | 密钥扫描（5 正则+占位符过滤） | 所有文本类暂存文件 | ✅ | SKIP_SECRET_CHECK |
| 2 | check_routes 契约一致性 | api-contracts/* 或 routers/*.py | ✅ | **无**（有意置于文档短路前） |
| 3 | 纯文档短路 | 仅 docs/diag/api-contracts | 早退 | — |
| 4 | npm build | frontend/src 等 5 路径 | ✅ | SKIP_FRONTEND_BUILD |
| 5 | check_api_usage | frontend/src/api/* | ✅ | SKIP_API_CHECK |
| 6 | audit_async_blocking | backend/app/* | ✅ | SKIP_AUDIT_ASYNC |
| 7 | P3-1 未引用符号审计（基线增量） | backend/app/* + 脚本自身 | ✅ | SKIP_UNUSED_AUDIT |
| 8 | P3-2 死样式审计（基线增量） | styles/* + 脚本自身 | ✅ | **无** |
| 9 | mypy | backend/app/* | ✅ | SKIP_MYPY（未安装则整段静默跳过 :245） |
| 10 | docker build 冒烟 | requirements.txt/Dockerfile | ✅（daemon 不可用环境跳过） | SKIP_DOCKER_BUILD |
| 11 | pytest 三档分派 | 档0 conftest→全量；档1 逻辑→全量或凭据复用+affected；档2 仅测试→affected | ✅ | SKIP_BACKEND_TESTS / SKIP_TESTS_MARKER |
| 12 | verify_perf 软门禁 | 仅 perf 脚本或本钩子自身变更 | ❌ 永不阻断 | SKIP_PERF_GATE |
| 13 | P3-6 测试数基线 ≤197 | tests/*.py | ❌ 提示不阻断 | **无**（有意降级） |
| 14 | smoke_startup（SMOKE_FAST） | backend/app+scripts+requirements | ✅ | SKIP_SMOKE_STARTUP |
| 15 | engine 纯度 AST | engine/* + 脚本自身 | ✅ | **无** |

### 13.2 合理性总评：结构健康，定位清晰

做得对的五点（行号证据）：

1. **触发面工程精细**：每段独立 pathspec 过滤；pytest 三档分派 + 凭据复用（:355
   tests_ok_marker 指纹+HEAD+时效三重校验）——代码面指纹保证「任何逻辑变更即凭据失效恢复
   全量」，闭环正确。
2. **顺序有讲究**：check_routes 故意放在文档短路之前（:86-88 注释明说契约变更不得被短路
   跳过）、密钥扫描在最前（文档也可能泄漏 key）——两处顺序都是踩坑后的刻意设计。
3. **历史教训全部注释固化**：R6-01 构建回归催生第 10 段、round30 xdist 封顶 4（20 核炸
   Windows 句柄）、2026-08-09 secret 扫描子 shell 变量不传播 bug——每个反直觉写法都有出处。
4. **失败信息可操作**：每段统一给出「修复方向 + 跳过方式」。
5. **环境优雅降级**：docker daemon 不可用区分「环境跳过 vs 真实构建失败」（:286-299 case
   分支）。

**定位澄清（重要）**：本轮 R103-R108 六项发现全部经 pre-commit 绿灯提交——但这不是它的
失职。15 段守的是**代码结构与提交纪律**（类型/契约/纯度/死代码/能启动），运行时行为问题
归 patrol/e2e 管。其中 R104/R106/R107 的回归防护由 G2/G4/G5 单测落地后自然进入 pytest 档
——**不需要为此新增门禁段**（符合门禁治理约定①防膨胀）。

### 13.3 发现的问题（按严重度）

| # | 级别 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| 1 | P1 | **`cd backend … cd ..` 成对模式脆弱**：全文 10+ 处，任何一段未来改动漏写恢复就污染后续所有段的工作目录 | 全文模式 | 重构为子 shell `(cd backend && …)` 包裹——失败自动回目录，结构性免疫（唯一值得动刀的重构点） |
| 2 | P1 | **mypy 未安装整段静默跳过**（:245）：对比 xdist 缺失时有「⚠️ 建议安装」提示，mypy 缺失连一行都不打印——类型检查可能长期空转而不自知 | :245-267 | 补一行 WARNING（对齐 xdist 先例），2 分钟改动 |
| 3 | P2 | **「13 段」数字漂移**：治理约定①写「与现有 13 段差异化」，实际已 15 段（docs 短路、engine 纯度、perf 软门禁、P3-6 加入后未更新基数）——新门禁「差异化价值」论证的对照清单失准 | :11 vs 实测 | AGENTS.md 同步为 15 段并列清单 |
| 4 | P2 | **skip 开关不对称**：12 段有跳过开关，check_routes/P3-2/engine 纯度三段没有——若是「架构/契约硬约束有意不给逃生门」应注释写明是有意设计而非遗漏 | 各段头部 | 注释标注意图即可 |
| 5 | P2 | **verify_perf 段自指触发形同停摆**：仅当 perf 脚本或钩子自身变更才跑（:412-413），日常提交永远不碰——性能台账机制实际空转 | :412-413 | 已被 §12 P0-2/P1-2 接管，建议此段注释标注移交关系避免双轨困惑 |

### 13.4 明确不建议做的

- 为 R103-R108 新增门禁段——违反治理约定①，其防护属于 G 系列单测 + §12 巡检；
- 把 e2e 塞进 pre-commit——需要后端在线，破坏「commit 快速反馈」定位；
- 表驱动重构压缩 487 行样板——收益是可读性、风险是回归，「最小改动」原则下不值得。

### 13.5 一句话总结

> 这套门禁的**结构与纪律是项目里质量最高的部分之一**——触发面、增量策略、教训沉淀都属
> 上乘；它的边界（管提交纪律不管运行时行为）应当被明确承认而不是试图扩张。真正的改进
> 空间全是工程卫生级的小活：一处结构性加固（子 shell 化）、两处提示补齐、一处数字漂移
> 修正。建议随第一批实施（R104+R107）捎带第 2、3 项分钟级微调，第 1 项子 shell 化单独
> 一个 commit（纯结构重构需独立验证）。
