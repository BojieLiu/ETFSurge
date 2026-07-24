# 事件循环阻塞与数据管道异步化重构方案

**版本:** v1.3  
**日期:** 2026-07-24  
**状态:** ✅ **已实施** — 2026-07-24 在 commit `2be9ccb` 中落地（Phase 0.9）  
**实施说明:** 参见 `docs/implementation-master-plan.md` § Phase 0.9。6 个 Phase 全部在单次 commit 中完成：10 文件改动，493 行新增，119 行删除。包括: P0（因子阻塞修复）、P1（线程池统一）、P1.5（冷却期污染）、P2（预热超时）、P3（full_pipeline 45s）、P4（测试防护）。  
**后续增强（uncommitted）:** 线程池从 32 进一步扩至 64 workers，增加队列深度 WARNING 日志和 `total_spawned` 指标，应对高并发 E2E 场景下的线程池耗尽问题。  

---

## 1. 问题总结

设计管道和定时调度器在启动后数秒内导致整个服务不可用。所有 API 端点（包括 `/health`）在 POST `/design-async` 后 8-15s 内超时。诊断确认**事件循环被同步 I/O 长时间阻塞**，并非操作系统资源限制。

---

## 2. 根因分析

### 2.1 P0 BUG — `factor_registry._fetch_market_data` 同步 I/O 直接 await

**位置**: `backend/app/factors/factor_registry.py:656-659`

```python
async def fetch_one(sym):
    try:
        rows = await asyncio.wait_for(
            fetch_history(sym, "A", "daily"), timeout=10   # ← BUG
        )
```

`fetch_history` (`backend/app/fetchers/china_market.py:742`) 是**纯同步函数**（`def`，非 `async def`），内部调用 mootdx TCP socket + Sina HTTP GET + akshare HTTP。直接 `await` 同步函数导致：

1. `fetch_history(sym, ...)` 在**事件循环线程上同步执行**（阻塞 3-15s/只）
2. 返回 `list[dict]`，传入 `asyncio.wait_for()` → 收到非 awaitable 值 → 立即 `TypeError`
3. `TypeError` 被 `except Exception` 静默吞掉 (`factor_registry.py:677`)
4. 因子计算永远在空数据上运行，产生无效结果

**影响范围**：30-58 只 ETF 的 `fetch_one` 通过 `asyncio.gather(*tasks)` 并发执行，每只阻塞 3-15s → 事件循环冻结 30s+。

**调用链**：

```
design_pipeline() @ task_manager.py:174
  └── asyncio.wait_for(generate_enhanced_design(), timeout=60)
        └── generate_enhanced_design() @ strategy_design.py:28
              └── await pool_manager.refresh()
                    └── await _refresh_impl()
                          ├── await run_sync(full_pipeline, timeout=120)  ✓ 线程池
                          ├── await run_sync(classifier.batch_classify)   ✓ 线程池
                          └── await factor_registry.compute(symbols)
                                └── await _fetch_market_data(symbols)
                                      └── await asyncio.gather(*[fetch_one(sym) for sym in 30-58只])
                                            └── fetch_one(sym):
                                                  await asyncio.wait_for(
                                                    fetch_history(sym, ...),  ← 同步！❌
                                                  )
```

**同样问题也存在于 `market_trends.py:195`**（但通过 `asyncio.to_thread` 包装了，正确—仅作为对比参考）。

### 2.2 策略检查管道也有类似风险

**位置**: `backend/app/services/portfolio_service.py`

`strategy_check()` 调用 `factor_registry.compute(symbols)` 走同样的 `_fetch_market_data` → `await fetch_history(...)` 路径，同样会阻塞事件循环。修复 P0 后两条管道都受益。

### 2.3 P1 — 线程池架构割裂

`backend/app/core/async_utils.py` 定义了两种桥接函数，但指向不同 executor：

| 函数 | Executor | max_workers | 调用方 |
|------|----------|-------------|--------|
| `run_sync()` | 默认 executor (`loop.run_in_executor(None, ...)`) | `min(32, cpu+4)` ≈ 12 | `market_service._call` (16处)、news router (5处)、`pool_manager` (2处) |
| `run_in_thread()` | `_shared_executor` | 16 | `china_market.py` (9处)、sentiment/sector/fund fetcher |
| `_ak()` (news_fetcher) | `_akshare_executor` | 4 | 仅 akshare 隔离 |

**冲突点**：
- `run_sync()` 和 `asyncio.to_thread()` 共享默认 executor（Python 事件循环全局），**无监控**
- 启动时 `_warmup_etf_cache` + 因子导入 + `market`/`global` 预热 = 3-4 个并发任务抢相同 worker
- `benchmark_stocks.py:129-131` 可爆发 45 个并发 `asyncio.to_thread()` 调用，瞬间填满默认 executor
- `refresh_news_cache` → `asyncio.to_thread(fetch_news_headlines)` (默认 executor) → 内部 `_safe()` → `run_in_thread()` (shared executor) → 两层嵌套
- mootdx `threading.Lock` 超时 10s，持有期间阻塞所在 executor 的一个 worker

### 2.4 P1 — 启动预热缺少超时保护

| 启动任务 | 文件:行 | 有超时？ |
|----------|---------|---------|
| `_warmup_market_cache` → `refresh_market_cache()` | main.py:65 | ✅ 25s `wait_for` |
| `_warmup_global_indices` → `get_global_indices()` | main.py:83 | ✅ 30s `wait_for` |
| `_warmup_etf_cache` → `asyncio.to_thread(fetch_all_etfs_base)` | main.py:90-98 | ❌ 无 — HTTP 挂起即永久阻塞 |
| `asyncio.to_thread(lambda: import factor_registry)` | main.py:73-77 | ❌ 无 — pandas/numpy 导入卡死 |

### 2.5 P2 — 取消后冷却期污染

`pool_manager.py:172` 在 `_refresh_impl` 运行前就设了 `_last_refresh_ts`：

```python
async with self._refresh_lock:
    self._last_refresh_ts = now      # ← 提前设置
    return await self._refresh_impl() # ← 可能被取消
```

取消后 `_last_refresh_ts` 仍为 `now` → 30s 内任何 `refresh()` 命中冷却期（`pool_manager.py:157-161`）直接返回空 diff，池永不更新。

### 2.6 P2 — 事件循环阻塞的检测盲区

当前测试防护体系（详见第5节）对此类 bug 的检测率为零。

---

## 3. 修改方案

### Phase 0 — 修复 `factor_registry._fetch_market_data`（P0）

**文件**: `backend/app/factors/factor_registry.py`

**改动细节**：

```python
# 导入（模块顶部）
from ..core.async_utils import run_sync

# _fetch_market_data 内（约 658 行）
async def fetch_one(sym: str) -> tuple[str, dict[str, Any]]:
    try:
        # 原代码（BUG）:
        # rows = await asyncio.wait_for(
        #     fetch_history(sym, "A", "daily"), timeout=10
        # )
        # 修正: 通过 asyncio.to_thread 桥接到线程池
        rows = await asyncio.wait_for(
            asyncio.to_thread(fetch_history, sym, "A", "daily"),
            timeout=10,
        )
```

**选择原因**：P0 需要立即独立修复，不依赖 P1。`asyncio.to_thread()` 与 `run_sync()` 当前行为一致（都使用默认 executor）。P1 统一线程池后自动受益。

**并发限制**：`asyncio.gather(*tasks)` 不加限制会导致 58 个并发线程池请求。添加 `asyncio.Semaphore(8)`：

```python
sem = asyncio.Semaphore(8)

async def fetch_one(sym):
    async with sem:
        ...  # 同上 await asyncio.to_thread(...)

**选择原因**：8 并发 × 10s timeout/只 × 58/8 ≈ 75s，可在 120s 全池刷新超时内安全完成。每只 ETF 正常响应 1-3s，个别超时也不影响整体。

**重要**：此修复和 `strategy_check` 中的 `factor_registry.compute` 共享同一代码路径，修复后两条管道同时受益。
```

**边界情况**：`fetch_history` 在 `asset_type == "index"` 或 `period in ("15m", "30m", "1h")` 时走不同内部路径，但这些路径同样是同步的。`asyncio.to_thread` 统一覆盖所有分支。

**验证标准**：
- `test_fetch_market_data_does_not_block_event_loop` — 执行期间 event loop 保持响应
- `test_fetch_market_data_returns_expected_shape` — mock 下返回正确结构的数据
- 并发 heartbeat 任务在 `_fetch_market_data` 全程保持推进

### Phase 1 — 统一线程池（P1）

**文件**: `backend/app/core/async_utils.py`

**改动细节**：

```python
# 增大共享线程池以承担额外负载
_shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)


async def run_sync(call, *args, timeout: int = DEFAULT_SYNC_TIMEOUT):
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        # 原来: loop.run_in_executor(None, call, *args)    ← 默认 executor
        # 改为: loop.run_in_executor(_shared_executor, ...)  ← 统一到共享池
        loop.run_in_executor(_shared_executor, call, *args),
        timeout=timeout,
    )
```

**风险**：`wait_for` 超时使用 event loop 计时器，独立于线程池。即使 `_shared_executor` 所有 worker 繁忙，新提交的任务加入队列，`wait_for` 在超时后正确 raise `TimeoutError`。**无死锁风险**。

**监控更新**：`get_thread_pool_stats()` 同时返回 default executor 和 shared executor 状态（平移过渡期）。确认所有 `asyncio.to_thread()` 调用已评估后，移除 default executor 监控。

**需要评估的 `asyncio.to_thread()` 调用**（是否统一到 `run_sync`）：

| 位置 | 调用 | 评估 |
|------|------|------|
| main.py:74 | `lambda: __import__("factor_registry")` | 一次性导入，建议保留 `to_thread`（不依赖 `run_sync` 接口） |
| main.py:93 | `fetch_all_etfs_base` | 可改为 `run_sync` |
| benchmark_stocks.py:129-131 | `asyncio.to_thread(fetch_history)` | 可改为 `run_sync`（但 P0 修复后 `fetch_history` 统一走 `to_thread`） |
| market_trends.py:195 | `asyncio.to_thread(fetch_history)` | P0 修复后已统一 |
| portfolio_service.py:527 | `asyncio.to_thread(fetch_index_realtime)` | 可改为 `run_sync` |
| source_health.py:32 | `asyncio.to_thread(fn)` per probe | 可改为 `run_sync`（使用 `_shared_executor` 共享池） |
| news_refresh.py:20 | `asyncio.to_thread(fetch_news_headlines)` | 可改为 `run_sync` |
| report_worker.py:46-47 | `asyncio.to_thread(...)` ×2 | 可改为 `run_sync` |
| ws.py:60 | `asyncio.to_thread(fetch_history)` | 可改为 `run_sync` |

**结论**：除一次性初始化导入（main.py:74）保留 `asyncio.to_thread` 外，其余可逐步统一。建议本次 P1 仅修改 `run_sync` 实现，不改变调用方。

**监控更新**：`get_thread_pool_stats()` 需要同步更新以监控两大 executor（过渡期）：

```python
def get_thread_pool_stats() -> dict:
    return {
        "shared_executor": {"max_workers": 32, "alive_threads": ..., "pending_tasks": ...},
        "default_executor": {"max_workers": ..., "alive_threads": ..., "pending_tasks": ...},
    }
```

确保 `admin.py` 端点和 `probes.py` 同时暴露两个池的状态。P1 完全落地且所有 `asyncio.to_thread` 迁移到 `run_sync` 后，移除 default executor 监控。

### Phase 1.5 — 修复冷却期污染（P1）

**文件**: `backend/app/services/pool_manager.py`

**改动**：采用"前置设置 + 失败清除"模式：

```python
async with self._refresh_lock:
    self._last_refresh_ts = now   # 防止并发刷新
    try:
        return await self._refresh_impl()
    except Exception:
        self._last_refresh_ts = 0  # 失败后清除，允许重试
        raise
```

**选择原因**：相比"成功后置"（选项一），本方案保持并发保护，同时允许失败后立即重试而非等待 30s。

### Phase 2 — 启动预热加固（P2）

**文件**: `backend/app/main.py`

**改动细节**：

```python
# 约 90-98 行
async def _warmup_etf_cache():
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(fetch_all_etfs_base), timeout=60
        )
        if result:
            logger.info("ETF 缓存预热完成：%d 只", len(result))
    except asyncio.TimeoutError:
        logger.warning("ETF 缓存预热超时（60s），不影响启动")
    except Exception:
        logger.warning("ETF 缓存预热失败（不影响启动）")

# 约 73-77 行
async def _warmup_factor_registry():
    try:
            await asyncio.wait_for(
                asyncio.to_thread(lambda: __import__("app.factors.factor_registry")),
                timeout=60,
            )
            logger.info("因子注册表预热完成")
        except asyncio.TimeoutError:
            logger.warning("因子注册表预热超时（60s），不影响启动")
    except Exception:
        logger.warning("因子注册表预热失败（不影响启动）")
```

`_warmup_factor_registry` 作为独立任务取代原来的 `asyncio.create_task(asyncio.to_thread(...))`。

**关于 scheduler 恢复**：当前 APScheduler 代码已在 diagnostics 期间注释掉。本方案不包括恢复 scheduler，但建议在 P0-P4 全部实施完毕后恢复。恢复前需验证：
- 调度器 15s 周期的 `refresh_market_cache` 会调用 `pool_manager.refresh()`，与设计管道共享 `_refresh_lock`（已有保护）
- 调度器任务经 P1 统一后全部使用 `_shared_executor`，不会阻塞 event loop
- 恢复验证方法：调度器运行 5 分钟后 `/health` 仍可正常返回 200

### Phase 3 — full_pipeline 超时熔断（P2）

**文件**: `backend/app/services/pool_manager.py`

**改动**：

```python
# 原来: raw_layers = await run_sync(self.scanner.full_pipeline, timeout=120)
# 改为:
raw_layers = await run_sync(self.scanner.full_pipeline, timeout=45)
```

+ 在 `_refresh_impl` 结束时添加耗时日志：

```python
logger.info("PoolManager: full_pipeline completed in %.1fs", time.time() - start)
```

### Phase 4 — 测试防护体系增强（P3）

#### 事件循环响应性测试

**新增文件**: `backend/tests/test_async_boundaries.py`

```python
async def test_fetch_market_data_does_not_block_event_loop():
    """验证 _fetch_market_data 执行期间 event loop 保持响应。
    
    如果 _fetch_market_data 在 event loop 上做同步调用，heartbeat
    任务会卡住，计数器无法推进。此测试通过 heartbeat 推进验证。
    """
    from app.factors.factor_registry import registry
    from unittest.mock import patch, MagicMock

    heartbeats = 0

    async def heartbeat():
        nonlocal heartbeats
        for _ in range(30):  # 30 × 50ms = 1.5s
            await asyncio.sleep(0.05)
            heartbeats += 1

    heart_task = asyncio.create_task(heartbeat())

    # Mock fetch_history 使其不依赖网络
    with patch("app.factors.factor_registry.fetch_history") as mock_fetch:
        mock_fetch.return_value = [
            {"close": 4.0, "high": 4.1, "low": 3.9, "volume": 10000}
            for _ in range(30)
        ]
        result = await registry._fetch_market_data(["510300", "560600"])

    heart_task.cancel()
    assert heartbeats > 20, (
        f"Event loop was blocked during _fetch_market_data: "
        f"only {heartbeats}/30 heartbeats completed"
    )
```

#### 同步函数直接 await 检测（AST 静态扫描）

**新增文件**: `backend/tests/test_async_lint.py`

```python
import ast
import os

# 已知同步函数名模式（黑名单）
_SYNC_PATTERNS = [
    "fetch_history",
    "fetch_a_stock_batch",
    "_mootdx_",
    "_sina_",
    "_tencent_",
    "run_in_thread",
    "requests.",
    "urllib.",
]


def _is_sync_call(node: ast.Await) -> bool:
    """检测 await 的目标是否是黑名单中的同步函数。"""
    if isinstance(node.value, ast.Call):
        func = node.value.func
        if isinstance(func, ast.Name):
            return any(p in func.id for p in _SYNC_PATTERNS)
        if isinstance(func, ast.Attribute):
            return any(p in func.attr for p in _SYNC_PATTERNS)
    return False


def test_no_direct_await_of_sync_function():
    errors = []
    base = os.path.join(os.path.dirname(__file__), "..", "app")

    for root, _, files in os.walk(base):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())

            for node in ast.walk(tree):
                if isinstance(node, ast.Await) and _is_sync_call(node):
                    rel = os.path.relpath(path, base)
                    errors.append(f"{rel}:{node.lineno}: await sync function detected")

    assert not errors, "\n".join(errors[:10])
```

**豁免规则**：如果 `await` 的目标是 `asyncio.wait_for(asyncio.to_thread(...), ...)` 模式，则跳过检测：

```python
def _is_exempted(node: ast.Await) -> bool:
    """跳过已正确包装的 await sync 模式。"""
    call = node.value
    if not isinstance(call, ast.Call):
        return False
    # 匹配 asyncio.wait_for(asyncio.to_thread(...), ...)
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "wait_for":
        for arg in call.args:
            if isinstance(arg, ast.Call):
                inner = arg.func
                if isinstance(inner, ast.Attribute) and inner.attr == "to_thread":
                    return True
    return False

def _is_sync_call(node: ast.Await) -> bool:
    if _is_exempted(node):
        return False
    ...  # 原检测逻辑
```

这样 `await asyncio.wait_for(asyncio.to_thread(fetch_history, ...), timeout=10)` 通过豁免，而 `await fetch_history(...)` 仍被标记。

#### E2E 增强：事件循环存活检测

**文件**: `backend/scripts/verify_e2e.py`

在 `section_design` 异步轮询中加入并发 health ping：

```python
def section_design(host, port):
    ...
    # 并发 health ping（独立线程）
    health_ok = True
    def _health_pinger():
        nonlocal health_ok
        for _ in range(90):  # 90s
            time.sleep(1)
            try:
                requests.get(f"{BASE}/health", timeout=5)
            except:
                health_ok = False
                break
    import threading
    t = threading.Thread(target=_health_pinger, daemon=True)
    t.start()
    
    # 主轮询逻辑（60s 超时）
    ...
    
    check("设计期间 event loop 保持响应", health_ok,
          "事件循环疑似被阻塞" if not health_ok else "")
    t.join(timeout=0)
```

#### 线程池占用监控断言

**文件**: `backend/scripts/verify_e2e.py`

在 `section_admin` 中增加：

```python
pool_stats = await async_get(f"{BASE}/api/v1/admin/thread-pool")
if pool_stats:
    shared = pool_stats.get("shared_executor", {})
    check("shared_executor 未过载",
          shared.get("active", 0) < shared.get("max", 32) * 0.8,
          f"active={shared.get('active')}/{shared.get('max')}")
```

---

## 4. 实施顺序与依赖（已实施）

> ⚠️ 以下所有 Phase 已于 commit `2be9ccb` 中完成。保留为架构记录。

| Phase | 任务 | 文件 | 依赖 | 风险等级 | 实施状态 |
|-------|------|------|------|---------|:--------:|
| P0 | 修复 `_fetch_market_data` 同步 await + 并发限制 | `factor_registry.py` | 无 | 🔴 最高 | ✅ 已实施 |
| P1.5 | 修复冷却期污染 | `pool_manager.py` | 无 | 🟢 低 | ✅ 已实施 |
| P2 | 启动预热加超时 | `main.py` | 无 | 🟢 低 | ✅ 已实施 |
| P1 | 统一 `run_sync` 到 `_shared_executor` | `async_utils.py` | 无 | 🟡 中 | ✅ 已实施 |
| P3 | full_pipeline 超时 120→45s | `pool_manager.py` | 无 | 🟢 低 | ✅ 已实施 |
| P4 | 测试防护增强 | 新增/修改测试文件 | P0-P3 | 🟢 低 | ✅ 已实施 |

**实施顺序**：P0 → P1.5 → P2 → P1 → P3 → P4。全部按顺序落地。

---

## 5. 测试缺陷分析

### 当前防护体系为何漏检

| 测试层 | 文件 | 覆盖了什么 | 漏掉了什么 |
|--------|------|-----------|-----------|
| 单元（mocked） | `test_design_tasks.py` | pipeline 逻辑、task 状态 | 全部外部依赖被 mock，不涉及真实数据源 |
| 单元（mocked） | `test_design_pipeline_integration.py` | pipeline 5 阶段 | `generate_enhanced_design` 整体被 mock |
| 因子测试 | `test_factor_registry.py` | 各 factor computer 纯函数 | 使用 mock 数据，不调用 `_fetch_market_data` |
| E2E | `verify_e2e.py` | HTTP status、task 完成 | 只检查单线程顺序请求，不检测并发响应性 |
| CI pre-commit | `.githooks/pre-commit` | 前端 build | 不涉及后端 |

**漏检模式总结**：测试的 mock 边界恰好包围了有 bug 的真实 I/O 路径。单元测试 mock 了 `generate_enhanced_design` 整体（跳过了 `factor_registry`），因子测试 mock 了所有市场数据（跳过了 `fetch_history`）。**mock 边界和 bug 边界重合时，测试永远通不过真实数据。**

### 新增防护层次

| 层次 | 类型 | 检测什么 | 运行时机 | 误报风险 |
|------|------|---------|---------|---------|
| **AST lint** | 静态分析 | `await sync_func()` 模式 | pre-commit / pytest | 低（有豁免规则） |
| **事件循环响应测试** | 单元测试 | `_fetch_market_data` 不阻塞 event loop | pytest | 无（mock 环境下确定性的） |
| **并发 health ping** | E2E | 后台任务不阻塞主循环 | `verify_e2e.py` | 低（网络抖动可能导致误报，设重试） |
| **线程池监控断言** | E2E | executor 占用率 < 80% | `verify_e2e.py --module admin` | 低（阈值可调） |
| **启动预热日志** | 运行时 | 各预热任务耗时 | 每次启动 | 无 |

**三层检测模型**：

```
AST lint (pre-commit)    → 静态发现模式违规
     ↓
事件循环响应测试 (pytest) → 验证关键路径不阻塞
     ↓
并发 health ping (E2E)   → 集成验证真实请求
```

任何一层失败即阻断提交/部署。

---

## 6. 实施后验证标准

1. **`pytest backend/tests/ -v` 全部通过**（含 `test_async_boundaries.py` 和 `test_async_lint.py`）
2. **`python scripts/verify_e2e.py` 全部 PASS**（含并发 health ping 和线程池断言）
3. 启动后发 POST `/design-async`，60s 轮询期间 `/health` 始终 200
4. 线程池管理页面 `active < 80% max`
5. 设计管道最终返回 `report_quality: "full"` 或 `"fallback"`
6. 预热任务统一 `wait_for` 覆盖，超时后不影响启动

---

## 7. 文件变更清单

| 文件 | 类型 | 变更内容 | 对应 Phase |
|------|------|---------|-----------|
| `backend/app/factors/factor_registry.py` | 修改 | `_fetch_market_data`: `fetch_history` → `asyncio.to_thread`；加 Semaphore(4) | P0 |
| `backend/app/core/async_utils.py` | 修改 | `run_sync` 改用 `_shared_executor`；pool 16→32 | P1 |
| `backend/app/services/pool_manager.py` | 修改 | 冷却期后移 + 失败清除；`full_pipeline` 120→45s；耗时日志 | P1.5 + P3 |
| `backend/app/main.py` | 修改 | ETF 预热 + 因子导入加 `wait_for(timeout=30)` | P2 |
| `backend/tests/test_async_boundaries.py` | 新增 | 事件循环响应性测试 | P4 |
| `backend/tests/test_async_lint.py` | 新增 | AST 静态扫描：await 同步函数检测 | P4 |
| `backend/scripts/verify_e2e.py` | 修改 | 并发 health ping + 线程池断言 | P4 |
