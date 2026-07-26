# 数据源统一改造方案

> 创建日期: 2026-07-22 | 版本: v3.0 | 上次更新: 2026-07-26
> **合并替代**：此文档合并了以下三份方案的代码改动部分，消除重叠与冲突：
> 1. `source-registry-optimization-plan.md` — China market 接入 SourceRegistry
> 2. `data-source-monitoring-plan.md` — 数据源可观测性
> 3. `market-awareness-and-data-source-plan.md` §4 — 美股数据源替换 (yfinance → Stooq)
>
> **v3.0 状态总览**：除 Phase D7（前端监控面板）外，所有 Phase (A→D6) **均已实施**。
> 本文档已从"实施计划"转换为"实施回顾 + 剩余任务指引"。
>
> **v2.0→v3.0 更新说明**：2026-07-26 全量代码审计发现 v2.0 中的实施方案绝大部分已被后续 commits 落地。
> 修正：Phase A（Stooq 已下线→实际为 TwelveData→Finnhub）、
> Phase B（3 函数已全部接入 registry.route() + _filtered price=0 过滤）、
> Phase C（probes.py 已创建含 8 探针）、
> Phase D（D1-D6 已实施，仅 D7 前端页面待完成）。
> 删除了对已不存在文件（stooq_fetcher.py）的引用。
>
> 涉及代码审计文件（2026-07-26）:
>   - `backend/app/fetchers/china_market.py` (961 行，3 函数已使用 registry.route + _filtered)
>   - `backend/app/services/source_registry.py` (192 行，已含 route_name 参数 + on_event 回调 + get_states + circuit_breaker_status)
>   - ~~`backend/app/fetchers/stooq_fetcher.py`~~ **文件已删除**（Stooq CSV API 已关闭返回 404/Cloudflare）
>   - `backend/app/services/source_health.py` (已有 register_probe + run_probes + health_loop 机制)
>   - `backend/app/services/market_service.py` (982 行，`_route_us()` 使用 `TwelveData→Finnhub`，已移除 Stooq/AlphaVantage/yfinance)
>   - `backend/app/main.py` (253 行，已调用 register_all_probes + 挂载 SourceEventStore 回调)
>   - `backend/app/monitor/probes.py` (存在，注册 8 个探针：6 数据源 + 2 线程池) ✅ 新建完成
>   - `backend/app/monitor/source_events.py` (存在，完整 SourceEventStore 实现) ✅ 新建完成
>   - `backend/app/routers/admin.py` (存在，4 个 sources API 端点已实现)

---

## 背景

这三份方案各自覆盖了数据源的不同方面，但在 `SourceRegistry`、`china_market.py` 降级链、美股路由等方面多处重叠。合并为统一方案后，可对外按序实施、避免冲突。

统一方案覆盖三大目标：

1. **提升国内数据路径韧性** — mootdx/Sina/QQ 等核心降级链接入熔断器
2. **替换不稳定数据源** — yfinance → 多源熔断链（TwelveData→Finnhub，境内直连稳定）
3. **建立可观测性** — 全链路事件记录 + 健康探针（复用 `monitor/token_usage.py` 的模式）

---

## 代码审计结果摘要（2026-07-26 更新）

### 已就绪的基础设施

| 组件 | 位置 | 当前状态 |
|------|------|---------|
| `SourceRegistry.route()` | `services/source_registry.py:106` | ✅ 存在，已含 `route_name` 参数 + 硬失败支持 |
| `SourceHealth` 熔断器 | `services/source_registry.py:15` | ✅ 存在，已含 `on_event` 回调 + `record_hard_failure` |
| 健康探针系统 | `services/source_health.py` | ✅ 存在，`register_probe()` + `run_probes()` + `health_loop()` 完整 |
| 已注册探针 | `monitor/probes.py` (via main.py:39) | ✅ 8 个（mootdx, sina, tencent, akshare, levistock, dongfang, threadpool_main, threadpool_akshare） |
| `Stooq` 相关 | — | ❌ **已移除**（CSV API 关闭返回 404/Cloudflare，文件已删除） |
| 监控模块 | `monitor/token_usage.py` | ✅ 有 `TokenUsageStore` 模式可复用 |
| 美股 `_route_us()` | `market_service.py:762` | ✅ 当前为 `TwelveData→Finnhub`（已移除 Stooq/AlphaVantage/yfinance） |
| China market 降级链 | `china_market.py:444-518` | ✅ 3 函数（A股实时/批量/港股）均已使用 `registry.route()` |
| price=0 过滤 | `china_market.py:424-439` | ✅ `_filtered()` 辅助函数在 provider lambda 层过滤 |
| SourceEventStore | `monitor/source_events.py` | ✅ 存在，内存环(5000条) + SQLite 异步刷盘 + 7天滚动清理 |
| 数据源监控 API | `routers/admin.py` | ✅ 4 个端点（health/timeline/failures/circuit-breakers） |
| 前端监控面板 | 待新建 | ❌ **唯一未完成项**（D7） |

### 需改造的关键缺口

| 缺口 | 涉及文件 | 严重度 | 状态 |
|------|---------|--------|:----:|
| China market 降级链硬编码未走 SR | `china_market.py` | P0 | ✅ 已实施 |
| price=0 检查在顶层函数而非 route 中 | `china_market.py:371,381` | P1 | ✅ 已实施（_filtered） |
| 仅 2 个探针，缺少 mootdx/sina/tencent/akshare/levistock | `main.py` | P1 | ✅ 已实施（8 探针） |
| 无 SourceEventStore，无数据源监控 API | 需新建 | P2 | ✅ D1-D6 已实施 |
| 无前端数据源监控面板 | 需新建 | P2 | ❌ **D7 待实施** |
| 非交易时段 price=0 会被误判为失败 | `china_market.py` 全部 fetcher | P2 | ⚠️ 需特别注意（_filtered 已缓解但非交易时段仍可能误判） |

---

## 架构概览（当前状态 2026-07-26）

```
┌─ 业务路径 (route_name) ────────────────────────┐
│ A_stock_realtime / HK_stock_realtime / US_ETF   │
│ A_stock_batch / probe / sector                  │
└─────────────────────────────────────────────────┘
         │ 路由（统一走 SourceRegistry.route()）
         ▼
┌─ SourceRegistry (熔断器) ───────────────────────┐
│  route(providers, route_name="...")              │
│     ├─ 冷却判断 → 跳过失败源                     │
│     ├─ 调用 → 计时 → result 有效性判断           │
│     └─ on_event 回调 → SourceEventStore.record() │
└──────────────────────────────────────────────────┘
         │ 降级链（按优先级）
         ▼
┌─ 数据源 ────────────────────────────────────────┐
│ A股实时:  mootdx → Sina                          │
│ A股批量:  mootdx → Tencent(QQ) → Sina           │
│ 港股实时:  Sina → Tencent(QQ) → 东方财富         │
│ 美股实时:  TwelveData → Finnhub                  │  ← v3: 移除 Stooq/Alphavantage/yfinance
│ 全球指数:  Sina → TwelveData → Finnhub           │  ← v3: 移除 Stooq
│ 行业板块:  levistock → akshare                   │
└──────────────────────────────────────────────────┘
         │ 探针 (每 120s, 8 个)
         ▼
┌─ 可观测性 ──────────────────────────────────────┐
│ SourceEventStore (复用 monitor/token_usage 模式) │
│  ├─ 内存环 (5000条) → 异步刷盘 data/source.db   │  ✅
│  ├─ 4 个 REST API → admin 路由                  │  ✅
│  └─ 前端监控面板（风格对齐 TokenMonitor）        │  ❌ D7 待实施
└──────────────────────────────────────────────────┘
```

**与 v2.0 的关键差异**:
- A 股/港股降级链：**已全部通过 registry.route() 管理熔断** ✅
- 美股实时：**移除 Stooq**（API 已关）、**移除 AlphaVantage**（25次/天限额）、**移除 yfinance**（境内不稳定）
- 当前美股链路仅为 `TwelveData → Finnhub`
- 已注册探针：**2 个 → 8 个** ✅
- SourceEventStore：**已完成** ✅

---

## 实施回顾与剩余任务

### Phase A — 美股路由重写（取代 yfinance）✅ **已实施**

**来源**: `market-awareness-and-data-source-plan.md` §4.1~4.5

**目标**: 美股实时/批量/历史数据从 yfinance 主力切换为境内直连链路

**实现情况**:
- `_route_us()` (market_service.py:762) 改为 `TwelveData → Finnhub` 双层链路
- Stooq CSV API 已关闭（404/Cloudflare），`stooq_fetcher.py` 已删除
- AlphaVantage 因 25次/天免费额度太低移出链路
- yfinance 因境内不稳定移出链路
- `_route_us()` 是 async 函数，已使用 `registry.route()` 管理熔断 + route_name + event recording

**关键 commit/改动**:
- 实际改动与 v2.0 计划有偏差：原本计划引入 Stooq 做主力，但 Stooq API 已死；实际改为精简链
- `_route_us()` docstring 注释已更新：v3 说明移除原因

**全球指数链路对齐**（2026-07-26，4.1.2）:
- `_foreign()` 降级链：EM缓存 → 港股缓存 → Sina → Sina页面 → Finnhub → 占位符
- `_route_us()` 降级链：TwelveData → Finnhub（通过 `registry.route()`）
- 全球指数与美股 ETF 共用 Finnhub 作为最终兜底源，但 `_foreign()` 不经过 `registry.route()`（前两级是内存缓存，不适合熔断路由模式）
- 对齐确认：`get_global_indices()` docstring 已更新（yfinance→Finnhub），verify_e2e.py 新增 US 三大指数（SPX/IXIC/DJI）覆盖断言 + 价格非空检查
- 结论：两条链路目标不同（批量面板 vs 单只精确），当前状态已满足需求，无需统一为同一路由机制

**验证** (当前):
```bash
# 美股实时
curl -s "http://localhost:8000/api/v1/market/realtime/US?symbol=SPY" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# verify_e2e.py 全 PASS
cd backend && python scripts/verify_e2e.py
```

---

### Phase B — China market 接入 SourceRegistry ✅ **已实施**

**来源**: `source-registry-optimization-plan.md` §P0-A

**目标**: `fetch_a_stock_realtime` / `fetch_a_stock_batch` / `fetch_hk_stock_realtime` 三函数从手写 if-else 切换为 SourceRegistry.route()

**实现情况**:

| 函数 | 行 | 降级链 | 已使用 route() | price=0 过滤 |
|------|---|--------|:--------------:|:-------------:|
| `fetch_a_stock_realtime` | china_market.py:444 | mootdx → Sina | ✅ | ✅ (_filtered) |
| `fetch_a_stock_batch` | china_market.py:454 | mootdx → Tencent → Sina | ✅ | ✅ (_filtered) |
| `fetch_hk_stock_realtime` | china_market.py:510 | Sina → Tencent → 东方财富 | ✅ | ✅ (_filtered) |

**关键技术决策**:
- `_filtered(provider_fn, *args)` 包装函数在 china_market.py:424 实现——在 provider lambda 层做 price=0 过滤，
  不修改底层 `_mootdx_realtime`/`_sina_realtime`/`_tencent_realtime` 函数的返回值契约。
- `registry.route()` 的 `route_name` 参数传递业务路径名，配合 SourceEventStore 事件追踪。

**注意**: 非交易时段 price=0 会被 `_filtered` 过滤导致 route() 尝试下一源。
当前策略是先试完所有源，全部 price=0 时返回 `[]`。交易时段行为正确。

**验证** (当前):
```bash
# A 股实时 — 正常返回
curl -s "http://localhost:8000/api/v1/market/realtime/A?symbol=000001" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# 港股实时 — 正常返回
curl -s "http://localhost:8000/api/v1/market/realtime/HK?symbol=00700" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# verify_e2e.py 全 PASS
cd backend && python scripts/verify_e2e.py
```

---

### Phase C — 健康探针补全 ✅ **已实施**

**来源**: `source-registry-optimization-plan.md` §P0-B + `data-source-monitoring-plan.md` §5.3

**目标**: 补齐所有核心数据源的主动健康探测，覆盖 6 个数据源 + 2 个线程池

**实现情况**:
- 新建 `backend/app/monitor/probes.py` — 集中管理全部探针
- `main.py` 在 lifespan 中调用 `register_all_probes()`（不含内联注册）
- 探针名与 `SourceRegistry` 中的源名一致（熔断状态共享）
- 探针运行间隔 120s（health_loop）

| 步骤 | 探针 | 源名 | 探测函数 | 超时 | 说明 |
|------|------|------|---------|:----:|------|
| C1 | mootdx | `mootdx` | `_mootdx_realtime(["510050"])` | 8s | 50ETF，轻量单代码查询 |
| C2 | sina | `sina` | `_sina_realtime(["510050"], "A")` | 10s | 直调 Sina 下层 |
| C3 | tencent | `tencent` | `_tencent_realtime(["510050"], "A")` | 10s | 直调 QQ 下层 |
| C4 | akshare | `akshare` | `ak.stock_zh_a_hist("510050", "daily")` | 15s | 历史日线非全量，`import akshare` 在 lambda 内惰性加载 |
| C5 | levistock | `levistock` | `lv.sector_em("industry")` | 10s | 行业板块 |
| C6 | 东方财富 | `dongfang` | `_em_hk_realtime(["00700"])` | 8s | 港股兜底源 |
| T1 | 主线程池 | `threadpool_main` | `get_thread_pool_stats()` | 1s | 活跃线程≤80%视为健康 |
| T2 | akshare 线程池 | `threadpool_akshare` | `get_akshare_pool_stats()` | 1s | 同上 |

**验证**:
```bash
# 启动后等 120s，查看日志
# 日志应包含: "[health] Running probes..." "[health] probe results: mootdx=OK, sina=OK, ..."
```

---

### Phase D — SourceEventStore 事件记录（D1-D6 ✅ 已实施, D7 ❌ 待实施）

**来源**: `data-source-monitoring-plan.md` §5.1~5.2

**目标**: 全链路数据源事件记录 + API 暴露 + 前端面板

#### D1-D6 实现情况

| 步骤 | 文件 | 改动 | 状态 |
|------|------|------|:----:|
| D1 | `backend/app/monitor/source_events.py` | **新建** SourceEventStore 类（内存环 5000 条 → 异步批量刷盘 SQLite `data/source.db`，7天滚动清理） | ✅ 已实现 |
| D2 | `backend/app/services/source_registry.py` | `SourceHealth.__init__` 已含 `on_event` 回调参数；`record_success/record_failure` 已调用 `self._on_event`；新增 `record_hard_failure` | ✅ 已实现 |
| D3 | 同上 | `SourceRegistry.set_event_callback(cb)` 已实现，含 `_make_source_callback` 包装 | ✅ 已实现 |
| D4 | `source_registry.py` | `route()` 已含 `route_name` 参数，成功/失败时传 route_name 给回调；`_route_us()` 传 `route_name="US_ETF"`；3 个 china_market 函数传各自 route_name | ✅ 已实现 |
| D5 | `backend/app/main.py` | lifespan 中调用 `registry.set_event_callback(_make_event_callback())`，`asyncio.run_coroutine_threadsafe` 写入 | ✅ 已实现 |
| D6 | `backend/app/routers/admin.py` | 4 个 API 已实现：`GET /sources/health` / `/sources/events/timeline` / `/sources/events/failures` / `/sources/circuit-breakers` | ✅ 已实现 |
| D7 | 前端 | **新增数据源健康监控页面**（与 TokenMonitor 风格对齐，ECharts 趋势图 + 源状态表格） | ❌ **待实施** |

**数据模型** (SQLite: `data/source.db`):

```sql
CREATE TABLE IF NOT EXISTS source_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL,       -- 'mootdx' / 'sina' / 'twelvedata' / ...
    route       TEXT    NOT NULL DEFAULT '',  -- 'A_stock_realtime' / 'US_ETF' / 'probe' / ...
    operation   TEXT    NOT NULL DEFAULT 'realtime',  -- 'realtime' / 'history' / 'probe'
    target      TEXT    NOT NULL DEFAULT '',  -- '000001' / 'SPY' / ...
    success     INTEGER NOT NULL,       -- 1=成功 0=失败
    duration_ms REAL    NOT NULL DEFAULT 0,
    error_message TEXT  NOT NULL DEFAULT '',
    timestamp   REAL    NOT NULL        -- Unix timestamp
);
```

**滚动清理**: 每日检查一次，`DELETE FROM source_events WHERE timestamp < unixepoch('now', '-7 days')`

#### ✅ D1-D6 验证 (当前):

```bash
# 1. 源健康概览（应返回所有注册源的状态）
curl -s "http://localhost:8000/api/v1/admin/sources/health" | python -c "import sys,json; d=json.load(sys.stdin); assert len(d)>2, 'too few sources'; [print(f'{s[\"name\"]}: {\"✅\" if s[\"available\"] else \"❌\"}') for s in d]"

# 2. 事件时间线
curl -s "http://localhost:8000/api/v1/admin/sources/events/timeline?hours=1" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} buckets')"

# 3. 最近失败
curl -s "http://localhost:8000/api/v1/admin/sources/events/failures?limit=10" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} failures')"

# 4. 熔断状态
curl -s "http://localhost:8000/api/v1/admin/sources/circuit-breakers" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: {len(d)} sources')"
```

#### ❌ D7 实施指引

**目标**: 新增前端数据源健康监控页面，与现有 TokenMonitor 风格对齐

**推荐参考**:
- 前端 `TokenMonitor.vue` 的布局（ECharts + 表格）
- API 端点：
  - `GET /api/v1/admin/sources/health` → 源状态表格
  - `GET /api/v1/admin/sources/events/timeline?hours=1` → ECharts 趋势图（成功/失败双线）
  - `GET /api/v1/admin/sources/events/failures?limit=10` → 失败列表
- `frontend/src/router/index.js` 新增路由 `/admin/sources`
- `frontend/src/App.vue` `navItems` 新增入口

**参考实现步骤**:
1. 新建 `frontend/src/views/SourceMonitor.vue`（参考 `TokenMonitor.vue` 布局 + Pinia store）
2. 新建 `frontend/src/stores/sources.js`（参考 `stores/token.js` 模式）
3. 注册路由：`router/index.js` 添加 `/admin/sources` → `SourceMonitor`
4. App.vue 导航栏添加"数据源"入口
5. 验证：各 API 调用正常，ECharts 折线图显示成功/失败趋势

---

## 依赖关系与推荐顺序

```
Phase A (美股路由)    ✅ 已实施
    │
Phase B (China SR)   ✅ 已实施
    │
Phase C (探针)        ✅ 已实施
    │
Phase D (EventStore)  ─── D1-D6 ✅ 已实施 | D7 ❌ 待实施（独立，无文件冲突）
```
---

## 验证标准（汇总）

| 阶段 | 验证方式 | 通过条件 | 失败应对 |
|------|---------|---------|---------|
| A | curl 命令自动化断言 | 美股实时含 price>0 | 检查 TwelveData/Finnhub API key |
| B | curl + verify_e2e.py | A 股/港股实时有数据，e2e 全 PASS | 确认降级链正常工作 |
| C | 启动日志 | 8 个探针均返回 OK | 逐个调试探针函数；超时过长者增加 timeout |
| D1-D6 | 4 个 curl 命令 | 全部返回 200 + 有效 JSON，source_events 表有数据 | 检查 DB 文件权限；检查回调注册顺序 |
| D7 | 前端浏览 | 数据源健康页展示正确 | 检查 API 返回格式与前端期望一致 |

---

## 剩余工作（按优先级排序）

| # | 任务 | 源阶段 | 预估 | 前置依赖 |
|---|------|--------|:----:|---------|
| 1 | D7: 前端数据源监控面板 | Phase D7 | 4h | D6 (已就绪) |

## 参考

- 原始方案 `source-registry-optimization-plan.md` — 已归档，内容已合并入本文档
- 原始方案 `data-source-monitoring-plan.md` — 已归档，内容已合并入本文档
- 原始方案 `market-awareness-and-data-source-plan.md` — §4 已合并，§5 市场感知联动待 market-analysis 方案实施后评估
- 全局指数链路决议: `docs/implementation-master-plan.md` §3.2
- 代码审计日期: 2026-07-26
- 合并决议: `docs/implementation-master-plan.md` §3.1
