# 数据源统一改造方案

> 创建日期: 2026-07-22 | 版本: v2.0（经 3 轮 review 修订）
> **合并替代**：此文档合并了以下三份方案的代码改动部分，消除重叠与冲突：
> 1. `source-registry-optimization-plan.md` — China market 接入 SourceRegistry
> 2. `data-source-monitoring-plan.md` — 数据源可观测性
> 3. `market-awareness-and-data-source-plan.md` §4 — 美股数据源替换 (yfinance → Stooq)
>
> **v2.0 修订说明**：根据 `docs/implementation-master-plan.md` §3.1 决议 + 实际代码审计重写。
> 修复了 v1.0 中的 14 个问题：Phase A 现有函数未正确引用、price=0 过滤层级错误、
> 探针函数名未验证、缺少非交易时段考量、缺少 API key 依赖标注、验证标准过于模糊等。
>
> 涉及代码审计文件:
>   - `backend/app/fetchers/china_market.py` (802 行)
>   - `backend/app/fetchers/stooq_fetcher.py` (182 行，已有 fetch_us_etf_realtime / fetch_us_batch / fetch_stooq_history)
>   - `backend/app/services/source_registry.py` (99 行，当前 route() 无 route_name 参数、无 event callback)
>   - `backend/app/services/source_health.py` (已有注册探针 + health_loop 机制)
>   - `backend/app/services/market_service.py` (763 行，`_route_us()` 使用 `TwelveData→Finnhub→AlphaVantage→yfinance`)
>   - `backend/app/main.py` (已有 2 个探针注册)
>   - `backend/app/monitor/` (已有 token_usage.py，可复用其模式)

---

## 背景

这三份方案各自覆盖了数据源的不同方面，但在 `SourceRegistry`、`china_market.py` 降级链、美股路由等方面多处重叠。合并为统一方案后，可对外按序实施、避免冲突。

统一方案覆盖三大目标：

1. **提升国内数据路径韧性** — mootdx/Sina/QQ 等核心降级链接入熔断器
2. **替换不稳定数据源** — yfinance → Stooq 主力（Stooq 已有封装，境内直连稳定）
3. **建立可观测性** — 全链路事件记录 + 健康探针（复用 `monitor/token_usage.py` 的模式）

---

## 代码审计结果摘要

### 已就绪的基础设施

| 组件 | 位置 | 状态 |
|------|------|------|
| `SourceRegistry.route()` | `services/source_registry.py:42` | ✅ 存在，无 route_name 参数 |
| `SourceHealth` 熔断器 | `services/source_registry.py:13` | ✅ 存在，无 event callback |
| 健康探针系统 | `services/source_health.py` | ✅ 存在，`register_probe()` + `health_loop()` 完整 |
| 已注册探针 | `main.py:34-42` | ⚠️ 仅 2 个（twelvedata, finnhub） |
| `Stooq` 美股/ETF 实时 | `stooq_fetcher.py:16` | ✅ `fetch_us_etf_realtime()` |
| `Stooq` 批量实时 | `stooq_fetcher.py:50` | ✅ `fetch_us_batch()` |
| `Stooq` 历史 K 线 | `stooq_fetcher.py:147` | ✅ `fetch_stooq_history(symbol, period)` |
| `Stooq` 全球指数 | `stooq_fetcher.py:102` | ✅ `fetch_global_index_realtime()`，已在 `_foreign()` 中使用 |
| 监控模块 | `monitor/token_usage.py` | ✅ 有 `TokenUsageStore` 模式可复用 |
| 美股 `_route_us()` | `market_service.py:569` | ✅ 当前为 `TwelveData→Finnhub→AlphaVantage→yfinance` |

### 需改造的关键缺口

| 缺口 | 涉及文件 | 严重度 |
|------|---------|--------|
| China market 降级链硬编码（mootdx→Sina）未走 SR | `china_market.py` | P0 |
| price=0 检查在顶层函数而非 route 中 | `china_market.py:371,381` | P1（Phase B 前置条件） |
| 仅 2 个探针，缺少 mootdx/sina/tencent/akshare/levistock | `main.py` | P1 |
| 无 SourceEventStore，无数据源监控 API | 需新建 | P2 |
| 非交易时段 price=0 会被误判为失败 | `china_market.py` 全部 fetcher | P2 |

---

## 架构概览（目标状态）

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
│ 美股实时:  Stooq → TwelveData → Finnhub         │
│ 全球指数:  Sina → TwelveData → Finnhub → Stooq  │
│ 行业板块:  levistock → akshare                   │
└──────────────────────────────────────────────────┘
         │ 探针 (每 120s)
         ▼
┌─ 可观测性 ──────────────────────────────────────┐
│ SourceEventStore (复用 monitor/token_usage 模式) │
│  ├─ 内存环 (5000条) → 异步刷盘 data/source.db   │
│  ├─ 4 个 REST API → admin 路由                  │
│  └─ 前端监控面板（风格对齐 TokenMonitor）        │
└──────────────────────────────────────────────────┘
```

**关键区别 v1 到 v2**:
- A 股批量链路明确了 `mootdx → Tencent(QQ) → Sina`（与当前代码一致）
- 全球指数链路明确了 4 层：`Sina → TwelveData → Finnhub → Stooq`
- 美股实时用 `Stooq` 替代 `yfinance` 为首选

---

## 实施路线

### Phase A — 美股路由重写（取代 yfinance）

**来源**: `market-awareness-and-data-source-plan.md` §4.1~4.5

**目标**: 美股实时/批量/历史数据从 yfinance 主力切换为 Stooq 主力

**前置知识**: `_route_us()` (market_service.py:569) 是 async 函数，已使用 `registry.route()`。
当前链路为 `TwelveData(8s) → Finnhub(8s) → AlphaVantage(8s) → yfinance(8s)`。
Stooq 的 `fetch_us_etf_realtime()` (stooq_fetcher.py:16) 和 `fetch_us_batch()` (stooq_fetcher.py:50)
已在系统中存在，仅未纳入此链路。

| 步骤 | 文件 | 改动 | 预估行数 |
|------|------|------|---------|
| A1 | `market_service.py` | **修改 `_route_us()`** 链路为 `Stooq → TwelveData → Finnhub`，移除 AlphaVantage（25次/天额度太低）和 yfinance；在 lambda 中调用 `stooq_fetcher.fetch_us_etf_realtime()` | ~15 |
| A2 | `market_service.py` | 新建 `get_us_batch(symbols)` 函数，通过 `registry.route()` 使用 Stooq 批量 `fetch_us_batch()` → TwelveData 逐个 fallback | ~15 |
| A3 | `market_service.py` | 新建 `get_us_history(symbol, period)` 函数，通过 `registry.route()` 使用 `stooq_fetcher.fetch_stooq_history()` → 现有 get_history fallback | ~12 |
| A4 | `market_service.py` | 修改 `_foreign()` (约 167 行) 链路为 `Sina(4s) → TwelveData(6s) → Finnhub(6s) → Stooq(8s) → placeholder`；对齐 `fix-global-indices-plan.md` 决议 | ~20 |
| A5 | `yfinance_fetcher.py` | 文件头添加 `[DEPRECATED]` 标记；`fetch_us_etf_realtime()` 入口加 `YFINANCE_PROXY` 环境变量检查 | ~5 |

**风险与缓解**:
- ⚠️ Stooq SSL 握手在非交易时段可能慢（原代码注释已注明）。**缓解**: 超时设置为 8s，不阻塞链路
- ⚠️ TwelveData/Finnhub 需要 API key，未配置时自动跳过（已有代码逻辑）。**缓解**: 确保降级链有 Stooq 兜底
- ⚠️ **非交易时段** Stooq 可能返回 last_price=0 或昨收价。**缓解**: A1 lambda 中做 `price > 0` 过滤

**验证（具体命令+预期）**:
```bash
# 美股实时 — 返回含 price 字段
curl -s "http://localhost:8000/api/v1/market/realtime/US?symbol=SPY" | python -c "import sys,json; d=json.load(sys.stdin); assert d.get('price',0)>0, 'no price'; print(f'OK: {d[\"symbol\"]} price={d[\"price\"]}')"

# 美股日线 — 返回 K 线列表
curl -s "http://localhost:8000/api/v1/market/history/US?symbol=SPY&period=daily" | python -c "import sys,json; d=json.load(sys.stdin); assert len(d)>0, 'empty history'; print(f'OK: {len(d)} bars')"

# 全球指数 — 美股区域有数据
curl -s "http://localhost:8000/api/v1/market/indices/global" | python -c "import sys,json; d=json.load(sys.stdin); assert 'US' in d, 'no US region'; assert any(i.get('price',0)>0 for i in d['US']), 'no prices'; print(f'OK: {len(d[\"US\"])} US indices')"
```

---

### Phase B — China market 接入 SourceRegistry

**来源**: `source-registry-optimization-plan.md` §P0-A

**目标**: 将 A 股/港股核心降级链接入 `SourceRegistry.route()` 熔断管理

**设计决策**:
- `registry.route()` 判断成功标准是 `if result:`（即非 None 非空列表视为成功）
- 当前 hand-coded 链使用 `if items and items[0].get("price")` — **route() 不会检查 price>0**
- **修复方案**: 不在低层函数加 price=0 过滤（会影响其他调用者），而是在 provider lambda 中处理

| 步骤 | 文件 | 改动 | 预估行数 |
|------|------|------|---------|
| B1 | `china_market.py` | `fetch_a_stock_realtime()` 改为 `registry.route([("mootdx", lambda: _filtered(_mootdx_realtime, [symbol])), ("sina", lambda: _filtered(_sina_realtime, [symbol], "A"))])`，其中 `_filtered()` 是新增的辅助函数，在顶层做 `price>0` 检查 | ~12 |
| B2 | `china_market.py` | `fetch_a_stock_batch()` 改为 `registry.route([("mootdx", ...), ("tencent", ...), ("sina", ...)])` | ~14 |
| B3 | `china_market.py` | `fetch_hk_stock_realtime()` 改为 `registry.route([("sina", ...), ("tencent", ...), ("dongfang", ...)])` | ~12 |
| B4 | `china_market.py` | 新增辅助函数 `_filtered(provider_fn, *args)` 调用 provider 后过滤 `all(i.get("price") for i in result)` | ~6 |
| B5 | `china_market.py` | 更新文件头注释为"降级链已接入 SourceRegistry 熔断路由管理" | 1 |

**注意**: B4 的 `_filtered` 辅助函数确保 `route()` 的 `if result` 语义正确——provider lambda 返回 `None` 或 `[]` 时 `route()` 会继续尝试下一个源。

> **为什么不改 `_mootdx_realtime`/`_sina_realtime`/`_tencent_realtime` 内部？**
> 这些低层函数被多处调用（包括需要 price=0 的场景），修改其返回值会破坏调用契约。
> 在 provider lambda 层过滤是最小侵入的修复方式。

**验证**:
```bash
# A 股实时 — 正常返回
curl -s "http://localhost:8000/api/v1/market/realtime/A?symbol=000001" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# 港股实时 — 正常返回
curl -s "http://localhost:8000/api/v1/market/realtime/HK?symbol=00700" | python -c "import sys,json; d=json.load(sys.stdin); print(f'OK: price={d.get(\"price\",0)}' if d.get('price',0)>0 else 'NO DATA')"

# verify_e2e.py 全 PASS
cd backend && python scripts/verify_e2e.py
```

---

### Phase C — 健康探针补全

**来源**: `source-registry-optimization-plan.md` §P0-B + `data-source-monitoring-plan.md` §5.3

**目标**: 补齐所有核心数据源的主动健康探测，覆盖 7 个数据源

**前置知识**:
- `source_health.py` 已有 `register_probe(name, fn, timeout)` + `health_loop(60s)` 机制
- `main.py:46` 有 `await _register_health_probes()` 在 lifespan 中被调用
- 新增探针名须与 `SourceRegistry` 中的源名一致（熔断状态共享）

**推荐实现方式**: 新建 `backend/app/monitor/probes.py` 集中管理全部探针，`main.py` 仅调用一行 `register_all_probes()`

| 步骤 | 新增探针 | 源名 | 探测函数 | 超时 | 说明 |
|------|---------|------|---------|------|------|
| C1 | mootdx | `mootdx` | `_mootdx_realtime(["510050"])` | 8s | 50ETF，轻量单代码查询 |
| C2 | sina | `sina` | `_sina_realtime(["510050"], "A")` | 10s | 同上，直调 Sina 下层 |
| C3 | tencent | `tencent` | `_tencent_realtime(["510050"], "A")` | 10s | 同上，直调 QQ 下层 |
| C4 | akshare | `akshare` | `_p = lambda: ak.stock_zh_a_hist("510050", "daily"); df = _p(); len(df) > 0` | 15s | akshare 最慢，用历史日线非全量扫描；注意 `import akshare` 在 lambda 内部惰性加载，避免启动开销 |
| C5 | levistock | `levistock` | `lv.sector_em("industry")` | 10s | 行业板块，确保板块全链路可用 |
| C6 | stooq | `stooq` | `stooq_fetcher.fetch_us_etf_realtime("SPY")` | 8s | 美股数据源主链路 |
| C7 | 东方财富 | `dongfang` | `_em_hk_realtime(["00700"])` | 8s | 港股兜底源 |

**文件改动**:
- 新建: `backend/app/monitor/probes.py`
- 修改: `main.py` — 将 2 行内联探针改为 `from .monitor.probes import register_all_probes; register_all_probes()`

**验证**:
```bash
# 启动后等 120s，查看日志
python -c "import time; time.sleep(125)"
# 日志应包含: "[health] Running 7 probes..." "[health] probe results: mootdx=OK, sina=OK, ..."
```

---

### Phase D — SourceEventStore 事件记录

**来源**: `data-source-monitoring-plan.md` §5.1~5.2

**目标**: 全链路数据源事件记录 + API 暴露 + 前端面板

**前置知识**:
- `monitor/token_usage.py` 已有 `TokenUsageStore`（内存环 + 异步刷盘模式），可直接复用架构
- `source_registry.py:99` 行 `registry` 全局单例，可加 `set_event_callback` 方法
- `routers/admin.py` 已有 3 个 token-usage API 端点（`/token-usage`、`/token-usage/timeseries`、`/token-usage/failures`）

**架构**: SourceEventStore 不直接侵入数据路径，通过 SourceRegistry 的 `on_event` 回调被动采集

| 步骤 | 文件 | 改动 | 预估行数 | 前置依赖 |
|------|------|------|---------|---------|
| D1 | `backend/app/monitor/source_events.py` | **新建** SourceEventStore 类（复用 `TokenUsageStore` 模式：内存环 5000 条 → 异步批量刷盘 SQLite `data/source.db`） | ~150 | 无 |
| D2 | `backend/app/services/source_registry.py` | `SourceHealth.__init__` 增加 `on_event` 回调参数；`record_success/record_failure` 调用 `self._on_event` | ~15 | 无 |
| D3 | 同上 | `SourceRegistry` 增加 `set_event_callback(cb)` 方法 | ~5 | D2 |
| D4 | `source_registry.py` + 现有调用者 | `route()` 增加 `route_name` 参数（`def route(self, providers, route_name="", ...)`），成功/失败时传 route_name 给回调；更新 2 处现有调用者：`_route_us()` 传 `route_name="US_ETF"`，`_try_two()` 传 `route_name=name_lv` | ~15 | D2 |
| D5 | `backend/app/main.py` | lifespan 中调用 `registry.set_event_callback(_make_event_callback())`，loop 中 `asyncio.run_coroutine_threadsafe` 写入 | ~15 | D3+D4 |
| D6 | `backend/app/routers/admin.py` | 新增 4 个 API：`GET /sources/health` / `/sources/events/timeline` / `/sources/events/failures` / `/sources/circuit-breakers` | ~80 | D1 |
| D7 | 前端 | 新增数据源健康监控页面（与 TokenMonitor 风格对齐，ECharts 趋势图 + 源状态表格） | ~150 | D6 |

**数据模型** (SQLite: `data/source.db`, 独立于 portfolio.db):

```sql
CREATE TABLE IF NOT EXISTS source_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL,       -- 'mootdx' / 'sina' / 'stooq' / ...
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

**验证**:
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

---

## 依赖关系与推荐顺序

```
Phase A (美股路由)    ─── 独立，无外部依赖
    │
Phase B (China SR)   ─── 独立，无外部依赖（与 A 可并行）
    │
    ├── 注意 A 和 B 会同时修改 source_registry.py 吗？
    │    不。A 只修改 route() 中 providers 列表的组成，
    │    B 在 china_market.py 中调用 route()。
    │    两者不修改 source_registry.py 本身，无文件冲突。
    │
Phase C (探针)        ─── 独立，无外部依赖（与 A/B 可并行）
    │
    └── 注意 C 的探针名须与 A/B 注册的源名一致，设计时需协调
        建议统一源名列表: mootdx, sina, tencent, akshare, levistock,
                         stooq, twelvedata, finnhub, dongfang
    │
Phase D (EventStore)  ─── 依赖 D2-D4 修改 SourceRegistry（唯一串行瓶颈）
    ├── D1 (DB/模型)         可独立于 D2-D4 开发
    ├── D2-D4 (SR 改造)      需要独占 source_registry.py
    ├── D5 (main.py 回调)    依赖 D2-D4
    ├── D6 (admin API)       依赖 D1
    └── D7 (前端)            依赖 D6
```

**推荐并行策略**:
- **Track 1**: A + B 并行（不同文件，互不冲突）
- **Track 2**: C 独立（仅修改 main.py + 新建 probes.py）
- **Track 3**: D1 + D6 + D7 可先做（DB + API + 前端，不依赖 SR），D2-D5 最后合并

---

## 验证标准（汇总）

| 阶段 | 验证方式 | 通过条件 | 失败应对 |
|------|---------|---------|---------|
| A | curl 命令自动化断言 | 美股实时含 price>0，日线 >0 条，全球指数 US 区域有数据 | 回退 `_route_us()` 到旧链路；检查 Stooq 连通性 |
| B | curl + verify_e2e.py | A 股/港股实时有数据，e2e 全 PASS | 恢复 hand-coded 降级链；确认 `_filtered` 辅助函数正确 |
| C | 启动日志 | `[health] probe results` 行含 7 个源，无异常 | 逐个调试探针函数；超时过长者增加 timeout |
| D | 4 个 curl 命令 | 全部返回 200 + 有效 JSON，source_events 表有数据 | 检查 DB 文件权限；检查回调注册顺序 |

---

## 参考

- 原始方案 `source-registry-optimization-plan.md` — Phase B 详细设计（含 §4.1 price=0 语义缺口、§4.2 探针协同、§4.3 锁超时分析）
- 原始方案 `data-source-monitoring-plan.md` — Phase D 详细设计（含 §5.1 SourceEventStore、§8 风险与考量、§9 数据量控制）
- 原始方案 `market-awareness-and-data-source-plan.md` — Phase A 详细设计（含 §4.6 akshare 统一降级策略、§4.5 yfinance deprecation）
- 全局指数链路决议: `docs/implementation-master-plan.md` §3.2
- 代码审计日期: 2026-07-22，覆盖 7 个核心文件
- 合并决议: `docs/implementation-master-plan.md` §3.1
