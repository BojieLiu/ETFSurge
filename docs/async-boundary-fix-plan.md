# 异步边界修复方案（最终版）

> 修订: 2026-07-26
> 关联问题: Event loop 阻塞导致服务挂死（`docs/systematic-quality-review.md` Issue #1）
> 范围限定: **仅处理事件循环阻塞问题**。其他 5 个质量问题见 `docs/systematic-quality-review.md`。

---

## 1. 根因定位

### 1.1 审计结果

对 `backend/app/` 下所有 Python 文件的 AST 扫描，识别出以下在 `async def` 函数中直接调用同步 I/O 的违规点：

| # | 文件 | 行号 | async def | 阻塞调用 | 状态 |
|---|------|------|-----------|----------|------|
| **1** | `factors/factor_registry.py` | 840-846 | `_fetch_market_data` | `urllib.request.urlopen()` | **🔴 线上活跃** |
| 2 | `services/macro_state.py` | 102 | `_fetch_pmi_trend` | `ak.macro_china_pmi()` | 🟡 死代码 |
| 3 | `services/macro_state.py` | 143 | `_fetch_rate_env` | `ak.bond_china_yield()` | 🟡 死代码 |

除以上 3 处外，项目中所有其他的阻塞 I/O 调用（`china_market.py`、`sentiment_fetcher.py`、`sector_fetcher.py`、`etf_scanner.py`、`news_fetcher.py`、各外部数据 fetcher）都在同步函数中，且均通过 `run_sync()` / `run_sync_long()` 线程池调用，不阻塞事件循环。

### 1.2 关键违规点分析

```python
# factor_registry.py:774
async def _fetch_market_data(self, symbols, ...):
    # ... K线数据获取部分（已在 commit 2be9ccb 修复为 asyncio.to_thread）
    
    # line 839-866: 批量获取 IOPV 数据 ← 遗漏的修复
    import urllib.request
    url = f"http://hq.sinajs.cn/list={','.join(sina_list)}"
    req = urllib.request.Request(url, headers={...})
    resp = urllib.request.urlopen(req, timeout=8)    # ← 同步阻塞！
    raw = resp.read().decode("gbk")                    # ← 同步阻塞！
```

**影响路径：**

```
design_pipeline()
  → generate_enhanced_design()
    → pool_manager.refresh() / factor_registry.compute()
      → _fetch_market_data() [async]
        → fetch_one() [已修复, 走 asyncio.to_thread]
        → urllib.request.urlopen(req) [❗ 直接阻塞事件循环, 8秒]
```

或：

```
strategy_check()
  → factor_registry.compute(symbols)
    → await self._fetch_market_data(symbols) [async]
      → urllib.request.urlopen(req) [❗ 直接阻塞事件循环, 8秒]
```

### 1.3 历史回溯：为什么改了多轮仍没根治

| 修复轮次 | commit | 修复了 | 遗漏了 |
|----------|--------|--------|--------|
| Phase 0 原始修复 | `d478f12` | 添加了 `run_sync()`/`run_sync_long()` 工具函数 | 未应用于 `factor_registry.py` |
| Phase 0.5 管道韧性 | `70a99f1` | ETF 缓存 TTL + EM 直连 + timeout 延长 | 未触及 `_fetch_market_data` 内部 |
| **Phase 0.9** | **`2be9ccb`** | `fetch_one()` 的 `fetch_history` 改用 `asyncio.to_thread()` + Semaphore(8)；线程池统一 32→64 workers | **同函数的 Sina IOPV 批量获取（后 40 行）被漏过** |

**根因**：Sina IOPV 部分（`factor_registry.py:839-866`）与 `fetch_one` 之间隔了 40 多行，没有相同的 `async with sem` 模式，被当成"事后处理"而不是"外部队列获取"，在代码审查中被遗漏。

**教训**：缺少系统性审计工具保证全部覆盖。

---

## 2. 修复方案

### 2.1 🔴 P0 — 立即修复（必须现在改）

#### 修复 1: `factor_registry.py:839-866` Sina IOPV 批量获取

将同步 `urllib.request.urlopen()` 替换为通过线程池的异步调用：

```python
# 改动前 (factor_registry.py:839-866)
try:
    import urllib.request
    ...
    resp = urllib.request.urlopen(req, timeout=8)  # BLOCKING
    raw = resp.read().decode("gbk")
    ...
except Exception as e:
    logger.warning("[factor] batch NAV fetch failed: ...", e)

# 改动后
try:
    import urllib.request
    from ..core.async_utils import run_sync
    ...
    # 将全部同步I/O提取为同步函数，通过run_sync调用
    async def _fetch_sina_quotes(sina_list: list[str]) -> dict:
        def _sync_fetch():
            import urllib.request
            url = f"http://hq.sinajs.cn/list={','.join(sina_list)}"
            req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn"})
            resp = urllib.request.urlopen(req, timeout=8)
            return resp.read().decode("gbk")
        
        raw = await run_sync(_sync_fetch, timeout=10)
        # ... 解析逻辑 ...
        return parsed_data
    
    iopv_data = await _fetch_sina_quotes(sina_list)
    # ... 合并到 data ...
except Exception as e:
    logger.warning("[factor] batch NAV fetch failed: ...", e)
```

#### 修复 2: 设计管线的并发限流

限制 `design_pipeline` 同一时间只能有一个任务运行，防止多个任务叠加导致的线程池耗尽：

```python
# task_manager.py 或 portfolio.py router 中
_design_semaphore = asyncio.Semaphore(1)

async def design_worker(mgr, task_id):
    async with _design_semaphore:
        await design_pipeline(mgr, task_id)
```

### 2.2 🟡 P1 — 死代码修复

#### 修复 3: `macro_state.py` 的异步函数

两个死代码函数 `_fetch_pmi_trend()` 和 `_fetch_rate_env()` 使用 `ak.` 的同步调用。虽然当前未被调用，但以后启用时会阻塞事件循环。修复方式：

```python
# macro_state.py:94-126
async def _fetch_pmi_trend() -> dict[str, Any]:
    from ..core.async_utils import run_sync
    import akshare as ak
    try:
        df = await run_sync(ak.macro_china_pmi, timeout=30)
        # ... 后续处理 ...
    except Exception as e:
        return {}
```

### 2.3 🟢 P2 — 预防性措施

#### 修复 4: CI 审计脚本 — 禁止 `async def` 中包含同步阻塞调用

创建 `scripts/audit_async_blocking.py`，实现本文档 [1.1 节](#11-审计结果) 所用的 AST 扫描逻辑。脚本扫描 `backend/app/` 下所有 `.py` 文件，检查 `async def` 函数体内的阻塞调用，发现违规则 `sys.exit(1)`。

```bash
# 运行方式
python scripts/audit_async_blocking.py
# 返回 0 = 无违规; 返回 1 = 发现违规
```

集成到 `.githooks/pre-commit` 中，在 Python 文件变更时自动运行。

#### 修复 5: 线程池健康监控增强

`async_utils.py` 已有 `get_thread_pool_stats()` 和队列深度 WARNING 日志。增加：
- 当 `run_sync` 队列深度 > 16 时，提升日志级别为 ERROR
- 新增 `/api/v1/admin/thread-pool` 接口（在 `admin.py` router 中）返回实时统计

#### 修复 6: `run_sync` 默认超时

当前的 `run_sync()` 默认超时为 8 秒，对批量 Sina IOPV 获取可能不足。修复 1 中将调用设置为 `run_sync(_sync_fetch, timeout=10)` 以匹配原有 `urlopen(timeout=8)`。

#### 修复 7: 单测增强 — 现有边界测试补全 Sina IOPV 覆盖

在现有 `tests/test_async_boundaries.py` 中增强：
- `test_fetch_market_data_does_not_block_event_loop`：当前只 mock 了 `fetch_history` 路径，需要**额外 mock 覆盖 Sina IOPV 路径**，测试 heartbeat 验证事件循环未被阻塞
- `test_design_task_does_not_block_event_loop`：新增集成测试（详见 §4.3）

#### 修复 8: 文档 — 开发约定

在 `AGENTS.md` 中已有的 async def 非阻塞警告旁，追加：

> **新增 `async def` 函数时必须遵守的规则：**
> 1. 函数体内不允许出现 `urllib.request.*`、`requests.*`、`ak.*` 等同步 I/O 调用
> 2. 所有同步 I/O 必须通过 `await run_sync(func, *args)` 或 `asyncio.to_thread()` 包装
> 3. 如果新增外部 HTTP/API 调用，优先使用 `await run_sync()`（统一线程池管理）
> 4. 提交前运行 `python scripts/audit_async_blocking.py` 检查违规
> 5. 如果函数必须同时使用 `await` 和同步 I/O，必须将同步 I/O 提取到内层 `def` 中

---

## 3. 修复执行计划

| 步骤 | 内容 | 文件 | 优先级 | 预估工时 |
|------|------|------|:------:|:--------:|
| 1 | **Sina IOPV `urllib.request.urlopen` → `await run_sync()`** | `factor_registry.py` | **P0** | 0.5h |
| 2 | `macro_state.py` 死代码修复 | `macro_state.py` | **P1** | 0.5h |
| 3 | 设计管线并发限流（Semaphore 1） | `task_manager.py` / `portfolio.py` | **P1** | 0.25h |
| 4 | 创建 CI 审计脚本 `scripts/audit_async_blocking.py` | 新建文件 | P2 | 0.5h |
| 5 | 增强现有异步边界单测（补 Sina IOPV mock + 集成测试） | `tests/test_async_boundaries.py` | P2 | 0.5h |
| 6 | 线程池深度监控增强（ERROR 级别 + admin API） | `async_utils.py`, `admin.py` | P2 | 0.25h |
| 7 | 更新 AGENTS.md 开发约定 | `AGENTS.md` | P2 | 0.25h |
| 8 | 集成审计脚本到 pre-commit 门禁 | `.githooks/pre-commit` | P2 | 0.25h |
| 9 | 端到端验证：触发设计+策略检查验证不阻塞 | 手动 / `verify_e2e.py` | P0 | 0.5h |

**总计核心（P0+P1）：约 1.25 小时**
**总计完整（含 P2）：约 3.5 小时**

> **与其他文档的协作**：步骤 3（并发限流）与 `systematic-quality-review.md` §8 的 P1-7 相同。步骤 4（CI 审计）与 `systematic-quality-review.md` §8 的 P2-14 相同。两份文档对齐后实施。

---

## 4. 回归验证

### 4.1 修复前复现

```bash
# 启动后端
cd backend && python -m uvicorn app.main:app --reload

# 触发设计任务
curl -X POST http://localhost:8000/api/v1/portfolio/design-async \
  -H "Content-Type: application/json" -d '{"capital": 500000}'

# 立即查询健康检查（应超时挂死）
curl http://localhost:8000/health  # ← 超时
```

### 4.2 修复后验证

同一步骤，健康检查应在 1 秒内返回 `{"status":"ok"}`，设计任务应在 90 秒内正常完成。

### 4.3 自动化验证

```python
# tests/test_async_boundaries.py (新增)
@pytest.mark.asyncio
async def test_design_task_does_not_block_event_loop():
    """触发设计任务后，立即请求 health 应正常响应。"""
    from app.main import app
    from httpx import AsyncClient, ASGITransport
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 触发设计任务（mock 所有外部 I/O 以避免真实网络调用）
        r = await client.post("/api/v1/portfolio/design-async", json={"capital": 500000})
        assert r.status_code == 202
        
        # 2. 立即请求 health
        r2 = await client.get("/health")
        assert r2.status_code == 200
        assert r2.json()["status"] == "ok"
```

---

## 5. 关键要点总结

1. **只有一处线上活跃的阻塞**：`factor_registry.py:845` 的 `urllib.request.urlopen()`，这是唯一的 P0 修复
2. **之前修复失败的原因**：commit 2be9ccb 修复了同函数的 `fetch_one` 但遗漏了后段 Sina IOPV 获取
3. **同步函数中的阻塞调用安全**：通过 `run_sync()` 调用的同步 I/O 不阻塞事件循环——本次审计确认所有其他位置均安全
4. **长期预防**：CI 门禁 + 单元测试 + 开发约定，三重保障防止回归
