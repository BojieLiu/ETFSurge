# round57 容器全链路诊断 — round56 实施批复验（2026-09-19 周六盘后/周末）

> 独立 round57 文档，不改写 round56 / 更早轮次。
> **归档提示（2026-10-03 round61 收尾）**：本文引用的 round56 已归档至
> `docs/archived/round56-container-reacceptance-round55-fixes.md`；文中「round56 §2.x/§4.1/§6#n」
> 均指该归档件。round55 及更早同理（`docs/archived/`），短名引用按既有惯例未改写路径。
> 诊断对象：HEAD `980a1c5`（含 `c6bce16` round56 R192/D/G/H 落地批 + `95f3c31`/`980a1c5` advice 批 + poster/share 前端批）。
> 验证环境：Docker Engine 29.7.2，prod profile + diag overlay（PROFILE_WARMUP=1）。
> 验证窗口：2026-09-19 周六 11:26-12:10（**周末非交易日**：实时类结论标「周末形态」）。
> 容器 11:26:54 起，warmup 39.6s（新）+ 39.9s（旧）；三容器 Up 全程无重启。
> 探针产物：`C:/Users/Public/etf_probe/`（build57*.log / rt/fh/fa/heat/s_*/newsall/nh/nm/ng / ws_probe57.py /
> design_task+check_task+dedup/t106 / tasks / designs / d62.json+c143.json+d62.txt+c143.txt /
> struct62.py+dup62.py+mom62.py+c143*.py / q57.py / feoverlay/ / settings-store.json.bak，会话级临时目录不入仓）。

---

## 0. 执行摘要

| # | 结论 | 状态 |
|---|---|---|
| 1 | **构建受阻后绕行成功**：daemon 直连 registry-1.docker.io  blocked（v6 黑洞 + v4 超时），`node:24-alpine` 拉取失败；后端用缓存基座一次建成并验明含 HEAD 代码，后端 overlay 方案：宿主 node v24.19 `npm run build` + `FROM` 缓存镜像 overlay，三字串实证=HEAD 构建 | ⚠️ 环境性（过程见 §1），镜像内容 ✅ |
| 2 | **round56 §6 #8 R192/D 生产实证**：同参连击两次同返 task 106（pending→running 去重，单执行 completed） | ✅ 关闭 |
| 3 | **round56 §6 #9 G 部分生效**：`divergence_detail` 键已在 suggestions schema 中，但 check143 30/30 为 null——P2/P3 分支外常见 sell+hold 无明细，前端 tag 无 why（→ R199 P3） | ⚠️ 半生效 |
| 4 | **round56 §6 #10 H 后端就绪**：design62 plans 三方案均含 CASH 行；前端表格渲染无浏览器实证，以 vitest（DesignResult.spec）为准 | ✅ 后端 / 📋 前端待浏览器 |
| 5 | **R186/R187/R188/R189 维持**：check143/106 三旗语 fallback 一致；vitest 568 passed 零 rejection（仅 router-link benign warn）；pytest 3268 passed / 0 failed；smoke 21/21（E′ 回落 [INFO]） | ✅ 维持 |
| 6 | **R181/R177/R178/因子维持**：design62 三方案 Σ=1.0、max≤0.30、零同指数重复；search 1/19/13；news 15+6+8=29；factor-health 3 healthy；factors/active 6/12/20 与 round56 完全一致 | ✅ 维持 |
| 7 | **R179 存续**：双 warmup 告警并存（39.6s 新 + 39.9s 旧），与暂缓登记一致 | 📋 维持 |
| 8 | **R191 维持关闭**：check143 复合分 19 个离散值，top 值 -0.779 仅 6/30，-0.21 零出现 | ✅ 维持 |
| 9 | **R196（P3）场外 null 价挂 last_close 标签**：15 只场外联接 price=null + `estimate_source=last_close`（`market_service.py:1337` nav 失败即标 last_close，无值却挂名）；根因链含周末环境成分（fetch_fund_nav 10× 失败日志），标签错误本身与周末无关 | 🐛 新发现 |
| 10 | **R197（P2）设计回报三元组 6 标的克隆**：512890/510050/515880/512880/513180/513120 的 etf.change_pct/return_1m/return_3m 与 159338 精确值（0.016182/0.010422/-0.014896）的 3 位小数舍入版（0.016/0.01/-0.015）逐项一致；矩阵动量 +0.023×5 连带；文本按标的呈现为实测值 | 🐛 新发现 |
| 11 | **R198（P3）同行内「综合信号」三值并存**：rationale 聚合（-0.01）vs 脚注因子分（-1.05/-3.16，`allocation_engine.py:2047`）vs 点分 overall（0.0），同标签异值 | 🐛 新发现 |
| 12 | **R199（P3）G 覆盖缺口**：else 分支 sell/buy+hold 不设 divergence_detail，前端 tag 回落通用文案（check143 30/30 null，≥4 行 sell+hold 将显示无 why 的 tag） | 🐛 新发现 |
| 13 | **e2e 分段 138 全过**：21+65+14+15+2+4+17 ALL PASS；DHC 13/13（134s）；WS 直连+经 nginx 3/3 均为 101 | ✅ |
| 14 | **补测完成（2026-09-19 13:30-14:10，第二实例）**：Lighthouse（Edge headless，2 采样/页）、浏览器走查（5 路由 DOM dump）、advice 批生产实证、patrol --full——见 §2.8 | ✅（附带 DOC-2 + F1/F2，见下） |
| 15 | **DOC-2（文档订正）**：`/dashboard` 路由不存在（router 仅定义 `/`=dashboard），本轮及 round56 的“Dashboard Lighthouse”（95/98-99）测的是 **404 NotFound 页**，非真实看板；真实看板 = `/`（perf 66-67） | 📝 订正 |
| 16 | **advice 批生产实证 PASS**：valuation 意图 live（`fetching_valuation` 相位）→ 沪深300 PE-TTM 14.63/as_of 09-18 真值 → 答案 0 自编 ETF 码；5 指标并发为代码层（gather）+ 取数成功行为侧 | ✅ |
| 17 | **patrol --full exit 1（1447s）**：PASS 7 项（L1-unit/alloc-invariants/llm-exclusion/routes/purity/async/frontend）；FAIL 4 项中 3 项为周末预算性（L2-e2e 900s/L2-health 120s/L3-perf 120s——分段 138/DHC 13/13 本轮已独立全过）；**F1 L4-baseline 328>320**（advice 批新测试文件未并入/未提 BASELINE，治理债）；F2 ruff WARN（`_valuation.py:22/:154` 非法 noqa，advice 批） | ⚠️ 见 §2.8 |
| 18 | **tests_ok 凭据口径**：本轮 patrol 写入 `logs/patrol/tests_ok.json`（head=980a1c5）时全量 exit 1——该凭据仅对应 **L1 通过**，不得解读为全量绿 | 📋 口径标注 |

---

## 1. 环境构建与启动

- 10:59:45 `up -d --build`：backend 一次建成（`Image etf_surge-backend Built`），frontend 在 `node:24-alpine` 拉取失败：
  `dial tcp [2a03:…]:443: connectex`（build57.log:66-89）。
- 根因取证（环境性，非产品）：daemon IPv4 外发正常（223.5.5.5 ping 通；pypi.org/TUNA 443 TCP-OK），唯 registry-1.docker.io
  v4 199.59.149.236:443 超时；163/ustc/腾讯三镜像站 DNS NXDOMAIN（服务早下线，非网络问题）。
  宿主代理 0.0.0.0:7897 经 `host.docker.internal:7897` 从 daemon 网络 TCP-OK，CONNECT 隧道实证可用（400 回包即隧道已建）。
- 曾试 `settings-store.json` 注入 proxyManual（Desktop 接受键并规范化 `ProxyHTTPMode`，但 backend 日志仍
  `because Docker Desktop has no HTTPS proxy`）+ `docker desktop restart` 一次——未生效，回退（bak 留存探针目录）。
  结论：本轮两次尝试（文件注入 + `docker desktop restart`）均未改变 engine 拉取行为（backend 日志持续
  `has no HTTPS proxy`）；改走 overlay 方案，不再追 Desktop 配置（省预算， bak 留存探针目录）。
- Backend 镜像验明 = HEAD：`/app/app/services/portfolio/strategy_check.py` 内 `divergence_detail`×2、
  `task_manager.py` 内 `deduped`×5，与宿主一致（COPY 缓存显示问题以内容实证为准）。
- Frontend overlay：宿主 node v24.19（与镜像 node:24 主版本一致）`npm run build` 11.83s 成功（deps/config 自 8193576
  未变：`git diff --name-only` 空）；`FROM etf_surge-frontend:latest` + COPY dist（经 feoverlay 上下文，绕开
  frontend/.dockerignore 对 dist 的排除）；构建物验明含 HEAD 三字串（现金缓冲/背离文案/explanation → AiDesign chunk）。
- 11:26:54 `up -d`（无 --build，backend 新镜像 + frontend overlay）；三容器 Up，无重启。
- warmup 39.6s（top3：instruments_sync 26.8s / indices_meta_sync 12.6s / etf_cache 0.2s）+ 旧格式 39.9s（R179 存续实证）；
  instruments 1741 行；indices_meta 1106 行；nav-warmup cycle=1 `pool_empty`（周末诚实标注）。
- `.env` 含 key；宿主代理常驻，探针统一 `curl --noproxy '*'` 落盘 + WS `proxy=None`（py312 websockets 16.0；
  msys2 python 无 websockets 模块，改用 py312——探针口径备注）。
- 定时刷新：sector cache ~60s 周期（11:57:48/11:58:48/11:59:47），regime/sentiment 刷新（range_bound），
  news buckets h=15 m=6 g=8（与 §2.5 一致）。
- `docker image prune -f` 回收 0B（无 dangling）。

## 2. 全链路诊断 + 对照验证

### 2.1 端点健康与性能（周末）

| 路径 | 本轮 | round56 | 阈值 | 判定 |
|---|---|---|---|---|
| /health | 200 / 0.41s | 200 | — | ✅ |
| nginx / | 200 / 0.20s | 200 / 0.22s | — | ✅ |
| /market/realtime/portfolio | 200 / **16.67s**，38 条（23 live + 15 场外 null，见 R196） | 10.04s（15 nav + 23 实时） | ≤3s | ⚠️ 慢源 + nav 全失败登记，周末形态 |
| /admin/factor-health | 200 / **6.75s**，3 symbols healthy（25-26/39） | 5.79s | ≤2s | ⚠️ 登记（同量级，未定性回归） |
| /admin/llm/health | 200 / **15.55s** | 24.2s | — | ⚠️ 维持登记（好转，仍慢） |
| /market/sectors/heat | 200 / 3.32s | 2.47s | — | ✅（周末慢，内容正常） |
| /factors/active | total=38，no_data=6 / static=12 / warn=20（计数逐项一致） | 同 | — | ✅ |
| WS 直连 :8000 ×3 | 101（news 快照 571B / portfolio hello / task 无快照握手 OK） | 同 | — | ✅ |
| WS 经 nginx :80 ×3 | 101（同上） | 同 | — | ✅ |

### 2.2 主动触发新数据验证

- `POST design-async`（balanced, 500000, enhanced）→ task 104（pending→quick_ready→completed）→ **design 62**
 （quality=full，etf_count=29，text 7541 字，regime=range_bound，session=closed）。
- `POST strategy-check-async`（空体→默认组合）→ task 105 completed → **check 143**
 （LLM 403→规则兜底，text 9177 字，is_fallback=True/llm_layer_ok=False）。
- 去重探针：同参连击两次 → 同返 task 106（pending→running→completed，单执行）→ **R192/D 后端生产实证** ✅。
- 附带：09-18 旧记录（design 60/61、check 141/142）为数据卷残留，非本轮触发。

### 2.3 design 62 层预算 + 结构五问（R181 维持）

- plans 三方案 Σ=1.0000，max 0.25/0.25/0.30 ≤ 30% ✅；CASH 行三方案均有（25%/25%/29.98%）✅。
- 层预算内：保守 core 0.45≤0.5 / sat 0.2≤0.2 / def 0.1≤0.15；平衡 core 0.5 / sat 0.2 / def 0.05；进攻 core 0.35≤0.6 /
  def 0.05≤0.05；进攻 sat 0.3002 vs 0.3（+2bp，`risk_controls.py:398-401` 无容差即时缩放在**缩前值**上执行，
  终值 0.3002 系 4 位小数展示舍入：0.0429×5+0.0857，Σ 仍 1.0——记观察，不记 R）。
- normalize_segment 分组查重：10/9/10 segs，0 重复 ✅（`SECTOR_ETF_MAP` + 名称回退双源；159338 等 9 码无池内映射走回退）。
- market_context：regime=range_bound、session=closed；与 check143 一致 ✅。

### 2.4 check 143（R186/R191/G 实证）

- summary=`LLM …超时（30s…规则引擎兜底）（最后错…403 Forbidden…openrouter.ai…因子覆盖 33.3%`；
  DB `is_fallback=True/llm_layer_ok=False/report_quality` + 诚实横幅 ✅ **R186 维持**。
- suggestions 30 行复合分 19 个离散值（top -0.779 仅 6/30），-0.21 零出现 ✅ **R191 维持关闭**。
- `divergence_detail` 键存在但 30/30 null：P2/P3 分支（sell+≥0.5 / buy+≤-0.5）本轮无命中；
  常见 sell+中性→hold（else，`strategy_check.py:1333-1350`）不设明细 → **R199**。
- regime=range_bound，与 design62 一致 ✅。

### 2.5 R177/R178/资讯（维持）

- 创新药 sector=1 ✅；红利 index=19 ✅；创新药 all=13 ✅。
- headlines 15 + macro 6 + global 8 = 29（round56 为 15+4+8=27；macro +2 系一周新资讯，内容抽查正常）。

### 2.6 对照验证矩阵（round56 §2.6/§6 + round54 遗留）

| round 项 | 预期 | 本轮实测 | 结论 | 证据 |
|---|---|---|---|---|
| R186 envelope/超时旗语 | 兜底必 fallback 旗语 | check143 + task106 双实例三旗语一致（403 分支） | PASS 维持 | c143.json / t106s.txt |
| R187 vue 守卫 | 0 rejection | 568 passed（+16 新用例），0 rejection，仅 router-link benign warn | PASS 维持 | vitest 两轮 |
| R188 熔断隔离 | 全量不 FAIL | 3268 passed / 0 failed（+41 新用例，`-n 2` 377s） | PASS 维持 | pytest 全量 |
| R189/E′ 回落+DHC | 默认调起可用；DHC 恒汇总 | smoke 21/21（[INFO] 回落）；DHC 13/13 134s | PASS 维持 | e2e smoke / DHC |
| R179 双告警 | 暂缓存续 | 39.6s + 39.9s 并存 | 维持暂缓 | backend log |
| R180 空 kw | 暂缓存续 | 未复测（与本轮 R 系列无交叉，沿用 round56 结论） | 维持暂缓 | — |
| R181 去重 | 零重复 | design62 零重复（双源映射） | PASS 维持 | dup62.py |
| R182/R184/R183/R185 | 无回归 | fh healthy×3；6/12/20 逐项一致 | PASS 维持 | fh/fa57.json |
| §6#8 R192/D | 同参去重生产实证 | 连击同返 task106 单执行 completed | PASS 关闭 | dedup1/2.json |
| §6#9 G | 背离结构化展示 | 键在位但 30/30 null，常见形无 why | 半生效→R199 | c143b / 代码 |
| §6#10 H | 分配表现金行 | plans 均含 CASH；前端渲染仅 vitest 代证 | 后端✅/前端📋 | struct62 / spec |
| redundant/advice 批 | 不回归 | valuation/PE/indices 并发在 HEAD 未专项验证 | 未覆盖（声明） | §2.8 |
| round54 抛光/四态 | 走查 | 无浏览器走查；smoke+build+vitest 代证 | 📋 遗留 | §2.8 |

### 2.7 性能与回归基线

- e2e 分段：smoke 21 + portfolio 65 + news 14 + admin 15 + ws 2 + health 4 + market 17 = **138 ALL PASS**。
- pytest `-n 2`：3268 passed / 11 skipped / 0 failed；vitest：47 files / 568 passed。
- 周末慢三项（realtime 16.67s / fh 6.75s / llm-health 15.55s）记性能债 +「待交易时段复测」，不定性回归。

### 2.8 补测结果（2026-09-19 13:30-14:10，用户指令补齐；第二实例 `--no-build` 复用已有镜像起）

> 注：13:31 直接 `up -d` 曾再次触发 backend 构建（configs 含 build 段；内容无变，新镜像验明仍=HEAD）+
> frontend 构建失败致整组 abort；改 `--no-build` 起成功。`up` 何时触发构建待查（非本轮重点，记录现象）。

**Lighthouse**（Edge 153 headless + CHROME_PATH，lighthouse 13.4.1，2 采样/页；EPERM 仅系跑后 tmp 清理噪音，结果有效）：

| 页面 | perf | a11y | BP | SEO | LCP | CLS | TBT | 硬门禁 |
|---|---|---|---|---|---|---|---|---|
| `/`（真看板） | 66/67 | 96/96 | 96/96 | 91/91 | ~4.0s | ≤0.041 | ~540ms | PASS（≥60/<0.1） |
| `/dashboard` | 98/99 | 95 | 100 | 91 | ~1.9s | 0.035 | ~90ms | **无效——404 页**（DOC-2） |

- `/` perf 中位数 67：低于 round56 交易时段 85；server-response 0ms（nginx 本地），主因 JS 包（unused-javascript 151KiB/750ms，echarts vendor 558KB 既有）+ 仿真 CPU；记性能债观察，不定性回归（待交易时段复测）。
- **DOC-2**：`router/index.js` 仅定义 `/`（name=dashboard），无 `/dashboard` → SPA 回落渲染 NotFound
 （DOM 7452B、has-404=True、text 509 字）。round56 §2.8「Dashboard Perf 95」同为 404 页读数，一并订正。

**浏览器走查**（Edge headless `--dump-dom --virtual-time-budget=12000`，5 路由）：

| 路由 | 状态 | 内容实证 |
|---|---|---|
| `/` | loaded（无空白/报错） | 全球指数真值（上证 3911.87 +0.94%、创业板 +2.25%、科创50 +2.89%、欧股约 -1.5%）；组合摘要 ¥735,000/+1.22%/场内外拆分/更新 13:41:28；watchlist/热点板块 top10/资讯 level+stars 均渲染；WS 已连接徽标 |
| `/news` | loaded | 98 news-item，level×80/stars×30 |
| `/portfolio-analysis` | loaded | 持仓（159338×4）+ weight/pnl 渲染 |
| `/ai` | 模式卡渲染 | 智能设计/策略检查/任务列表三卡 + 因子说明；任务行未在 headless 抓到（limitation，G/H 渲染以 vitest spec 为准） |
| `/dashboard` | **404** | NotFound（见 DOC-2） |

- 交叉核对：看板科创50 +2.89% / 创业板 +2.25% / 恒生科技 +2.20% vs design62 文本「科创50大涨2.9%/创业板领涨2.2%/恒生科技+2.2%」一致 ✅。
- 空/错态：本轮数据源齐，未触发空/错 UI（形态未见即不硬验；loading 骨架在各页源码级存在）。

**advice 批生产实证**（`POST /api/v1/analysis/llm-advice/stream`，沪深300 PE 问，200 / 35.8s）：

- 相位：`calling_model` + **`fetching_valuation`** → L1v2 valuation 意图路由 live ✅。
- 数值：PE-TTM 14.63 / PE-LYR 16.92 / 股息率 2.63% / 20 日 PE 分位数 0.26，`as_of 2026-09-18`（周五新鲜）✅。
- 自编 ETF 码：答案 6 位码 0 个 → 无幻觉违反（980a1c5 prompt guard 空生效，记 vacuous-pass）。
- 5 指标并发：代码层 gather（`routers/analysis.py`）已读确认 + 本次取数成功（未触 25s cap）；延迟分布不可外部观测，诚实标注。

**patrol --full**（1447s，exit 1）：PASS 7（L1-unit / L2-alloc-invariants / L2-llm-exclusion /
L4-routes / L4-purity / L4-async / L5-frontend）；FAIL 4 = 3 预算性（L2-e2e 900s、L2-health 120s、L3-perf 120s——
周末慢源下预算不足；e2e 分段 138 / DHC 13/13 本轮已独立全过，不定性产品回归）+ 1 治理性：

- **F1（流程债）L4-baseline FAIL：test file count 328 > baseline 320**——advice 批新增测试文件未并入既有文件、
  未走「提 BASELINE + review」流程。方案：下次实施轮二选一（并入既有文件 / 提 BASELINE + review 后 commit）。
- **F2（lint 债）L4-ruff WARN**：`hub/_valuation.py:22/:154` 非法 `# noqa`（advice 批）。方案：修正为合法码或删除，一行级。
- tests_ok.json 本轮已写（head=980a1c5）但全量 exit 1——**该凭据仅对应 L1 通过**，§0#18 口径标注，不得作全量绿引用。

原「未执行」四项至此全部关闭（Lighthouse/走查/patrol/advice），残留观察：`/` perf 67 vs 85（待交易时段）、
F1/F2（待实施轮）、G/H 无 headless 实证（以 spec 为准）。

---

## 3. 分析结果质量审查（四问法 + 结构五问）

对象：design62（LLM 层成功，7541 字）与 check143（规则兜底，9177 字）。周末形态：涨跌为周五收盘滞后，session=closed 已披露。

| 判断原文 | 事实/推断 | 数据支撑 | 与当下行情一致? | 结论分级 | 修复建议 |
|---|---|---|---|---|---|
| design62 三方案 Σ=1.0、max≤0.30、CASH 行齐 | 事实 | struct62：Σ=1.0000×3；max 0.25/0.25/0.30 | —（内部一致） | 合理 | — |
| design62 现金 25/25/30% + ETF 数 10/9/10 | 事实 | 表格（不含现金计数）vs plans（含 CASH 11/10/11）交叉一致 | ✅（进攻 30% 满仓逻辑自洽） | 合理 | — |
| design62「震荡市态调整系数为 0」 | 推断→事实化 | 自带依据（regime=range_bound 实读一致） | ✅ | 合理 | — |
| design62 逐标的 RSI/动量离散值（510300 -3.797 / 511090 +4.504 / 518880 -1.511） | 事实 | mom62.txt 点分值 | ✅ | 合理 | — |
| design62 6 标的动量 +0.023/+0.004 复读呈现为个测值 | 推断（文本暗示个测） | 三元组 6 连 clone（§4.1 R197）；输入失真则归因失真 | ⚠️ 输入存疑 | 部分合理 | R197 |
| design62 同行「综合信号 -0.01」与脚注「综合信号 -1.05/-3.16」并存 | 事实（文本内） | d62.txt:32-33；rationale.py:244-248 vs allocation_engine.py:2047 | ❌ 同标签异值，内部矛盾 | 部分合理（命名层） | R198 |
| design62 511090/518880 负信号防御配置+脚注警示 | 推断 | 脚注如实警示，配置本身在预算内 | ✅（警示与配置自洽） | 合理 | —（措辞由 R198 覆盖） |
| design62 结构五问 | 事实 | dup62：10/9/10 segs 零重复 | — | 合理（R181 无复发） | — |
| check143「市态：震荡」+ 覆盖 33.3% + 15 缺数据声明 | 事实 | regime=range_bound；summary 全文 | ✅（披露诚实） | 合理 | — |
| check143 逐标的离散因子分（-1.95/-1.38/0.27…）+ 模板建议 | 事实+规则模板 | 19 离散值；兜底横幅自洽 | ✅（形态诚实，信息量低） | 合理×8 / 部分合理×2（模板复读） | 维持 round55 既有建议 |
| check143 sell+hold 偏离（159338/588000/510880/513120…） | 推断（F10 有意） | else 分支 reason 自带解释；detail 30/30 null | ✅（设计如此，tag 无 why） | 部分合理 | R199 |
| check143 三旗语 fallback | 事实（DB 值） | 与 summary 一致（双实例） | —（内部一致） | 合理（R186 维持） | — |

**汇总**：可采信 9 条 / 需修正 4 条（R197 输入 + R198 命名 + R199 tag + 模板复读标注）/ 臆断 0 / 失效 0。
**数据抽查**：Σ=1−现金 ✓；占位值（RSI 50.0/动量 +0.300/ln_mcap 0.0）未出现 ✓（但 +0.023×5 系 R197 输入克隆，
非经典占位）；as_of/session=closed ✓；regime 双端一致 ✓；价格/涨跌：场内 23 live，场外 15 null（R196）。

---

## 4. 问题分析与修复方案（只写方案不写代码）

### 4.1 R 系列新发现

| 编号 | 发现 | 根因机制链（file:line） | 严重度 |
|---|---|---|---|
| R196 | **场外 null 价挂 `last_close` 标签**：realtime 15 只场外联接 `price=null + is_estimated=true + estimate_source=last_close`；`market_service.py:1337` nav 失败即标 last_close（无值也挂名）；`market_service.py:1330` index 回退为空时 price=None。周末成分：fetch_fund_nav 10× 失败日志（11:28:34/42，源侧）；标签错误本身与周末无关（任何 nav 中断均复现） | `market_service.py:1308-1340`（_fetch_one）→ `:1337` 标签分支 → `:1330` 空回退；`routers/market.py:874-901` 归一化保留该形状 | P3（诚实性标签 + 下游 null  handling 未验） |
| R197 | **设计回报三元组 6 标的克隆**：512890/510050/515880/512880/513180/513120 的 change_pct/return_1m/return_3m =（0.016/0.01/-0.015），恰为 159338 精确值（0.016182/0.010422/-0.014896）的 3 位舍入；连带矩阵 momentum +0.023×5；文本按标的呈现为实测。已验链：registry 计算（`factor_registry.py:443-460` round-4）← kline_cache（`market_data_hub.py:339-351`）；**克隆源头未定**（周末缓存陈旧/共享序列 vs  coarse 回退，待交易时段复测二分） | `factor_registry.py:435-460` ← `market_data_hub.py:339-351` ← `_kline_cache`；呈现 `rationale.py:227-229` | P2（数据正确性；若交易时段消散则降 P3/销账） |
| R198 | **同行「综合信号」三值并存**：行文 -0.01（rationale 聚合 `rationale.py:244-248`）vs 脚注 -1.05/-3.16（因子分 `allocation_engine.py:2047`）vs 点分 overall 0.0（`factor_registry.py:1675`）。同标签三口径，用户无法判断持仓真实信号 | `rationale.py:234-248` + `allocation_engine.py:2018/2047` + `factor_registry.py:1675` | P3（命名混淆，有误导面） |
| R199 | **G 覆盖缺口**：else 分支 sell/buy+hold（`strategy_check.py:1333-1350`）不设 divergence_detail；check143 30/30 null，≥4 行 sell+hold 前端 tag（`StrategyCheckResult.vue:66-68`）回落通用文案无 why（reason 段虽有解释，tag 无透出） | `strategy_check.py:1273-1350`（仅 P2/P3 设键）→ `StrategyCheckResult.vue:66/isDiverged:157-162` | P3（tag 无 why；reason 段有解释，面小） |

### 4.2 测试防护体系缺口分析

**1) 防护体系现状（本轮实测）**：pytest 3268 绿 / vitest 568 绿零 rejection / e2e 分段 138 全过 /
DHC 13/13 134s / 双镜像内容验明 HEAD。R186-R189 补齐守卫全部在位且生效；R192-D 去重生产实证通过。

**2) 逐发现映射**：

| 发现 | 最应拦截的防护层 | 为何未识别 | 应补的守卫 |
|---|---|---|---|
| R196 | market_service 单测（场外 null 价标签） | 现有断言只验 estimate_source 非空（watchlist.md:99 语义），不验「有标签必有值」 | 单测：nav 全失败 + index 为空 → estimate_source 不得为 last_close（须 unavailable 类）且 price null；负向：旧实现必输出 last_close |
| R197 | design 链路单测（输入多样性） | 断言只验输出结构/预算，不验「多标的同源输入」；周末克隆在工作日单测（mock 离散值）中恒不复现 | 单测：构造 6 只同 K 线输入 → 触发「共享输入」WARN 标注或显式降置信；e2e 内容断言：design factor_breakdown 三元组方差 > 0（工作日） |
| R198 | design 文本单测（术语一致性） | 只验脚注存在，不验「同行同标签值一致」 | 单测：渲染行内全部「综合信号」数值 → 同行多值必 FAIL（或脚注改名后断言标签唯一） |
| R199 | strategy_check 单测 + 前端 spec | G 单测只覆盖 P2/P3 分支；spec 只验有 detail 时渲染，不验「tag 显示但无 detail」 | 单测：else 分支 sell+hold → detail 非 null（含阈值解释）；spec：detail 缺失时 tag 不显示通用文案（或显示 reason 摘要） |

**3) 系统性根因归并**：①「有披露无区分/无值有标签」（R196/R197；round56「兜底质量」类延续——诚实披露 vs 有效语义是两层要求）；
②「同词多义」（R198；新出现——三层信号演进各自命名未统一）；③「分支覆盖不全」（R199；新出现——G 只验 P2/P3，else 主干无守卫）。
总体评价：防护体系缺的是「**语义一致性断言**（标签↔值、术语↔口径、tag↔why）」一层，而非更多用例数量。

**4) 补齐设计（只写方案，不写代码）**：

- **方案 A（P3，R196）**：`_fetch_one` nav 失败且 index 回退为空时 `estimate_source="unavailable"`（price 保持 null），
  前端该形状渲染「维护中」而非估值徽标。影响 `market_service.py:1326-1338` + 1 单测 + 前端徽标分支。
  验收：复现输入 → unavailable + null；负向：旧实现必 last_close。另：calculate/pricing 对 null 价路径补单测（当前未验）。
- **方案 B（P2，R197，推荐交易时段复测先行）**：下个交易日 9:30-11:30 重触发 design-async，带 6 标的 factor_breakdowns 取证：
  若三元组离散 → 销账（周末性，关单）；若仍克隆 → 方案 C。验收：复测记录 + 输入/输出对照表。
- **方案 C（P2，R197，若复测维持）**：审计 kline_cache 键装配（symbol→序列映射）+ 周末陈旧序列共享路径；
  对「多标的同序列输入」显式标注并降置信，不静默参与聚合。影响 hub kline 段 + registry 输入校验 + 1 单测。
  验收：同序列输入 → WARN 标注；负向：旧实现静默聚合。
- **方案 D（P3，R198）**：脚注改称「因子综合分」（与行文「综合信号」解耦）或统一用 rationale 口径；
  二选一（推荐改名：动法最小，决策表与聚合不动）。影响 `allocation_engine.py:2047` 文案 + 文本单测标签唯一断言。
  验收：同行「综合信号」标签值唯一；负向：旧文案必多值。
- **方案 E（P3，R199）**：else 分支 sell/buy+hold 同样 emit `divergence_detail`（阈值解释：因子中性未达 ±0.5，
  信号单侧不足以翻行动）；前端不动（已有回落渲染）。影响 `strategy_check.py:1333-1350` + 单测 + spec 更新。
  验收：check143 同形输入 → 30 行中 sell/buy+hold 全带 detail；负向：旧实现 30/30 null。
- **方案 F（流程）**：诊断模板「WS 探针」条目追加「msys2 python 无 websockets，用 py312」环境备注（无代码影响；待「round实施」时改模板）。

### 4.3 与 round56/round55 的关系

- round56 §6 #8（R192/D）本轮生产实证关闭；#9（G）半生效转 R199；#10（H）后端就绪、前端待浏览器。
- round56 R191/性能债/Lighthouse §6#6/#7：本轮周末基线重建（realtime 16.67s / fh 6.75s / llm 15.55s），待下个交易时段复测销账。
- round55 §6#3（patrol 规则）/#4（P1-5）维持不变；R179/R180 维持暂缓。
- R192-D 去重与 advice 批（valuation/PE/indices 并发）无交叉；advice 批本轮未专项验证（§2.8 声明）。

---

## 5. 三轮 Review 记录

### 5.1 Round 1 — 事实核对

| 项 | 核对 | 结论 |
|---|---|---|
| 构建失败 + overlay 链 | build57.log:66-89 拉取错；overlay Dockerfile + dist 字串三命中 | ✅ |
| backend 镜像 = HEAD | 容器内 divergence_detail×2 / deduped×5 = 宿主值 | ✅ |
| warmup 双告警 | backend log 39.6s 新 + 39.9s 旧；instruments 1741 / indices_meta 1106 | ✅ |
| R177/R178/news/因子 | sector=1 / index=19 / all=13；15+6+8=29；fh healthy×3；6/12/20 | ✅ |
| design62 | Σ=1.0×3 / max≤0.30 / CASH×3 / 零重复 / regime 一致 | ✅ |
| check143 三旗语 + 33.3% | summary 全文 + DB 实读；-0.21 零出现；detail 30/30 null | ✅ |
| R196 15 null | rt57.json falsy-price 15 全场外 + estimate last_close；nav 失败日志 10× | ✅ |
| R197 6 克隆 | d62.json 三元组 6 连（0.016/0.01/-0.015）vs 159338 精确值 | ✅ |
| R198 三值 | d62.txt:32-33（-0.20/-0.60 vs -1.05/-3.16）+ 三处 file:line | ✅ |
| e2e 138 / pytest 3268 / vitest 568 / DHC 13/13 | 各输出尾行 | ✅ |

### 5.2 Round 2 — 逻辑一致性

- 周末慢（realtime 16.67s）vs 内容正常（23 live + 15 诚实 null）：慢归慢、假归假分离 ✅。
- R197「输入克隆」vs round56「无占位」：上轮离散（-2.424~+1.288）vs 本轮 6 连同值——非口径差异，属新现象 ✅。
- G「已实施」vs 30/30 null：实施覆盖 P2/P3，常见形在 else——「半生效」定性准确 ✅。
- 2bp 超标记观察不记 R：`risk_controls.py:398-401` 无容差但作用于缩前值，终值偏差系展示舍入——分离标注 ✅。

### 5.3 Round 3 — 完整性

- 验证窗口标注：实时类全标周末形态；R197/B 复测窗口明确 ✅。
- 未执行诚实标注：首轮四项未执行（§2.8）→ 用户指令后 13:30-14:10 全部补测（§2.8 改写为补测结果 + §5.4 复核）；
  残留观察（`/` perf 67、F1/F2、G/H headless 未实证）已显式登记 ✅。
- 未决项：R196/R197/R198/R199（§6）+ 周末性能债复测 + P1-5（沿用）✅。
- 合规：全程未写修复代码（唯一产物=本文档 + 探针不入仓 + host 构建副产物 dist/gitignored）✅。
- 工作树外状态：settings-store.json 代理注入（未生效，已留 bak，§6#5 决策）；未提交归档改动（round53/54/55 已 staged 进 archived，属他轮收尾，本轮不动）✅。
- round35/36-B5 不归档：仍有活跃引用（engine-dedup-layers.md 等），按模板§文档归档#2 保留；round56 保留（承载下轮 R197/性能债复测基线）✅。

### 5.4 Round 4 — 补测复核（2026-09-19 14:10，用户指令补齐后追加）

| 项 | 核对 | 结论 |
|---|---|---|
| LH 4 采样落盘 | lh_home1/2 + lh_dash1/2 json + 中位数（`/` 67 / 404 页 98-99） | ✅ |
| DOC-2 `/dashboard` 404 | router/index.js 无该 path；dom_dash has-404=True；round56 同口径复核（其亦跑 `/dashboard`） | ✅ |
| 走查 5 DOM | home 真值（3 数 vs design62 文本一致）/ news 98 / portfolio 持仓 / ai 三卡 / dash 404 | ✅ |
| advice SSE | advice57.sse（200/35.8s）：双相位 + PE 14.63/as_of 09-18 + 0 自编码 | ✅ |
| patrol exit 1 归因 | 7 PASS；3 超时=周末预算（分段 138/DHC 独立绿）；F1 328>320 / F2 noqa 行号 | ✅ |
| tests_ok 口径 | json head=980a1c5 + exit 1 并存 → 仅 L1 标注（§0#18），无假绿 | ✅ |

---

---

## 6. 决策点

> **拍板结果（2026-09-19，用户）**：#1–#5 采纳推荐；#9 并入既有测试文件（不提 BASELINE）；
> #10 未单独拍板（默认搭实施轮顺手修，待确认）。#2/#3/#4/#9/#10 涉及写代码，待「开始实施」指令。
> 拍板后固定收尾：① 本节已回填；② memory 同 name 覆盖更新（待会话工具）。
>
> ### 实施回填（2026-09-28，commit `03ed659`）
>
> | # | 决策 | 状态 |
> |---|---|---|
> | 1 | R197 方案 B：下个交易日 9:30-11:30 重触发 design 带 breakdowns（消散→销账，维持→方案 C） | 📋 仍待交易时段（未实施） |
> | 2 | R196 方案 A（unavailable 标签 + 前端维护中 + pricing null 单测） | ✅ 已实施（commit `03ed659`）——**前端徽标分支按「0 引用=脚手架」跳过**，见下方偏离登记 |
> | 3 | R198 方案 D（脚注改名“因子综合分”） | ✅ 已实施（commit `03ed659`） |
> | 4 | R199 方案 E（else 分支同 emit detail） | ✅ 已实施（commit `03ed659`） |
> | 5 | settings-store.json 代理键保留 | ✅ 已拍板（留，repo 外无代码变更） |
> | 9 | F1：新测试文件并入既有文件（不提 BASELINE） | ✅ 已实施（commit `03ed659`）—— 8 文件归位，320 ≤ 320 基线 |
> | 10 | F2 非法 noqa | ✅ 已实施（commit `03ed659`） |

**R196 偏离登记（前端部分未做，理由）**：方案 A 含「前端该形状渲染『维护中』而非估值徽标」。
实施前核查消费方（`explore` 子代理 + `rg` 双证）：`GET /api/v1/market/realtime/portfolio`
的报价形状**前端零消费**——`frontend/src/api/index.js` 的 `realtimePortfolio` 方法早已在
round35 FE1/RC-D 删除（零调用者），`WatchlistPanel.vue` 的「估/维护中」徽标读的是
**自选端点**（`/market/watchlist`）的另一条 enrich 链路，WS `/ws/portfolio` 只广播
`{type:'portfolio_changed'}` 不带报价。按 AGENTS.md「脚手架零容忍」不新增无消费方分支，
故前端部分**暂缓**；待该端点真有前端消费方时再补徽标（后端语义已就位，不阻塞）。

**实施中新发现（已修，非本轮 R 项）**：`test_chat_session_endpoint.py` 的 `client`
fixture 原本 `with TestClient(app)` 触发 app lifespan。F1 归位把该文件用例从 3 个加到
8 个后，lifespan 次数随之翻倍 → 残留后台任务占满共享 `run_in_thread(executor="long")`
线程池 → 同进程后续 mock 取数用例（`test_fundamental_fetcher::TestFetchFundScale`）8s
超时被吞成 `None` 产生**跨文件假失败**；长驻 app 的后台循环写运行时配置又污染
`test_llm_provider_failover` 的 provider 期望。处置：该文件 fixture 改为
**不进入 lifespan**（只需路由，LLM/上下文均已 mock）。实测 177s+FAIL → 77s 全绿。

**验收期结论（commit `03ed659`）**：pytest 全量 3340 passed / 0 failed；hook 等价
受影响批次 503 passed；mypy 151 文件 Success；check_routes / check_engine_purity /
audit_async_blocking / P3-6 基线（320≤320）/ smoke_startup 全过。
`patrol --full` L2-e2e FAIL 归类**环境性**（`NameResolutionError: '::1'` + 8 次连接
STORM，known-env-issues §1.1；:8000 上跑的是改动前的老后端，且 e2e 之外 `::1` 解析正常），
非本轮回归；实值链路（realtime/因子/资讯）未在干净后端复测 → **待交易时段复测**。

| # | 决策 | 选项 + 推荐 + 影响范围 | 状态 |
|---|---|---|---|
| 1 | R197 - clone | **推荐方案 B 交易时段复测先行**（9:30-11:30 重触发 design 带 breakdowns；消散→销账，维持→方案 C）。影响：诊断动作，无代码 | 待拍板 |
| 2 | R196 null 标签 | **推荐方案 A**（unavailable 标签 + 前端维护中 + pricing null 单测）。影响 `market_service.py:1326-1338` + 前端徽标 + 2 测试文件 | 待「开始实施」 |
| 3 | R198 同词多义 | **推荐方案 D 改名**（脚注→因子综合分，决策表不动）。影响 `allocation_engine.py:2047` + 1 文本单测 | 待「开始实施」 |
| 4 | R199 G 缺口 | **推荐方案 E**（else 分支同 emit detail，前端不动）。影响 `strategy_check.py:1333-1350` + 单测/spec | 待「开始实施」 |
| 5 | 宿主 settings-store.json 代理键 | 留（文档化现状；未来构建仍需走 overlay 或修 Desktop 渠道）/ 删（恢复原状，bak 在探针目录）。**推荐留**（repo 外变更，无代码影响；删了下次构建重踩坑） | 待拍板 |
| 6 | 周末性能债复测 | realtime/fh/llm-health + R197/B，下个交易日窗口一并复测（附带 `/` perf 67 vs 85） | 待交易时段 |
| 7 | patrol --full | **已跑（exit 1，见 §2.8）**；F1/F2 见 #9/#10；规则本身沿用（下次实施轮交付照常跑） | ✅ 已执行 |
| 9 | F1 baseline 328>320 | 并入既有测试文件 **或** 提 BASELINE + review（advice 批遗留）。影响 scripts/check_test_baseline.py + 测试文件布局 | 待「开始实施」 |
| 10 | F2 非法 noqa | 修正 `_valuation.py:22/:154` 为合法码或删除（一行级，advice 批遗留） | 待「开始实施」 |
| 8 | P1-5 | 排期不变（加急已撤销，round56 §6#4） | ✅ 沿用 |

> 拍板后固定收尾：① 本节回填；② memory 同 name 覆盖更新。

---

## 7. 本轮验证命令备忘（复现用）

```bash
# 容器（prod + diag overlay；registry 不通时 backend 先 build，frontend 走 overlay）
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod build backend
# 宿主构建前端（node 主版本对齐镜像）+ overlay（frontend/.dockerignore 排除 dist，须经外部上下文）
cmd /c "npm run build"   # workdir frontend
docker build -t etf_surge-frontend:latest <含Dockerfile(FROM etf_surge-frontend:latest)+dist 的目录>
docker compose -f docker-compose.yml -f docker-compose.diag.yml --profile prod up -d
# 探针（宿主代理常驻，统一 --noproxy '*'；输出 -o 落盘，禁管道直解；WS 用 py312）
curl.exe --noproxy "*" -s -o rt.json -w "%{http_code} %{time_total}s" http://localhost:8000/api/v1/market/realtime/portfolio
# e2e 分段（默认 host，E′ 回落自动生效）
python scripts/verify_e2e.py --smoke
python scripts/verify_e2e.py --module portfolio|news|admin|ws|health|market
# 单测
python -m pytest -n 2 -q            # backend（-n auto 有页面文件风险，见 known-env-issues §1.6）
cmd /c "npm test"                   # frontend
# DHC（宿主跑，预算 300s+；周末卡死按「检查器未完成」口径，不记产品 FAIL）
python scripts/data_health_check.py
# 去重探针（同参连击两次 → 同 task_id）
curl.exe --noproxy "*" -s -X POST http://localhost:8000/api/v1/portfolio/strategy-check-async -H "Content-Type: application/json" --data "@check_body.json"
```
*诊断产物：C:/Users/Public/etf_probe/（会话级临时目录）；容器诊断完成后回收。未收到「round实施」不写修复代码。*

---

## 9. 交易时段复测（2026-09-29 周二 13:00-15:00 下午盘，commit 待回填）

> 窗口说明：2026-09-29 为**交易日**，13:00 下午盘开盘后开跑。方法：真实源 + 真实
> LLM，无 mock；HTTP 走进程内 `TestClient`（`::1` 字面量在本机解析不稳，见
> known-env-issues §1.1），异步任务端点那一轮**开启 lifespan**（否则任务 worker 不存在）。

### 9.1 通过项（实盘实证）

| 项 | 结论 | 证据 |
|---|---|---|
| **R04 模板收敛**（用户原始抱怨「3 处输入未提供/暂无法验证」） | ✅ **0 次** | 端到端 `llm-report/stream` 产出 2366-2432 字 / 6 章 / 28.2s / 无 SSE error；全文「未提供」+「暂无法验证」命中 **0** 次 |
| **组合设计端到端** | ✅ 真 LLM 报告 | task 132：`running(5s) → quick_ready(30s) → completed(110s)`；日志 `[design_pipeline] report saved to design_id=75 (6342 chars, quality=full)` |
| **R03 平衡型防御锚扩容** | ✅ 生效 | design 75 balanced 防御层 = **2 只**：`30年国债ETF鹏扬` + `黄金ETF华安`（改前仅黄金 1 只） |
| **R197 三元组克隆** | ✅ 未复现 | 三方案 0 个出现「≥3 标的同 (return_1m, return_3m)」元组 |
| **R198 信号标签唯一** | ✅ 生效 | design 75 报告正文：`综合信号 x0` / `因子综合分 x1`（脚注改名已在实盘报告可见） |
| **R199 divergence_detail** | ✅ 生效 | 策略检查兜底行实测 `divergence_detail = {signal_direction: neutral, factor_direction: neutral, factor_score: -0.314, threshold: 0.5, explanation: ...}`——正是 check143 曾 30/30 为 null 的主干 hold 分支 |
| **R196 「有标签必有值」** | ✅ 盘中 0 例外 | `/market/realtime/portfolio` 38 行、场外 15 只、null 价 0 只、`label_without_value=0`、`priced=38/38` |
| **R06 端到端**（§D） | ✅ | 直连路径 29.5s / 34.9s、`is_fallback=False`、`usage 10254 tokens` |
| **性能债：realtime/portfolio** | ✅ 大幅改善 | **0.84s**（round57 周末基线 16.67s，~20×） |
| **性能债：admin/llm/health** | ✅ 大幅改善 | **1.11s**（周末基线 15.55s，~14×） |
| **性能债：admin/factor-health** | ⚠️ 仍超阈值 | 6.59s（周末 6.75s；阈值 ≤2s）→ 维持性能债登记 |

### 9.2 未通过 / 环境性（逐项归因，不含糊）

| 项 | 现象 | 归因 |
|---|---|---|
| **R06 全市场宽度** | `fetch_market_breadth()` 3 次全返 `{}` | **源不可达**（push2delay；13:00 前曾成功取到 total=100/up=21/down=56/成交额 2.45e10，证明确为间歇性）。设计行为正确：回退 `{}` → prompt 走「（数据源暂不可用）」占位，未报 0 家伪值 |
| **R01 板块与风格段** | `compute_sector_momentum()` 连续 2 次返 **0 行**（各 ~14s，命中内部 15s 超时） | **源不可达**，非接线缺陷。`update_sector_cache` 只在 `if momentum:` 时写缓存，故空返回即保持空；`get_sector_momentum` 盘中不回退快照（设计如此，诚实降级）。同窗口 `hot_plates` 正常（11 行）→ 佐证是板块动量源单点问题 |
| **策略检查走异步任务时回落** | task 131：`report_quality=fallback` / `is_fallback=true`，summary `LLM 分析超时（15s 未返回…`，`因子覆盖 16.7%` | **新发现，需用户决策（见 §9.3）**：非本轮回归 |

### 9.3 新发现（超出本轮清单，待决策）

**N1：策略检查经异步任务仍回落——根因是「分档预算无 provider 延迟余量」，不是单纯档位太小**

追查过程（三次实测互相修正，故以本条为准）：

| 检查 | 因子覆盖 | 有真实因子值的持仓 | 命中档位 | 结果 |
|---|---|---|---|---|
| #161（13:48，design 之前） | 16.7% | **0/30**（`factor_scores` 是空 `{}`，非中性默认） | `all_empty` = **15s** | 超时兜底 |
| #162（14:01，先 warm 再查） | **33.3%** | **15/30** | `partial` = **30s** | 仍兜底 |

- **更正先前判断**：#161 的 15s 档**触发是准确的**（`all_empty = filled_factor_count == 0`
  成立），不是误分类——「上下文不足 → 快速兜底」正是该档的设计意图（round7 P25）。
  先前「15s → 30s 即可」的建议**证据不足，撤回**。
- **#162 暴露真因**：`partial` 档 30s 与现役 provider 实测 27.2/29.5/31.5s **几乎零余量**，
  再叠加开局那条必死的 Zen 腿（约 1s）即被砍。summary 记录的即：
  `LLM 访问被拒绝（访问被拒绝，30s 未完成…403…opencode.ai/zen…）`。
- **性质**：非本轮回归。分档阶梯与 provider 延迟是两条独立演进的曲线，在「无 provider 可用」
  期间无法暴露；R06 修好链路后二者才第一次相撞。
- **建议（需拍板，本轮未实施）**：把「档位」改为**按 provider 实测延迟留余量**（如
  `partial` 档 ≥ 实测 p95 × 1.5），而非固定 15/30/180；或对确定性失败腿做**首跳前**短路
  （R05 现只拦 403，Zen 的 400 由 F8 熔断兜住，仍要付一次 ~1s 试探）。
  **未擅自改**：有 `tests/test_round14_llm_budget_consistency.py` 锁定预算-重试一致性，
  属显式决策点。

**N1 附带结论：R04 在生产路径实证通过**

#162 的 summary 以 `LLM 访问被拒绝` 开头——即 `03ed659` 新增的 `FORBIDDEN_PREFIX`。
改前同一 403 会被 else 分支误标 `LLM 分析超时`（§B2 根因）。本次为该修复的**首个实盘证据**，
且同时证明 R186 口径同步有效：`is_llm_fallback_summary` 仍能识别新前缀（`is_fallback=true`
与前缀一致，未出现「summary 写兜底而 is_fallback=False」矛盾）。

**N2：`app/tasks/startup.py` 两处 NameError 导致 2 个预热段从未执行 —— ✅ 已修复（commit `28bd820`）**

- 原始实证：warmup 日志 `design-data warmup failed (non-fatal): name '_kline_warmup_symbols' is not defined`
  与 `行情缓存预热 fast 阶段失败 (非阻塞): name 'refresh_market_cache' is not defined`。
- 根因（round35 巨文件拆分 Batch 5 把 main.py 代码搬进 `tasks/` 时 import 未同步）：
  ① `:182/:193` 调 `refresh_market_cache`，定义在 `app/tasks/market_refresh.py:19`，未导入；
  ② `:373` 调 `_kline_warmup_symbols`，定义在 `app/main.py:247`，未导入——且 `main.py:78`
  反向 import `startup.py`，**不能原地补 import**（循环依赖）。
- **定位方式（客观，非推断）**：`ruff check --select F821 app` 精确列出 3 处 undefined name
  （`:182`/`:193`/`:373`）。F821 本就在项目 ruff 门禁的 `"F"` 族内之所以长期未暴露，
  是因为 ruff 只作为 patrol 的 L4-ruff **软门禁（WARN 不阻断）** 运行。
- 修复（用户拍板 N2a + N2b 一起修）：
  ① `startup.py` 补 `from .market_refresh import refresh_market_cache`——该模块只 import
     `core.logging` / `services.market_data_hub`，不反向 import 本模块，**无循环风险**；
  ② 把 `_kline_warmup_symbols` / `_kline_warmup_holdings_symbols` **下沉**到
     `app/tasks/startup.py`（按该模块既有约定：定义在 tasks/、main.py re-export 保导入面）。
- **单测防复发（关键：patch 目标必须改）**：原 `test_stock_kline_warmup.py` 打的是
  `app.main.*`。下沉后那是 re-export 别名，而函数体在 startup 模块 globals 里查找
  `_kline_warmup_holdings_symbols` → **monkeypatch 会静默失效**（测试转真库查询仍可能绿）。
  已全部改指 `app.tasks.startup.*`，并加两条守卫：re-export 必须是同一函数对象、
  patch 目标字符串必须指向定义模块。
- **运行时前后对照（同一 7 段 warmup 序列，开 lifespan 实测）**：

  | 项 | 修复前 | 修复后 |
  |---|---|---|
  | `market_cache` 段 | `success=false, phase=fast_failed` | `done=true, success=true, phase=fast` |
  | `design_data` 段 | 未执行（NameError） | `done=true, success=true`（+121s，~30 只标的取 K 线占大头，故需比冒烟更长的观察窗） |
  | 4 段汇总 | 2 段失败 | **4/4 done 且 success** |
  | 日志 NameError | 2 处 | 0 处 |

  `ruff --select F821 app` 由 3 处命中变为 **All checks passed**（全 151 文件）。
- 验收：pre-commit 触发**全量 pytest 3342 passed / 11 skipped**（181.8s）、
  mypy Success 151 文件、warmup+结构相关 9 文件 109 passed、
  `test_stock_kline_warmup` 5 passed（3 原有 + 2 新守卫）、
  audit_async_blocking / check_routes / check_engine_purity 全过。
- **归属订正**：本轮两批 commit（`03ed659`/`688ad45`）均未触碰 `app/tasks/startup.py`
  （`git diff 1e7a5c3..HEAD` 空），属 round35 存量缺陷，由本轮复测发现并修复。
- 残留登记：① 启动成本上升（K 线预热与行情缓存段此前被跳过，现真实执行；
  warmup 在后台且 30s 预算告警为提示性）；② `main.py`/`startup.py` 的 3 处**存量 F401**
  （未用 `refresh_market_cache` re-export、`typing.Any`/`Generator`）经比对与 HEAD
  逐字一致，非本轮引入，未纳入本次改动。

**N3：warmup 30.8s 超 30s 预算阈值**（`instruments_sync 21.8s` / `indices_meta_sync 8.8s`）→ 维持性能债登记。

**N1 决策支持数据（2026-09-29 补测，read-only，未改任何代码/预算）**

| 测量 | 结果 |
|---|---|
| 现役 provider 延迟分布（生产调用路径 `llm_complete_with_system`，`max_retries=0`，847 prompt_tokens 代表性负载，6 次采样） | 11.4 / 14.0 / 15.4 / 17.7 / 20.7 / 23.9s；mean 17.2s、median 16.5s、max 23.9s，**6/6 成功** |
| 分档命中 | 15s 档 → 2/6 命中；**30s 档 → 6/6 命中**（该负载下） |
| 生产 strategy-check 真实 prompt 体量（**拦截 `llm_complete_with_system`、统计生产实际发送的字符串**，tiktoken `cl100k_base`） | **4,642 tokens**（system 1,334 + user 3,308，30 只持仓） |
| 真实 prompt 分段占比（实测） | `## 持仓分析` **2,992 tok = 90.4%**、`## 输出硬约束（Z26）` 231 tok = 7.0%、`## 市场状态` 58 tok = 1.8% |
| 真实 prompt 与上述计时样本之比 | **≈5.5x**（4,642 vs 847 prompt_tokens） |
| 客户端自身读超时 | `read=90.0s`（远宽于外层分档预算）→ **真正卡住的是外层 15/30s 分档**，不是 provider 超时 |
| 真实端到端（4.6k tokens 真实负载） | 27.2 / 29.5 / 31.5s —— **跨在 30s 档边界上** |

- ⚠️ **本项数值第三次更正，前两次都量错了对象**（此条比数字本身更值得记）：
  ① 首次用「CJK 1 token/字符」临时估算整份 60,532 字符 `holdings_json` → **≈44k / 52x**；
  ② 改用 tiktoken，但对**存储的 API 记录形状**逐字段求和 → **2,595 / 3x**；
  ③ **在 `llm_complete_with_system` 边界拦截、统计生产真实发送的字符串** → **4,642**。
  ② 仍然错对象：LLM prompt 由 `generate_strategy_check_report` 从 `market_data` +
  `factor_breakdowns` 现场拼装，不是 `holdings_json` 的字段和。
  **教训**：连换两次估法却没换被测对象，说明「换个算法重算」不等于「重新测量」——
  与下面 L2-e2e 那条同源，先确认量的是生产真正发送的东西。
- **结论（供拍板参考，本轮不改）**：约束是「**prompt 体量 × provider 延迟 vs 分档预算**」，
  不是单看档位。同一 provider 在 847 tokens 下 30s 档有 6/6 余量，在 4.6k tokens
  （真实负载）下则骑在 30s 边界；客户端自身 read 超时是 90s，说明卡点是外层分档。
  两条路径：
  1. **提档**（30s → 45~60s）：消除边界抖动，代价是每次真实失败多等 15-30s；
  2. **瘦身 prompt**：**实测下几乎无「边角料」可裁**——90.4% 的 token 集中在
     `## 持仓分析` 段（2,992 tok），其余字段合计不足 10%；要真降 token 只能压缩
     逐标的因子正文，而那正是报告的立身之本（用真实因子值而非编造，见 round31 R95）。
     故「瘦身」不是免费选项，本质是**拿报告质量换延迟**。
  综上：**提档是低风险解，瘦身是有质量代价的解**；选哪条交由你拍板。

**L2-e2e 归类更正（2026-09-29，原「环境性 ::1 解析失败」判断有误）**

- 原记录：把 `patrol --full` 的 L2-e2e FAIL 归为「环境性：`NameResolutionError: Failed to
  resolve '::1'` + 8 次连接 STORM，known-env-issues §1.1」。**该归类经指纹实测被推翻**。
- 实测（同一台机、同一 shell）：

  | 检查 | 结果 |
  |---|---|
  | `socket.getaddrinfo('::1', 8000, AF_INET6)`，代理环境变量原样 | **5/5 解析成功** |
  | 同上，代理环境变量全部剥离 | **5/5 解析成功** |
  | 同上，代理环境变量恢复 | **5/5 解析成功** |
  | `NO_PROXY` / `no_proxy` 是否含 `::1` | **已含**（`localhost,127.0.0.1,::1`） |
  | 当前 `GET http://[::1]:8000/health` | `ConnectionError`（**NewConnectionError，连接被拒**） |
  | `netstat` 监听 8000 | **无任何 LISTENING 行** |

- **更正结论**：`::1` 的 OS 解析与 requests 的代理旁路**都正常**，因此不是 §1.1 的解析抖动；
  真实原因是**后端当时未在 8000 监听**（连接被拒）。e2e 日志里的
  `NameResolutionError` 是 requests 在重试/代理链路上抛出的**症状**，而非根因。
- **方法论教训（比结论更重要）**：把 `NameResolutionError` / 连接拒绝直接归档为
  「环境性」，跳过了「先 `netstat` 确认端口是否有人听」这一步——顺序反了。
  正确顺序：**先确认服务存活 → 再看解析 → 最后才谈环境抖动**。
  本轮若先做指纹测试，本可在第一次 e2e 失败时就定位到「后端没起」而非绕道环境归类。
- **对已完成验收的影响**：本轮所有实盘验收（§9.1 全表）均走**进程内 `TestClient`**，
  不经 8000 端口，因此该误判**不影响**任何已记录的 PASS 结论；受影响的只有
  「L2-e2e 属环境性」这一句归类文字。`verify_e2e.py` 的干净复测仍待后端在线时进行。

### 9.4 与「待交易时段复测」清单的对照

| 原清单项 | 本轮结论 |
|---|---|
| round57 #6 性能债（realtime / fh / llm-health） | ✅ 两项大幅改善，factor-health 仍超阈 |
| round58-market R06 实额/家数 | ⚠️ 源间歇不可达（行为正确，取数失败） |
| round58-market R08 hsgt 近 5 日 | ✅ 早已按「停更」口径落地（最后可得 2024-08-16），无「近 5 日」可取 |
| round58-market 端到端报告实值引用 | ✅ 报告真产出且 0 免责话术；板块/家数未引用系**源不可达**（非接线问题） |
| round58-portfolio R01 成长占比告警 | ✅ 口径正确：balanced 22.4% / aggressive 27.8% 均 ≤30% cap → 不告警（符合设计） |
| round58-portfolio R03 defense ≥2 | ✅ 实证 2 只（黄金+30年国债） |
| round58-portfolio R04/R05 `report_quality=full` | ⚠️ 直连路径达成；**异步任务路径**因 N1 预算档回落（待决策） |
| L2-e2e 环境性 FAIL | 本轮以进程内 TestClient 绕开 `::1` 解析问题完成上述实值验收；`verify_e2e.py` 本身仍待干净后端复测 |
