# 已知环境性问题速查表（known-env-issues）

> 目的：验证/诊断遇到下述症状时**直接按指纹归类继续**，不从零重新排查。
> 每条含：症状指纹 → 归类 → 处置动作。新症状经排查确认非回归后回填本表
> （AGENTS.md 开发陷阱章节有引用本表的处置纪律）。
> 创建：2026-08-23（round34 实施轮；此前 AGENTS.md 引用本文件但它从未被创建）。

## 1. 运行时 / 验证期

### 1.1 verify_e2e 中段「连接拒绝风暴」（待取证升级）

- **症状指纹**：全量 e2e 运行至 SSE 分析模块（symbol/sector-analysis stream）之后的
  异步任务段，`/health` 先出现读超时（挂死判定），随后大量端点转为 `WinError 10061`
  连接拒绝直至运行结束；**后端进程存活**、后台循环日志（news/sector 刷新）持续；
  **e2e 进程退出后自愈**（服务恢复接受连接）。本地 3/3 次在同一定位复现（2026-08-23）。
- **归类**：两层——①挂死超时层 = 设计管线在事件循环内 ~20s 连续同步计算阻塞并发
  （真实性能缺陷，修复方向：重计算段 run_sync 包裹，独立批次）；②拒绝风暴层 =
  疑似①的放大后果或 Windows ProactorEventLoop accept 停摆，机制未闭合。
- **处置**：归类继续（关键断言在风暴前已捕获即有效）；verify_e2e 挂死分支已带
  `_probe_dual_stack()` 双栈取证 + netstat 监听转储（r35 落地），复现时收集输出
  升级专项。非本轮代码引入（round34 §5 容器轮已记载同类 /health 超时谜题）。
- **2026-08-25 更新（B5 交付期实测，3/3 复现）**：①风暴起点进一步锚定——
  `POST /design-async → 202` 受理后 **180s 轮询未完成**，随后全部检查转 10061；
  核心链（/health、design_text 持久化、3 套方案、market_regime）在风暴前全 PASS。
  ②冻结深度可放大至分钟级：Zen 全程 503 日，后台 120s 周期探针日志同停
  （循环被占满而非 ~20s 短阻塞）。③修复方案已入档
  `docs/round36-B5-allocate-pipeline.md` §8（A 重计算 run_sync 下放 / B 循环滞后
  看门狗 / C e2e 风暴快速跳过），待「开始实施」。
- **2026-08-25 §8 实施后更新**：三层全部落地（见 round36 文档 §9）——py-spy
  采样抓到三个真凶并修复：①`_build_market_context` 循环上直呼同步
  `get_sector_stocks`（future.result() 阻塞 64-66s/板块，最大真凶）；②设计管线
  相关性/K 线兜底段；③每客户端重建 SSL 上下文。冻结 64-66s×N → 单次 9.6s、
  外部拒连 12 → 0。**残余**：单次 ~10s 内外信号分裂停滞（外部零拒连但内部
  调度滞后），特征与主机 commit charge 高位的调度饥饿一致 → 归 §1.6 环境债，
  扩页面文件后复测闭案。语义陷阱：`run_in_thread/safe_call` 为同步阻塞等待，
  async def 直呼即冻结循环（audit_async_blocking 不查此类）。
- **2026-08-26 取证升级（B7 e2e 补跑期，3/3 同型）+ 客户端侧两个新陷阱**：
  ①**getaddrinfo 顺序翻转**——本日午后 `localhost` 解析变为 v4-first（伴随代理客户端
  常驻；晨间 D3 会话仍 ::1-first），python requests 直连全部落 127.0.0.1 → 假性
  ConnectionRefused 风暴（§1.1 形态完全复刻但非循环冻结）；指纹鉴别三件套：
  netstat 显示 LISTENING + `curl --noproxy "*" http://[::1]:8000/health` 返回 200 +
  requests 报 refused ⇒ 客户端解析问题而非服务端。verify_e2e 已钉死
  `BASE/--host="[::1]"` 字面量（181c376），不再依赖解析顺序。②**代理客户端劫持**：
  Clash(7897) 下 urllib/requests 对 `[::1]` 字面量不走 NO_PROXY 旁路（IPv6 字面量
  匹配缺口）→ 全量 502 Bad Gateway（代理发的，非后端）；e2e 跑法：`NO_PROXY=*`。
  ③风暴本体的设计管线归因维持 §1.1/round36 §9 结论不变；今日 15 项 FAIL 全数
  归位既有条目（§1.3 数据集薄 ×4 / §1.4 冷缓存 gate ×1 / §1.5 no_data ×2 /
  设计管线风暴拒连 ×8），零前端/B7 相关（B7 纯前端批次，后端仅测试路径修复）。


### 1.2 LLM 提供方不可用（402 配额耗尽 / 400 / 节流刷屏）

- **症状指纹**：日志周期性 `[LLM] Provider ... failed` + `[llm_quota_gate] throttling`；
  策略检查 LLM 路径超时→规则兜底（is_fallback=True）；金丝雀测试 httpx 报错。
- **归类**：外部服务可用性（周末配额耗尽高发）。
- **处置**：金丝雀已改「提供方不可达→诚实 skip」（skip 可见非伪装通过）；
  R95 类正文一致性验证标注「待 LLM 恢复复测」。

### 1.3 周末 ETF 记录稀疏 / 成交额规模缺失

- **症状指纹**：e2e「ETF 记录数 ≥10 实际 1」「有成交额 0/1」「有基金规模 0/1」。
- **归类**：数据源周末中断（round33/34 O3 一贯观察）。
- **处置**：对应 e2e 项归环境性；交易日复测。

### 1.4 watchlist 冷缓存慢（周末 >6s gate）

- **症状指纹**：周末全量 e2e 中 watchlist 7s+（gate 6s），交易日盘中正常。
- **归类**：源降级慢路径（性能软门禁范畴）。
- **处置**：登记已知性能债；交易日盘中复测 ≤3s 正式口径。

### 1.5 etf_specific / sentiment census no_data 超标

- **症状指纹**：`etf_specific no_data ≤2 实际 5`（premium_discount/tracking_error/
  shares_change/industry_diversification）、`sentiment no_data ≤0 实际 1`（news_heat）。
- **归类**：T-A/S-A 数据源债 + 快照类因子前向积累（设计使然，非回归）。
- **处置**：等 T-A/S-A 实施与自然积累；census 门禁阈值随数据面演进再校准。

### 1.6 pre-commit 全量 pytest xdist worker 崩溃（页面文件不足）

- **症状指纹**：`pytest -n auto`（4 worker）全量中途 `INTERNALERROR RuntimeError:
  can't start new thread` 或 worker `OSError [WinError 1455] 页面文件太小`；
  崩溃前已过用例全部 PASS、无断言失败；重跑偶发复现（2026-08-25 B5 交付期）。
- **归类**：本机 commit charge 逼近上限（实测 ~51/59GB），4 worker 各自加载完整
  FastAPI app 的峰值内存超限——环境资源问题，非代码回归。
- **处置**：全量改 `python -m pytest -n 2` 执行后稳定全绿 → `tests_ok_marker.py
  --mark` 后 pre-commit 凭据有效自动跳过重复全量。根治需扩页面文件（系统设置，
  非仓库范畴）；若换机/扩页后 `-n auto` 稳定可删除本条。

## 2. 工具链陷阱（Windows）

| 陷阱 | 后果 | 正确姿势 |
|---|---|---|
| PowerShell `Set-Content` 编辑 `.githooks/*` | UTF8 BOM 破坏 shebang → commit 报 cannot spawn | `[IO.File]::WriteAllText($p,$t,[Text.UTF8Encoding]::new($false))` |
| PowerShell 直接 `git commit` | hook 为 sh 脚本无法 spawn | Git Bash：`& "<Git>\bin\bash.exe" -lc "cd /e/<repo> && git commit -F <msg>"` |
| `uvicorn --host ::` 于 Windows | v6only，127.0.0.1 不监听 | 保持默认；verify_e2e BASE=localhost 即可，勿改绑 127.0.0.1 实验 |
| SQLite `ALTER TABLE RENAME` | 索引名保留 → create_all 撞名崩溃 | rename 表前先 DROP 其全部索引 |
| `rg -rln` | `-r` 是 --replace，输出被字面替换 | 用 `rg -ln` |

## 3. 已知性能债登记（round34-B4 定位；2026-08-26 深夜归因 + 同日盘中 D3 定档）

> 口径：软门禁（AGENTS.md 性能验收节）；修复排期不阻塞功能交付。
> 两组读数：01:00 非交易窗（最坏路径归因用）+ 11:35 交易日盘中（D3 定档用，源健康：熔断全 closed、单标的 realtime 108ms）。

| 路径 | 盘中稳态 | 冷启首击 | 阈值 | D3 定档 |
|---|---|---|---|---|
| `GET /market/watchlist` | **29-71ms** ✅ | 12.4s（有界） | ≤3s | **稳态达标**。冷启尖峰=enrich 截断(8s, 含 US 组)+兜底预算(≤8s)，一次性部署成本且已有界（日志实证走 R29 兜底路径）；可选后续=startup 预热一次 enrich 把尖峰挪出用户首击 |
| `POST /portfolio/calculate` | **17ms**（PRICE_MAP_CACHE 命中）✅ | 5.9/8.1s | 登记制 | 稳态达标。冷构建=pricing.py 两波 gather 结构性一次性成本（pricing.py:121/:148）；预热建议同上 |
| `GET /market/search` | 1.8-2.4s ⚠️ | 16.1s（instruments 冷同步） | ≤1s | **稳态仍超 ~2 倍**——新增小债：热缓存后 search 聚合链路待分段画像排期 |

- 归因存档（深夜窗）：watchlist 兜底段原无总预算（Semaphore(3)×每项 3s→ceil(N/3)×3s），已由 `_watchlist_close_fallback(budget_s=8.0)` 修复（共享截止线+超线项落「维护中」诚实行，测试 ×2）。
- 复测工具：交易日盘中 `python scripts/verify_perf.py`（watchlist 半边，自带阈值判定）；calculate 段用 §3 文档命令两轮取均值。非交易窗读数仅作最坏路径归因，不作验收。

## 回填纪律

- 新条目必须附出处（round 文档 §节 或 commit hash）与「确认非回归」的证据命令。
- 问题闭环（根因修复上线）后条目移入表尾「已闭环」区，保留指纹供回归对照。
