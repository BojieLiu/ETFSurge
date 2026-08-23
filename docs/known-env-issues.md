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

## 2. 工具链陷阱（Windows）

| 陷阱 | 后果 | 正确姿势 |
|---|---|---|
| PowerShell `Set-Content` 编辑 `.githooks/*` | UTF8 BOM 破坏 shebang → commit 报 cannot spawn | `[IO.File]::WriteAllText($p,$t,[Text.UTF8Encoding]::new($false))` |
| PowerShell 直接 `git commit` | hook 为 sh 脚本无法 spawn | Git Bash：`& "<Git>\bin\bash.exe" -lc "cd /e/<repo> && git commit -F <msg>"` |
| `uvicorn --host ::` 于 Windows | v6only，127.0.0.1 不监听 | 保持默认；verify_e2e BASE=localhost 即可，勿改绑 127.0.0.1 实验 |
| SQLite `ALTER TABLE RENAME` | 索引名保留 → create_all 撞名崩溃 | rename 表前先 DROP 其全部索引 |
| `rg -rln` | `-r` 是 --replace，输出被字面替换 | 用 `rg -ln` |

## 回填纪律

- 新条目必须附出处（round 文档 §节 或 commit hash）与「确认非回归」的证据命令。
- 问题闭环（根因修复上线）后条目移入表尾「已闭环」区，保留指纹供回归对照。
