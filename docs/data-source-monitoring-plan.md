# 数据源可观测性方案

> 版本: v2.0 | 日期: 2026-07-21
> 状态: 设计文档（已审查，待实施）

---

## 目录

- [数据源可观测性方案](#数据源可观测性方案)
  - [目录](#目录)
  - [一、背景与目标](#一背景与目标)
  - [二、现状分析](#二现状分析)
    - [2.1 已有基础设施](#21-已有基础设施)
    - [2.2 当前缺口](#22-当前缺口)
  - [三、设计原则](#三设计原则)
  - [四、数据模型](#四数据模型)
    - [4.1 事件记录模型](#41-事件记录模型)
    - [4.2 探针状态模型](#42-探针状态模型)
  - [五、后端架构](#五后端架构)
    - [5.1 SourceEventStore](#51-sourceeventstore)
    - [5.2 SourceRegistry 增强](#52-sourceregistry-增强)
    - [5.3 探针系统改造](#53-探针系统改造)
    - [5.4 硬编码路径接入（decorator 方案）](#54-硬编码路径接入decorator-方案)
    - [5.5 所有数据源一览](#55-所有数据源一览)
  - [六、API 契约](#六api-契约)
    - [6.1 源健康概览](#61-源健康概览)
    - [6.2 源事件时间线](#62-源事件时间线)
    - [6.3 最近失败事件](#63-最近失败事件)
    - [6.4 当前熔断状态](#64-当前熔断状态)
  - [七、前端设计](#七前端设计)
    - [7.1 路由与导航](#71-路由与导航)
    - [7.2 页面布局](#72-页面布局)
  - [八、实施路线](#八实施路线)
    - [Phase 1 — 核心采集闭环](#phase-1--核心采集闭环)
    - [Phase 2 — 探针 + 前端展示](#phase-2--探针--前端展示)
    - [Phase 3 — 告警与增强](#phase-3--告警与增强)
  - [九、风险与考量](#九风险与考量)
    - [9.1 数据量控制](#91-数据量控制)
    - [9.2 性能影响](#92-性能影响)
    - [9.3 重启动数据保留](#93-重启动数据保留)
  - [十、检查清单](#十检查清单)

---

## 一、背景与目标

ETF Surge 依赖多个免费数据源（mootdx、Sina、Tencent QQ、akshare、yfinance、Twelve Data、Finnhub 等）获取行情、资讯、行业板块等数据。这些数据源各自有稳定性差异：某段时间 mootdx 可能连不上、新浪可能限流、akshare 可能超时。

**现状问题**：
- 当某个数据源持续失败时，降级链工作与否缺乏可见性
- 运维和调试时无法快速回答"当前哪个源是好的"
- 无法量化各源的长期稳定性，无法优化降级顺序

**目标**：建立数据源级别的可观测性，记录每一次访问事件（成功/失败/耗时），暴露 API 和 UI，使系统稳定性和数据源选优有数据支撑。

---

## 二、现状分析

### 2.1 已有基础设施

| 组件 | 文件 | 功能 |
|------|------|------|
| `SourceHealth` | `services/source_registry.py` | 每个源的熔断器：连续失败计数 + 冷却时间 |
| `SourceRegistry` | 同上 | 全局注册表，`route()` 按优先级尝试 providers，跳过冷却中的源 |
| `health_loop` | `services/source_health.py` | 定时执行探针，记录成败到 `SourceRegistry` |
| `register_probe` | 同上 | 注册探针函数 |

**目前使用 `SourceRegistry.route()` 的路径**：
- 美股实时（`_route_us`，market_service.py）：twelvedata → finnhub → alphavantage → yfinance
- 行业板块（`_try_two`，sector_fetcher.py）：levistock → akshare（含 industry / concept / sector stocks / sector history）

**目前注册的健康探针**（main.py）：
- `twelvedata` — 拉 SPY 实时，超时 8s
- `finnhub` — 拉 SPY 实时，超时 8s

### 2.2 当前缺口

**缺口 1 — 核心国内数据路径未接入 SourceRegistry**

`china_market.py` 中以下函数的降级链均为硬编码 if-else，不走 `registry.route()`：

| 函数 | 降级链 | 当前行为 |
|------|--------|---------|
| `fetch_a_stock_realtime` | mootdx → Sina | mootdx 连挂 10 次仍会先尝试 mootdx |
| `fetch_a_stock_batch` | mootdx → QQ → Sina | 同上 |
| `fetch_hk_stock_realtime` | Sina → QQ → EM | 同上 |
| `fetch_index_realtime` | mootdx → QQ | 同上 |

熔断器对这些路径完全无感知，也无法自动跳过不可用的源。

**缺口 2 — 健康探针覆盖严重不足**

实际系统的数据源远不止 2 个。mootdx、Sina、Tencent QQ、akshare、yfinance、Alpha Vantage、levistock、东方财富(EM)、tushare 等均未注册探针。

**缺口 3 — 无 API / UI 查询源健康状态**

当前 `SourceHealth` 只存在于进程内存，无任何 HTTP endpoint 暴露：
- 无法通过 REST 查询"现在哪个源在冷却"
- 前端无法展示源状态面板
- 外部监控（Prometheus / Grafana）无法接入

**缺口 4 — 无历史趋势数据**

`SourceHealth` 状态不持久化。重启后熔断器状态丢失，长期稳定性只能靠人脑记忆。

---

## 三、设计原则

1. **零冲击接入** —— 监控代码不可影响数据路径的正常执行（异步刷盘、不抛异常）
2. **复用已有模式** —— 沿用 `TokenUsageStore` 的模式（内存环 + SQLite + 异步批量刷盘）
3. **分覆盖面推进** —— 先跟 SourceRegistry 深度集成（自动覆盖美股 + 板块），再逐步覆盖硬编码路径
4. **可观测优先** —— 不追求完美告警，先把数据亮出来，后续优化有依据
5. **存储有界** —— 事件记录 7 天滚动清理，避免磁盘膨胀

---

## 四、数据模型

### 4.1 事件记录模型

每条记录对应一次数据源访问尝试（即使是降级链中失败的尝试也记录）：

| 字段 | 类型 | 必需 | 说明 | 示例 |
|------|------|------|------|------|
| `id` | INTEGER | ✅ | 自增主键 | 1 |
| `source_name` | TEXT | ✅ | 数据源名称，统一小写 | `"mootdx"` / `"sina"` / `"twelvedata"` |
| `route` | TEXT | ✅ | 业务路径，用于区分同源不同用途 | `"A_stock_realtime"` / `"US_ETF"` / `"sector"` / `"probe"` |
| `operation` | TEXT | ✅ | 操作类型 | `"realtime"` / `"history"` / `"probe"` |
| `target` | TEXT | - | 请求标的（若有） | `"000300"` / `"SPY"` / 空字符串 |
| `success` | INTEGER | ✅ | 1=成功，0=失败 | 1 |
| `duration_ms` | REAL | ✅ | 耗时（毫秒），含网络 I/O | 342.5 |
| `error_message` | TEXT | - | 失败时的异常消息，成功时为空字符串 | `"Connection timed out"` |
| `timestamp` | REAL | ✅ | Unix 时间戳 | 1710000000.0 |

**SQLite DDL**：

```sql
CREATE TABLE IF NOT EXISTS source_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT    NOT NULL,
    route       TEXT    NOT NULL DEFAULT '',
    operation   TEXT    NOT NULL DEFAULT 'realtime',
    target      TEXT    NOT NULL DEFAULT '',
    success     INTEGER NOT NULL,
    duration_ms REAL    NOT NULL DEFAULT 0,
    error_message TEXT  NOT NULL DEFAULT '',
    timestamp   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_se_source ON source_events(source_name);
CREATE INDEX IF NOT EXISTS idx_se_ts     ON source_events(timestamp);
```

### 4.2 探针状态模型

探针本身也是事件，`route` 固定为 `"probe"`。探针的状态等同于该源最近一次探针事件的 `success` 和 `duration_ms`。

---

## 五、后端架构

### 5.1 SourceEventStore

**文件**: `backend/app/monitor/source_events.py`

沿用 `TokenUsageStore` 的成熟模式，但增加一条线程安全写入路径（应对同步函数中的记录需求）：

```
SourceEventStore
├── _events: list[dict]      ← 内存环缓冲区（最多 5000 条）
├── _lock: asyncio.Lock      ← 异步写入时序安全
├── _flush_queue: Queue      ← 异步写入队列
├── _thread_queue: Queue     ← 同步函数写入队列（threading.Queue）
├── _flush_task: Task        ← 后台刷盘任务
└── SQLite: data/source_events.db
```

核心接口：

```python
import queue as _queue
import threading
import time

class SourceEventStore:
    async def record(self, source_name: str, route: str, operation: str,
                     success: bool, duration_ms: float,
                     target: str = "", error_message: str = "") -> None:
        """记录一次数据源访问事件（异步上下文调用，非阻塞）。"""

    def record_sync(self, source_name: str, route: str, operation: str,
                    success: bool, duration_ms: float,
                    target: str = "", error_message: str = "") -> None:
        """线程安全的同步记录方法，供非 async 上下文调用（如 china_market.py）。

        将事件入队到 _thread_queue，由 _flush_worker 跨线程消费。
        不会阻塞调用者，不会抛异常。
        """

    async def source_summary(self, hours: int = 24) -> list[dict]:
        """返回每个源在指定时间窗口内的汇总：
        - 总调用次数 / 失败次数 / 成功率
        - 平均耗时
        - 最后成功 / 最后失败时间戳
        - 当前是否在冷却中（从 SourceRegistry 读取）
        """

    async def timeline(self, source: str | None = None,
                       hours: int = 24, bucket: str = "hour") -> list[dict]:
        """返回时间序列，每个 bucket 内的成功/失败/平均耗时。"""

    async def recent_failures(self, source: str | None = None,
                              limit: int = 50) -> list[dict]:
        """返回最近失败事件。"""

    async def _drain_thread_queue(self) -> None:
        """将 _thread_queue 中的事件转移到 _flush_queue（每次 flush 前调用）。"""

    async def _flush_worker(self) -> None:
        """后台批量刷盘：每 100 条或 5 秒。
        每次循环先 _drain_thread_queue()，再 flush。
        """

    def _cleanup_old(self) -> None:
        """每次启动 + 写入时检查，删除 7 天前的数据。"""

    async def shutdown(self) -> None:
        """关闭时 flush 剩余数据（在 lifespan shutdown 中调用）。"""
```

**全局单例**：

```python
source_event_store = SourceEventStore()
```

### 5.2 SourceRegistry 增强

**文件**: `backend/app/services/source_registry.py`

改动点：

**a) SourceHealth 增加事件回调钩子**

```python
class SourceHealth:
    def __init__(self, cooldown=60.0, failure_threshold=3, name="",
                 on_event: Callable | None = None):
        self.name = name
        self._on_event = on_event  # 新增：回调 hook

    def record_success(self, duration_ms=0.0, route="", target=""):
        self._failures = 0
        self._cool_until = 0.0
        if self._on_event:
            self._on_event(self.name, route, True, duration_ms, target=target)

    def record_failure(self, now, duration_ms=0.0, route="",
                       error_message="", target=""):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._cool_until = now + self.cooldown
            self._failures = 0
        if self._on_event:
            self._on_event(self.name, route, False, duration_ms,
                           error_message=error_message, target=target)
```

**b) SourceRegistry 注册时注入事件回调**

```python
class SourceRegistry:
    def __init__(self):
        self._states: dict[str, SourceHealth] = {}
        self._on_event = None  # 外部通过 set_event_callback 设置

    def set_event_callback(self, cb: Callable):
        self._on_event = cb

    def _health(self, name: str) -> SourceHealth:
        if name not in self._states:
            self._states[name] = SourceHealth(name=name, on_event=self._on_event)
        return self._states[name]
```

**c) route() 记录耗时**

```python
    def route(self, providers: list, now: float | None = None,
              route_name: str = "") -> Any:
        """route_name 标识业务路径，如 'US_ETF' / 'sector_industry'。"""
        now = now or time.time()
        for name, fn in providers:
            h = self._health(name)
            if not h.available(now):
                continue
            t0 = time.monotonic()
            try:
                result = fn()
                elapsed = (time.monotonic() - t0) * 1000
                if result:
                    h.record_success(duration_ms=elapsed, route=route_name)
                    return result
                h.record_failure(now, duration_ms=elapsed, route=route_name)
            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                h.record_failure(now, duration_ms=elapsed, route=route_name,
                                 error_message=str(e))
        return None
```

**d) 接入位置：main.py lifespan**

回调可能在同步或异步上下文中触发（探针在 async 函数中运行，`route()` 本身无上下文要求），因此使用 `asyncio.run_coroutine_threadsafe` 确保在正确的事件循环中执行：

```python
from .monitor.source_events import source_event_store
from .services.source_registry import registry

def _make_event_callback():
    """创建 SourceRegistry 事件回调。在 lifespan 中调用，捕获 loop 引用。"""
    loop = asyncio.get_running_loop()
    def _cb(name, route, success, dur, **kw):
        asyncio.run_coroutine_threadsafe(
            source_event_store.record(
                source_name=name, route=route,
                operation="realtime",
                success=success, duration_ms=dur,
                **kw
            ),
            loop
        )
    return _cb

async def lifespan(app):
    # ... 其他初始化 ...
    registry.set_event_callback(_make_event_callback())
    # ... lifespan shutdown 中 ...
    # await source_event_store.shutdown()
```

**e) 更新现有 caller 传入 route_name**

现有 `registry.route()` 调用者需传入 `route_name` 以标识业务路径：

| 文件 | 位置 | 当前调用 | 改为 |
|------|------|---------|------|
| `market_service.py:588` | `_route_us` | `registry.route([...])` | `registry.route([...], route_name="US_ETF")` |
| `sector_fetcher.py:40` | `_try_two` | `registry.route([...])` | `registry.route([...], route_name=name_lv)` |

这样**所有走 `registry.route()` 的路径自动接入监控，调用点只需多传一个参数**。

### 5.3 探针系统改造

**文件**: `backend/app/monitor/probes.py`（新建）

将当前 `main.py` 中的探针注册逻辑抽离到独立文件，并补全所有核心数据源：

```python
"""数据源健康探针注册。所有数据源的主动健康探测在此集中管理。"""

from ..services.source_health import register_probe

def register_all_probes():
    # ── A 股数据源 ──
    from ..fetchers.china_market import fetch_a_stock_realtime

    def _probe_mootdx():
        return fetch_a_stock_realtime("510050")  # 50ETF
    register_probe("mootdx", _probe_mootdx, timeout=5)

    def _probe_sina():
        # 直接调用 Sina 层（绕过 mootdx 首选项）
        from ..fetchers.china_market import _sina_realtime
        return _sina_realtime(["510050"], "A")
    register_probe("sina", _probe_sina, timeout=5)

    def _probe_tencent():
        from ..fetchers.china_market import _tencent_realtime
        return _tencent_realtime(["510050"], "A")
    register_probe("tencent", _probe_tencent, timeout=5)

    # ── 全量数据源 ──
    # akshare_fetcher.py 是向后兼容 shim，直接引用 china_market
    from ..fetchers.china_market import fetch_a_stock_realtime as ak_fetch
    def _probe_akshare():
        return ak_fetch("510050")
    register_probe("akshare", _probe_akshare, timeout=10)

    # ── 美股数据源 ──
    from ..fetchers.twelvedata_fetcher import fetch_realtime as td_fetch
    def _probe_td():
        return td_fetch("SPY")
    register_probe("twelvedata", _probe_td, timeout=8)

    from ..fetchers.finnhub_fetcher import fetch_realtime as fh_fetch
    def _probe_fh():
        return fh_fetch("SPY")
    register_probe("finnhub", _probe_fh, timeout=8)

    from ..fetchers.alphavantage_fetcher import fetch_realtime as av_fetch
    def _probe_av():
        return av_fetch("SPY")
    register_probe("alphavantage", _probe_av, timeout=8)

    from ..fetchers.yfinance_fetcher import fetch_us_etf_realtime
    def _probe_yf():
        return fetch_us_etf_realtime("SPY")
    register_probe("yfinance", _probe_yf, timeout=8)

    # ── 行业板块 ──
    from ..fetchers.levistock_fetcher import fetch_sector_heat
    def _probe_lv():
        return fetch_sector_heat(limit=3)
    register_probe("levistock", _probe_lv, timeout=8)

    # ── 港股 ──
    from ..fetchers.china_market import _em_hk_realtime
    def _probe_em_hk():
        return _em_hk_realtime(["00700"])
    register_probe("dongfang", _probe_em_hk, timeout=8)

    logger.info("[probes] Registered %d health probes", len(...))
```

**main.py 修改**：将现有 2 行探针注册替换为：

```python
from .monitor.probes import register_all_probes
register_all_probes()
```

### 5.4 硬编码路径接入（手动埋点方案）

对于 `china_market.py` 中的硬编码降级链，不做大重构（避免引入 bug），改为在顶层函数的手工记录事件点。

**方案**：在调用处使用 `source_event_store.record_sync()`，不侵入现有逻辑。

**为什么不用 `asyncio.ensure_future`？**
`china_market.py` 是纯同步模块，这些函数可能通过 `run_in_thread` / `_exec` 在独立线程中执行，
此时没有运行中的事件循环，`asyncio.ensure_future` 会抛出 `RuntimeError`。
`record_sync()` 使用 `threading.Queue` 跨线程传输，不依赖事件循环，详见 9.2 节。

具体改动点：

**文件**: `backend/app/fetchers/china_market.py`

在以下函数的每个源调用点加入 `source_event_store.record_sync()`：

| 函数 | 需监控的源 | 改动方式 |
|------|-----------|---------|
| `fetch_a_stock_realtime` | mootdx 调用行、sina 调用行 | +2 处 record |
| `fetch_a_stock_batch` | mootdx、QQ、sina 各调用行 | +3 处 record |
| `fetch_hk_stock_realtime` | sina、QQ、EM 各调用行 | +3 处 record |
| `fetch_index_realtime` | mootdx、QQ 各调用行 | +2 处 record |
| `fetch_futures_realtime` | akshare 调用行 | +1 处 record |
| `fetch_etf_list` | sina、akshare 各调用行 | +2 处 record |

需要新增 import：

```python
from ..monitor.source_events import source_event_store
```

**记录手法示例**（`fetch_a_stock_realtime`）：

```python
def fetch_a_stock_realtime(symbol=None):
    with no_proxy():
        if not symbol:
            return []
        t0 = time.monotonic()
        items = _mootdx_realtime([symbol])
        elapsed = (time.monotonic() - t0) * 1000
        if items and items[0].get("price"):
            source_event_store.record_sync(
                "mootdx", "A_stock_realtime", "realtime",
                True, elapsed, target=symbol)
            return items
        source_event_store.record_sync(
            "mootdx", "A_stock_realtime", "realtime",
            False, elapsed, target=symbol)
        t0 = time.monotonic()
        items = _sina_realtime([symbol], "A")
        elapsed = (time.monotonic() - t0) * 1000
        source_event_store.record_sync(
            "sina", "A_stock_realtime", "realtime",
            bool(items and items[0].get("price")), elapsed, target=symbol)
        return items
```

> `record_sync()` 是纯同步方法（内部用 `threading.Queue`），可以在任何线程中安全调用，不会阻塞调用者。

### 5.5 所有数据源一览

以下为系统涉及的全部数据源，按优先级/业务域分组的完整清单：

| 源名称 | 类型 | 用途 | 接入方式 |
|--------|------|------|---------|
| `mootdx` | A股行情 | A股实时 / 指数 / K线 | decorator 接入 |
| `sina` | A股行情 | A股实时 / 港股实时 / ETF列表 / 全球指数 | decorator 接入 |
| `tencent` (QQ) | A股行情 | A股批量 / 港股实时 / 指数 | decorator 接入 |
| `akshare` | 综合数据 | ETF列表 / 指数K线 / 基金净值 / 期货 | decorator + SourceRegistry |
| `dongfang` (EM) | 综合数据 | 港股实时 / 行业板块 / 资金流向 | decorator 接入 |
| `twelvedata` | 美股行情 | 美股实时 | SourceRegistry (已有) |
| `finnhub` | 美股行情 | 美股实时 / K线 | SourceRegistry (已有) |
| `alphavantage` | 美股行情 | 美股实时 / K线 | SourceRegistry (已有) |
| `yfinance` | 美股行情 | 美股实时 / 历史数据 | SourceRegistry (已有) |
| `levistock` | 市场情绪 | 财联社快讯 / 板块热度 / 市场情绪 | SourceRegistry (已有) |
| `fred` (FRED) | 宏观数据 | VIX / 美债收益率 / CPI / 非农 | 单独接入 |
| `tushare` | 基本面 | 个股基本面数据 | 单独接入 |

---

## 六、API 契约

所有端点挂载在 `admin.py` 的已有路由前缀 `/api/v1/admin` 下。

### 6.1 源健康概览

```
GET /api/v1/admin/sources
```

**请求参数**：无

**响应**：

```json
{
  "sources": [
    {
      "name": "mootdx",
      "available": true,
      "failure_count": 0,
      "cool_until": null,
      "last_event_ts": 1710000000.0,
      "last_success_ts": 1710000000.0,
      "last_failure_ts": null,
      "last_error": "",
      "success_rate_1h": 0.98,
      "success_rate_24h": 0.95,
      "avg_duration_1h": 234.5,
      "avg_duration_24h": 312.1,
      "events_1h": 120,
      "events_24h": 2800
    }
  ],
  "total_sources": 14,
  "available_sources": 12,
  "overall_success_rate_24h": 0.93,
  "overall_errors_24h": 42
}
```

**说明**：`available` 根据 `SourceRegistry` 的冷却状态判断。`success_rate_*` 和 `avg_duration_*` 从 `source_events.db` 聚合（而非熔断器状态），以保证重启后仍可查询历史。

### 6.2 源事件时间线

```
GET /api/v1/admin/sources/events
```

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `source` | string | - | 全部 | 过滤特定源 |
| `hours` | int | - | 24 | 时间窗口 |
| `bucket` | string | - | `hour` | 聚合粒度：`hour` / `day` |

**响应**：

```json
{
  "source": null,
  "hours": 24,
  "bucket": "hour",
  "timeline": [
    {
      "window": "2026-07-21T08:00:00",
      "success": 45,
      "failure": 2,
      "total": 47,
      "success_rate": 0.957,
      "avg_duration_ms": 289.3
    }
  ]
}
```

### 6.3 最近失败事件

```
GET /api/v1/admin/sources/failures
```

| 参数 | 类型 | 必需 | 默认 | 说明 |
|------|------|------|------|------|
| `limit` | int | - | 50 | 最多返回条数 |
| `source` | string | - | 全部 | 过滤特定源 |

**响应**：

```json
{
  "failures": [
    {
      "id": 1024,
      "source_name": "mootdx",
      "route": "A_stock_realtime",
      "operation": "realtime",
      "target": "510050",
      "duration_ms": 5120.0,
      "error_message": "Connection timed out",
      "timestamp": 1710000000.0
    }
  ]
}
```

### 6.4 当前熔断状态

```
GET /api/v1/admin/sources/circuit-breakers
```

**响应**：

```json
{
  "breakers": [
    {
      "name": "twelvedata",
      "available": true,
      "cool_until": null,
      "failure_count_since_reset": 0,
      "cooldown_secs": 60,
      "failure_threshold": 3
    },
    {
      "name": "mootdx",
      "available": false,
      "cool_until": 1710000600.0,
      "failure_count_since_reset": 3,
      "cooldown_secs": 60,
      "failure_threshold": 3
    }
  ]
}
```

---

## 七、前端设计

### 7.1 路由与导航

在 `App.vue` 导航栏加入新入口，与 Token 监控并列：

```javascript
{ path: '/source-monitor', label: '数据源监控', icon: '📡' }
```

路由注册（`router/index.js`）：

```javascript
{
  path: '/source-monitor',
  name: 'source-monitor',
  component: () => import('../components/SourceMonitor.vue'),
  meta: { title: '数据源监控', description: '数据源健康状态与稳定性趋势' },
}
```

### 7.2 页面布局

**组件**: `frontend/src/components/SourceMonitor.vue`

页面结构（复用 `TokenMonitor.vue` 的设计系统）：

```
┌──────────────────────────────────────────────────────┐
│  📡 数据源监控                                         │
│                                                      │
│ ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐             │
│ │ 总源数 │  │ 在线率 │  │ 今日失败 │  │ 最慢源 │  ← 概览卡 |
│ │  14   │  │ 86%  │  │  42  │  │ mootdx│             │
│ └──────┘  └──────┘  └──────┘  └──────┘             │
│                                                      │
│ ┌────────────────────────────────────────┐           │
│ │ 源状态矩阵（卡片网格）                       │           │
│ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ │           │
│ │ │ mootdx   │ │ sina     │ │ tencent  │ │           │
│ │ │ 🟢 可用   │ │ 🟡 波动   │ │ 🔴 冷却中  │ │           │
│ │ │ 95% / 45ms│ │ 80% /120ms│ │ 冷却至14:32│           │
│ │ │ 最后失败:—│ │ 13:42 超时│ │ 12:00 连续3次│           │
│ │ └──────────┘ └──────────┘ └──────────┘ │           │
│ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ │           │
│ │ │ twelvedata│ │ finnhub  │ │ akshare  │ │           │
│ │ │ ...      │ │ ...      │ │ ...      │ │           │
│ │ └──────────┘ └──────────┘ └──────────┘ │           │
│ └────────────────────────────────────────┘           │
│                                                      │
│ ┌────────────────────────────────────────┐           │
│ │ 稳定性趋势（ECharts 折线图）                │           │
│ │ · 源选择下拉框  [mootdx ▼]              │           │
│ │ · 切换标签页 [成功率] [平均耗时]         │           │
│ │ ┌────────────────────────────────────┐ │           │
│ │ │  📈 成功率趋势 (24h)                │ │           │
│ │ │  100% ████████████▁▁▁▁▁████████   │ │           │
│ │ │   50% ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁    │ │           │
│ │ │    0% ──────────────────────────  │ │           │
│ │ └────────────────────────────────────┘ │           │
│ └────────────────────────────────────────┘           │
│                                                      │
│ ┌────────────────────────────────────────┐           │
│ │ ❌ 最近失败事件                           │           │
│ │ │ 时间        │ 源       │ 标的  │ 错误  │           │
│ │ │ 14:23:15   │ mootdx   │ 510050│ 超时   │           │
│ │ │ 14:23:10   │ akshare  │ 510880│ 限流   │           │
│ └────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────┘
```

**API 层**（`frontend/src/api/index.js`）：

```javascript
export const adminApi = {
  // ... 现有 token 端点 ...
  sourceSummary: () => api.get('/admin/sources'),
  sourceEvents: (params) => api.get('/admin/sources/events', { params }),
  sourceFailures: (params) => api.get('/admin/sources/failures', { params }),
  sourceBreakers: () => api.get('/admin/sources/circuit-breakers'),
}
```

**状态指示灯规则**：

| 状态 | 条件 | 色值 |
|------|------|------|
| 🟢 稳定 | 可用且 24h 成功率 ≥ 95% | `#52c41a` |
| 🟡 波动 | 可用但 24h 成功率 < 95% 或 avg_duration > 2s | `#faad14` |
| 🔴 不可用 | 熔断冷却中或 24h 成功率 < 50% | `#ff4d4f` |
| ⚫ 无数据 | 从未被访问过或探针未注册 | `#d9d9d9` |

---

## 八、实施路线

### Phase 1 — 核心采集闭环

**目标**：埋点采集跑通，API 可用，不依赖前端。

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| 1.1 | 新建 `SourceEventStore` | `backend/app/monitor/source_events.py` | 内存环 + SQLite + 异步刷盘 |
| 1.2 | 增强 `SourceHealth` 事件回调 | `backend/app/services/source_registry.py` | `record_success/failure` 中加入事件回调 + 耗时计量 |
| 1.3 | 增强 `route()` 耗时节 | `backend/app/services/source_registry.py` | `time.monotonic()` 计时 |
| 1.4 | main.py 挂载回调 | `backend/app/main.py` | `registry.set_event_callback(...)` |
| 1.5 | 新增 API 端点 | `backend/app/routers/admin.py` | `/sources`, `/sources/events`, `/sources/failures`, `/sources/circuit-breakers` |
| 1.6 | china_market 接入 | `backend/app/fetchers/china_market.py` | 关键路径加 event record |
| 1.7 | 验证 | `verify_e2e.py` | 确认 `/admin/sources` 返回非空数据 |

**验证方法**：
```bash
# 启动后端
cd backend && uvicorn app.main:app --reload
# 等一轮行情刷新后
curl http://localhost:8000/api/v1/admin/sources | python -m json.tool
# 预期：mootdx / sina / akshare 等源均有数据
```

### Phase 2 — 探针 + 前端展示

**目标**：探针全覆盖 + UI 可视化。

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| 2.1 | 新建 `probes.py` | `backend/app/monitor/probes.py` | 注册全部 12+ 数据源探针 |
| 2.2 | 精简 main.py | `backend/app/main.py` | 替换为 `register_all_probes()` |
| 2.3 | 前端 API 层 | `frontend/src/api/index.js` | 加 `adminApi.source*` |
| 2.4 | 前端组件 | `frontend/src/components/SourceMonitor.vue` | 源状态矩阵 + 趋势图 + 失败事件 |
| 2.5 | 路由注册 | `frontend/src/router/index.js` | 加 `/source-monitor` |
| 2.6 | 导航入口 | `frontend/src/App.vue` | 加导航项 |

### Phase 3 — 告警与增强

**目标**：自动告警 + 清理策略。

| # | 改动 | 说明 |
|---|------|------|
| 3.1 | WS 推送源状态变化 | 当某源进入/退出冷却时 push 通知 |
| 3.2 | 数据清理 | 启动 + 写入时清理 7 天前数据 |
| 3.3 | 源健康与 pool_manager 联动 | PoolManager 决策时参考源可靠性权重 |

---

## 九、风险与考量

### 9.1 数据量控制

**风险**：`china_market.py` 的 `_build_price_map` 每 15 秒刷新所有 ETF，如果 per-symbol 记录事件，每天约 86 万条（`200 ETF * 4 batch/s * 60 * 24 / 15`），SQLite 写不现实。

**对策**：在批量函数的每个源调用点**一个批次记一条**，不记 per-symbol。例如：

```python
def fetch_a_stock_batch(symbols):
    t0 = time.monotonic()
    items = _mootdx_realtime(symbols)
    elapsed = (time.monotonic() - t0) * 1000
    target = f"batch[{len(symbols)}]"  # 不展开 symbols
    # record 一次，而非 len(symbols) 次
```

这样每天约 5000 条（`~12 源 * 每源 ~400 次调用`），7 天约 3.5 万条，SQLite 无压力。

### 9.2 性能影响

**风险**：`record_sync()` 使用 `threading.Queue.put_nowait()`，在同步函数中是否会有锁竞争或阻塞？

**分析**：
- `threading.Queue.put_nowait()` 是纯内存操作（原子性入队），不涉及 I/O，单次耗时 < 1µs。
- `record_sync()` 不做任何上锁操作——仅将事件放入线程安全队列，由后台 `_flush_worker` 异步消费。
- `TokenUsageStore` 的 `record()` 走的是同一模式（`asyncio.Queue`），已在生产中使用。
- 数据源访问本身耗时 200ms-5s，监控开销可忽略。

**对比 `asyncio.ensure_future`**：在无事件循环的线程中会抛 `RuntimeError`（Python 3.12+ 尤其严格），`record_sync()` 无此限制。

### 9.3 重启动数据保留

`source_events.db` 独立于 `portfolio.db`，重启不会丢失。启动时自动清理 7 天前的历史数据，避免磁盘膨胀。

---

## 十、检查清单

### Phase 1 Checklist

- [ ] `backend/app/monitor/source_events.py` — SourceEventStore 完整实现（含 `record_sync` / `shutdown` / `_thread_queue` / `_drain_thread_queue`）
- [ ] `backend/app/monitor/__init__.py` — 导出 `source_event_store`
- [ ] `source_registry.py` — `SourceHealth` 增加 `on_event` 回调 + `name` + 耗时计量
- [ ] `source_registry.py` — `route()` 增加 `route_name` 参数并记录耗时
- [ ] `source_registry.py` — `SourceRegistry.set_event_callback()` 方法
- [ ] `main.py` — lifespan 中调用 `registry.set_event_callback(_make_event_callback())` + shutdown 时 `source_event_store.shutdown()`
- [ ] `market_service.py` — `_route_us` 调用 `route()` 时传入 `route_name="US_ETF"`
- [ ] `sector_fetcher.py` — `_try_two` 调用 `route()` 时传入 `route_name`
- [ ] `admin.py` — 新增 4 个端点：`/sources`, `/sources/events`, `/sources/failures`, `/sources/circuit-breakers`
- [ ] `china_market.py` — 6 个函数的源调用点加入 `record_sync()` + import
- [ ] `tests/test_source_events.py` — 单元测试（mock SQLite，验证 `record` / `record_sync` / `source_summary` / `timeline` / `recent_failures`）
- [ ] `tests/test_probes.py` — 验证所有探针函数可被调用（mock 网络请求）
- [ ] `verify_e2e.py` — 追加 `/admin/sources` 的 E2E 检查项

### Phase 2 Checklist

- [ ] `backend/app/monitor/probes.py` — 注册 12+ 数据源探针
- [ ] `main.py` — 替换为 `register_all_probes()` 一行
- [ ] `frontend/src/api/index.js` — `adminApi.source*` 4 个方法
- [ ] `frontend/src/components/SourceMonitor.vue` — 页面组件完整
- [ ] `frontend/src/router/index.js` — 路由注册
- [ ] `frontend/src/App.vue` — 导航入口
- [ ] `npm run build` — 通过无报错

### Phase 3 Checklist

- [ ] WS 推送源状态变化
- [ ] 7 天数据滚动清理
- [ ] pool_manager 源可靠性权重联动

---

> **下一步**：审查完成后，从 Phase 1 #1 开始编码，按检查清单逐项完成。
