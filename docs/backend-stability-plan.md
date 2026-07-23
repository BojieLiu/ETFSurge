# 后端稳定性修复方案

## 根因回顾

```
设计任务提交 → POST /design-async (2.7s 返回 task_id)
    ↓
asyncio.create_task(design_worker)
    ↓
generate_enhanced_design()
    ↓
run_sync(pool_manager.refresh()) → 线程池
    ↓
full_pipeline() 同步 HTTP (akshare/新浪) 跑在 A 线程
    ↓
full_pipeline 跑完 → batch_classify → 因子计算 → ...
    ↓
pool_manager.refresh() 30s 超时 → asyncio.wait_for 抛出 TimeoutError
    ↓
协程被取消！但 A 线程！！！依然在跑 full_pipeline！！！
    ↓
A 线程跑完 → 写入 SQLite → SQLITE_BUSY → 等待 30s
    ↓
后续所有 API 请求的 SQLite 操作都被阻塞 → 后端挂死
```

**核心矛盾**: `asyncio.wait_for` 不能取消 `run_in_executor` 的线程。Future 取消了，线程继续跑，SQLite 写锁被线程占用，事件循环上的协程全部排队等锁。

---

## 方案对比

### 方案 A: 同步线程池隔离（SQLite 专用连接）✅ 推荐

**思路**: 给线程池任务开独立的 SQLite 连接，不跟事件循环上的协程抢连接。

**改动量**: 小—中（3 个文件改动）

**关键改动**:

1. `pool_manager.py` refresh() 里加冷却期保护（已完成 ✅）
2. `database.py`: 暴露一个 `sync_session_factory`（使用 `sqlalchemy.create_engine` 而非异步引擎）
3. 所有 `run_sync` 的内部调用（full_pipeline, batch_classify 等）若需要写 DB，通过同步 session 写

**优点**:
- 改动最小，验证最快
- 线程池线程和事件循环协程用不同连接，彻底消除写锁竞争
- 不阻塞事件循环上的 API 请求

**缺点**:
- 需要识别出哪些 run_sync 内的代码会触达 SQLite
- DB 连接数翻倍

---

### 方案 B: 任务队列 + 专用工作进程（Celery / RQ）

**思路**: 把后台任务彻底移出 asyncio 进程，用独立进程跑。

**改动量**: 大（引入新依赖 + 基础设施）

**优点**:
- 彻底隔离：任务进程挂死不影响 API 进程
- 可扩展：可以跑多个 worker
- 成熟方案：Celery 有完善的超时/重试/监控

**缺点**:
- 引入 Redis/RabbitMQ 依赖
- 部署复杂度大增（Docker 需加新 service）
- 学习成本
- 为目前的负载水平（个人项目）过度工程

---

### 方案 C: 去 SQLite 换 PostgreSQL

**思路**: 用真正支持并发的数据库。

**改动量**: 大（换数据库 + 改连接方式）

**优点**:
- 真并发读写，无写锁问题
- `asyncpg` 驱动稳定
- 生产级

**缺点**:
- 需要运行 PostgreSQL 服务（Docker 或安装）
- 迁移所有表结构和数据
- 改所有查询适配 PG 语法

---

### 方案 D: 只加冷却期 + 超时熔断

**思路**: 不修线程取消问题，用"防重复"和"超时熔断"避免触发死锁路径。

**改动量**: 小（已基本完成）

**当前已完成**:
- ✅ `refresh()` 30s 冷却期
- ✅ `_refresh_lock` 并发锁
- ✅ `_refresh_market_snapshot` fire-and-forget
- ✅ `run_sync` 包裹同步调用
- ✅ SQLite connect_args timeout=30s

**但**: 只要触发刷新（冷却期过期 + 并发请求），仍可能死锁。不彻底。

---

## 推荐方案: A + D 组合

**短期（半天内实施）**: 方案 A（隔离连接）+ 当前 D
**长期（未来迭代）**: 若并发量持续增长，再考虑方案 B 或 C

### 实施步骤

| # | 任务 | 文件 | 预估 |
|---|------|------|:----:|
| 1 | `database.py` 加同步 `sync_engine` / `sync_session` | `database.py` | ~5 行 |
| 2 | 在 `run_sync(full_pipeline)` 内部，所有 DB 操作改用 sync session | `etf_scanner.py` | ~10 行 |
| 3 | `pool_manager.refresh()` 冷却期容错加固：冷却期内返回 stale 数据而非空池 | `pool_manager.py` | ~10 行 |
| 4 | `task_manager.design_worker` 的 150s 超时改为软超时（try-cancel 而非硬抛） | `task_manager.py` | ~15 行 |
| 5 | `asyncio.wait_for` → `asyncio.shield` + 手动计时，超时时主动标记任务失败而非取消协程 | `task_manager.py` | ~10 行 |

### 验证计划

1. 单测池: 增量 + 回归 18/18 ✅
2. `verify_e2e.py --module resilience`: 提交设计 + 策略任务，运行期间持续检查 `/health` 存活率
3. 手动测试: 连续提交 3 个设计 + 3 个策略检查，验证后端不挂
