# ETF Surge 综合优化方案

> 版本: v2.0 | 日期: 2026-07-21
> 审核后修正：EM 源改用 `m:1+t:2` 提高覆盖面、补 `no_proxy`、补 DB 迁移 SQL、补 `onHistorySelect` 类型分发、补 strategy_check `portfolio_type` 读取 bug、补运行中条目守卫
> 基于全链路追踪，覆盖 6 大问题的修复方案

---

## 一、已定位的问题清单

| 编号 | 问题 | 根因 | 优先级 |
|------|------|------|--------|
| **P1** | 设计生成失败："方案生成失败，请稍后重试" | 数据管道间歇性空池：Sina 返回 0 只 ETF → akshare 兜底 timeout=8s 不够 → 0 candidates → 设计失败 | **P0** |
| **P2** | 策略检查白屏 | `DashboardAiTools.vue` 未传 `taskStatus` props → `TaskProgress` 拿到空字符串，三个 `v-if` 条件都不满足 → 渲染空白 | **P0** |
| **P3** | 策略检查超时 | 前端 120s 超时。后端 `task.error` vs `task.error_message` 字段名不匹配，真实错误被吞掉，始终显示 fallback 文案 | **P0** |
| **P3b** | 策略检查不按所选组合执行 | `strategy_check_worker` 读 `task.get("portfolio_type")` 但该值存在 `task.params` 中 → `portfolio_type` 始终为 None，永远检查全场而非所选组合 | **P0** |
| **P4** | 历史记录加载不出来 | `loadHistoryList` 用 `Promise.all(listDesigns + listStrategyChecks)`，任一路失败整个 catch 不显示 | **P1** |
| **P5** | 设计生成完不跳结果页 | `POST /design-async` 返回不含 `design_id`（异步设计），前端 WS 回调和轮询都用 `undefined` 调用 `fetchDesignDetail` → 永远不跳转 | **P1** |
| **P6** | 历史记录无状态 | `list_designs` / `get_design` 不返回 `status`，前端看不出方案成功/失败 | **P2** |

---

## 二、修改方案

### Phase A — 数据管道韧性（修复 P1）

#### A1 — 缓存 key 修正 + TTL 延长

**文件**: `backend/app/fetchers/etf_scanner.py`

```python
# 当前（L136, L142, L160）：
sync_memory_cache.set("all_etfs", merged, CACHE_TTL.get("etf_scanner", 120))
#                         ↑ key 正确      ↑ "etf_scanner" 在 CACHE_TTL 中不存在 → fallback 120s

# 改为：
sync_memory_cache.set("all_etfs", merged, CACHE_TTL["etf_list"])
#                                           ↑ 3600s（1 小时）
```

代码中三处调用全部改 `CACHE_TTL.get("etf_scanner", 120)` → `CACHE_TTL["etf_list"]`。

注意：缓存数据包含最新价/PE/成交量等指标，T=3600s 意味着这些数据最多滞后 1 小时。但候选池筛选主要依赖名称、规模和成交额量级，价格滞后不影响分类和排名。实时报价另有独立缓存（5s TTL）。

#### A2 — 添加 last-good 缓存兜底

**文件**: `backend/app/fetchers/etf_scanner.py`

模块级新增：
```python
_last_good_etfs: list[dict] | None = None
```

每次成功获取后更新：
```python
_last_good_etfs = merged  # 或 result
```

兜底处（L156-157, L164-165）改：
```python
# 当前：
stale = sync_memory_cache.get("all_etfs")
return stale or []

# 改为：
stale = sync_memory_cache.get("all_etfs")
return stale or _last_good_etfs or []
```

#### A3 — 延长 akshare spot timeout

**文件**: `backend/app/fetchers/etf_scanner.py`（L153）

```python
# 当前：
df = run_in_thread(_p, timeout=8)

# 改为：
df = run_in_thread(_p, timeout=25)
```

#### A4 — 启动时预热 ETF 缓存

**文件**: `backend/app/main.py`

在 lifespan 中，`_warmup_market_cache` 之后追加：
```python
async def _warmup_etf_cache():
    try:
        from app.fetchers.etf_scanner import fetch_all_etfs_base
        result = await asyncio.to_thread(fetch_all_etfs_base)
        if result:
            logger.info("ETF 缓存预热完成：%d 只", len(result))
    except Exception:
        logger.warning("ETF 缓存预热失败（不影响启动）")
        
asyncio.create_task(_warmup_etf_cache())
```

#### B1+B2 — 新增 East Money 直连 HTTP 源

**文件**: `backend/app/fetchers/etf_scanner.py`

新增函数 `_fetch_em_etf_list()`：

```python
def _fetch_em_etf_list() -> list[dict] | None:
    """直连东方财富 push2 API 获取全量 ETF 列表（免 akshare，纯 HTTP+JSON）。

    字段映射：f12=代码  f14=名称  f2=最新价  f3=涨跌幅
             f62=换手率  f184=总市值(基金规模)  f66=市盈率  f45=成交量

    使用 m:1+t:2 覆盖沪深两市全部 ETF（~1843 只），免 akshare 封装。
    """
    from ..utils.proxy import no_proxy
    import requests as _req
    headers = {"User-Agent": "Mozilla/5.0"}
    fields = "f12,f14,f2,f3,f62,f184,f66,f45,f168,f20,f21,f115,f116"
    all_items = []
    total = None
    for page in range(1, 20):
        url = (f"http://push2.eastmoney.com/api/qt/clist/get?"
               f"pn={page}&pz=100&po=1&np=1&fs=m:1+t:2&fields={fields}&fid=f3")
        try:
            with no_proxy():
                r = _req.get(url, timeout=5, headers=headers)
            data = r.json()
            diff = data.get("data", {}).get("diff", [])
            if page == 1:
                total = data.get("data", {}).get("total", 0)
            if not diff:
                break
            all_items.extend(diff)
            # 已取够全部，提前跳出
            if total and len(all_items) >= total:
                break
        except Exception:
            break
    if not all_items:
        return None
    return [{
        "symbol": item["f12"],
        "name": item.get("f14", ""),
        "amount": item.get("f62", 0) or 0,
        "fund_scale": item.get("f184", 0) or 0,
        "price": item.get("f2", 0) or 0,
        "change_pct": item.get("f3", 0) or 0,
        "turnover": item.get("f45", 0) or 0,
        "pe": item.get("f66", 0) or 0,
        "pb": item.get("f115", 0) or 0,
    } for item in all_items]
```

在 `fetch_all_etfs_base()` 的 Sina 失败后、akshare spot 之前插入：

```python
# 2.5 East Money 直连 HTTP（新增 Tier）
try:
    em_result = _fetch_em_etf_list()
    if em_result and len(em_result) >= 50:
        logger.info("[etf_scanner] East Money direct HTTP: %d ETFs", len(em_result))
        sync_memory_cache.set("all_etfs", em_result, CACHE_TTL["etf_list"])
        return em_result
except Exception as e:
    logger.warning("[etf_scanner] East Money direct HTTP failed: %s", e)
```

降级链变为：
```
① 内存缓存 → ② Sina (akshare) → ②.5 East Money 直连 HTTP → ③ gtimg → ④ akshare spot (25s)
```

---

### Phase B — 策略检查白屏 + 超时修复（修复 P2, P3）

#### C1 — 补齐 props 传递

**文件**: `frontend/src/views/DashboardAiTools.vue`

```html
<!-- 当前 -->
<StrategyCheckResult
  v-if="activeCoreFeature === 'strategy'"
  :result="strategyResult"
  :loading="checkingStrategy"
  :error="strategyError"
  @close="exitCoreFeature"
/>

<!-- 改为 -->
<StrategyCheckResult
  v-if="activeCoreFeature === 'strategy'"
  :result="strategyResult"
  :loading="checkingStrategy"
  :error="strategyError"
  :task-status="strategyTaskStatus"
  :task-progress="strategyProgress"
  :task-stage="strategyStage"
  @close="exitCoreFeature"
/>
```

同时确保 `strategyTaskStatus` 在 `checkStrategy()` 开始时设为 `'running'`：
```javascript
async function checkStrategy() {
  checkingStrategy.value = true
  strategyTaskStatus.value = 'running'  // 已存在（L359）
  // ...
}
```

#### C2 — 轮询结果中 `task.error` → `task.error_message`

**文件**: `frontend/src/views/DashboardAiTools.vue`

```javascript
// 当前（L384）：
strategyError.value = task.error || '策略检查失败'

// 改为：
strategyError.value = task.error_message || task.error || '策略检查失败'
```

#### C3 — 修复 strategy_check_worker 读取 portfolio_type

**文件**: `backend/app/tasks/strategy_check_worker.py`

```python
# 当前（读取 task 顶层，portfolio_type 实际在 task["params"] 中）：
capital = task.get("capital", 500000)
portfolio_type = task.get("portfolio_type")

# 改为：
params = task.get("params", {})
capital = params.get("capital", 500000)
portfolio_type = params.get("portfolio_type")
```

同样的修复应用到设计生成路径（L333）：
```javascript
// 当前：
designFailed.value = task.error || '方案生成失败，请稍后重试'

// 改为：
designFailed.value = task.error_message || task.error || '方案生成失败，请稍后重试'
```

---

### Phase C — 历史记录加载（修复 P4）

#### D1 — Promise.all 加 catch 隔离

**文件**: `frontend/src/views/DashboardAiTools.vue`

```javascript
// 当前：
const [designRes, checkRes] = await Promise.all([
  portfolioApi.listDesigns(20, 0),
  portfolioApi.listStrategyChecks(20, 0),
])

// 改为：
const [designRes, checkRes] = await Promise.all([
  portfolioApi.listDesigns(20, 0).catch(() => ({ data: [] })),
  portfolioApi.listStrategyChecks(20, 0).catch(() => ({ data: [] })),
])
```

#### D2 — 对 list_strategy_checks 加异常保护

**文件**: `backend/app/routers/portfolio.py`

当前 `list_strategy_checks` 使用 `async with async_session()` 创建新会话，如果 DB 连接失败会报 500（拖垮前端 Promise.all）。改为：

```python
@router.get("/strategy-checks")
async def list_strategy_checks(limit: int = 10, offset: int = 0):
    """列出历史策略检查记录。"""
    try:
        ...
        return [r.to_dict() for r in rows]
    except Exception:
        logger.exception("[strategy_checks] listing failed")
        return []
```

---

### Phase D — 历史记录状态 + 前端链路（修复 P5, P6）

#### E1 — 模型新增 status / error_message 字段

**文件**: `backend/app/models/portfolio_design.py`

```python
# 新增字段
status = Column(String(20), nullable=False, default="completed")
error_message = Column(Text, nullable=True)
```

迁移 SQL（开发环境直接执行）：

```sql
-- 新增 status 和 error_message 字段
ALTER TABLE portfolio_designs ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'completed';
ALTER TABLE portfolio_designs ADD COLUMN error_message TEXT NULL;
```

注意：已有记录自动获得 `status='completed'`（安全假设——旧记录生成时没报错的都视为成功）。

#### E2 — design_worker 保存时设 status

**文件**: `backend/app/tasks/task_manager.py`

```python
# 创建 record 时（L155-159）增加 status 和 error_message
has_error = bool(result.get("error")) or not strategies
record = PortfolioDesign(
    capital=capital,
    risk_profile=params.get("risk_profile", "balanced"),
    strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
    market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
    status="failed" if has_error else "completed",
    error_message=result.get("detail") if not strategies else None,
)
```

#### E3 — 路由返回 status

**文件**: `backend/app/routers/portfolio.py`

`list_designs` 的 `load_only` 中加 `PortfolioDesign.status`，返回对象加 `"status": r.status`。

`get_design` 返回加 `"status": record.status`、`"error_message": record.error_message`。

#### E4 — 前端历史列表状态徽标

**文件**: `frontend/src/components/design/DesignHistory.vue`

在每个 history-item 的名称后面加状态徽标：

```html
<span class="history-status" :class="'status-' + (h.status || 'completed')">
  <!-- 成功 --> <template v-if="h.status === 'completed'">✅ 成功</template>
  <!-- 失败 --> <template v-else-if="h.status === 'failed'">❌ 失败</template>
  <!-- 运行中 --> <template v-else-if="h.status === 'running'">⏳ 运行中</template>
</span>
```

#### E5 — 历史列表合并运行中任务 + onHistorySelect 类型分发

**文件**: `frontend/src/views/DashboardAiTools.vue`

在 `loadHistoryList()` 中，合并 task store 中的 running 设计任务：

```javascript
// loadHistoryList 中合并运行中任务（追加到 designHistoryList 前）
const runningTasks = taskStore.tasks
    .filter(t => t.type === 'design' && t.status === 'running')
    .map(t => ({
        id: null, _type: 'design', status: 'running',
        created_at: new Date(t.createdAt).toISOString(),
        capital: '-',
    }))
```

同步更新 `onHistorySelect`，同时传入 `_type` 和 `status` 以正确分发：

```javascript
// 当前：onHistorySelect(id) 只接收 id，对 check 类型也调 getDesign → 404
// DigiHistory 组件需改为 $emit('select', h.id, h)

// onHistorySelect 改为：
async function onHistorySelect(id, item) {
  // 运行中：不请求后端
  if (item?.status === 'running') {
    toast('该方案仍在生成中，请稍后再试', 'info')
    return
  }
  // 失败：提示错误
  if (item?.status === 'failed') {
    toast('该方案生成失败，无法查看详情', 'warning')
    return
  }
  // check 类型：跳转策略检查记录详情
  if (item?._type === 'check') {
    toast('请前往策略检查功能查看详情', 'info')
    return
  }
  // 正常 design 类型：原逻辑
  try {
    const res = await portfolioApi.getDesign(id)
    // ... 后续不变
  }
}
```

同时更新 `DesignHistory.vue` 的 emit：`@click="$emit('select', h.id)"` → `@click="$emit('select', h.id, h)"`。

#### F1 — WS 回调改用 task store 取 designId

**文件**: `frontend/src/views/DashboardAiTools.vue`

```javascript
// 当前（L305-306）注册回调捕获 taskData.design_id（undefined）
const wsToken = taskStore.registerTaskCompletion(taskData.task_id, async () => {
    const data = await fetchDesignDetail(taskData.design_id)
})

// 改为从 task store 获取
const wsToken = taskStore.registerTaskCompletion(taskData.task_id, async (changes) => {
    const task = taskStore.getTask(taskData.task_id)
    const did = task?.designId || changes?.designId
    if (!did) {
        // fallback: 从 task API 获取
        try {
            const taskRes = await portfolioApi.getTask(taskData.task_id)
            did = taskRes?.data?.result?.design_id
        } catch {}
    }
    if (did) {
        await fetchDesignDetail(did)
        toast('组合方案生成完成！', 'success')
    }
})
```

#### F2 — App.vue WS handler 直接从 msg.design_id 取值

**文件**: `frontend/src/App.vue`

```javascript
// 当前（L183-188 注释说 backend _notify 不带 design_id，但其实带了）
if (msg.status === 'completed') {
    portfolioApi.getTask(taskId).then((res) => {
        const did = res?.data?.design_id  // 路径错误
        ...
    })
}

// 改为：
if (msg.design_id) {
    taskStore.updateTask(taskId, { designId: msg.design_id })
} else if (msg.status === 'completed') {
    // fallback
    portfolioApi.getTask(taskId).then((res) => {
        const did = res?.data?.result?.design_id  // 修正路径
        if (did) taskStore.updateTask(taskId, { designId: did })
    }).catch(() => {})
}
```

#### F3 — 轮询路径同样修复

**文件**: `frontend/src/views/DashboardAiTools.vue`

```javascript
// 当前（L325-330）：
const taskRes = await portfolioApi.getTask(taskData.task_id)
const task = taskRes.data
if (task.status === 'completed') {
    clearInterval(pollTimer)
    await fetchDesignDetail(taskData.design_id)  // undefined
}

// 改为：
const taskRes = await portfolioApi.getTask(taskData.task_id)
const task = taskRes.data
if (task.status === 'completed') {
    clearInterval(pollTimer)
    const did = task?.result?.design_id || taskData.design_id
    if (did) {
        await fetchDesignDetail(did)
        toast('组合方案生成完成！', 'success')
    }
}
```

---

## 三、涉及文件清单

| 文件 | 改动数 | 说明 |
|------|--------|------|
| `backend/app/fetchers/etf_scanner.py` | 6 处 | A1(key)+A2(last-good)+A3(timeout)+B1+B2(EM源) |
| `backend/app/main.py` | 1 处 | A4(ETF预热) |
| `backend/app/models/portfolio_design.py` | 1 处 | E1(字段) |
| `backend/app/routers/portfolio.py` | 2 处 | D2(异常保护)+E3(status返回) |
| `backend/app/tasks/task_manager.py` | 1 处 | E2(save时设status) |
| `backend/app/tasks/strategy_check_worker.py` | 1 处 | C3(params读取修复) |
| `frontend/src/views/DashboardAiTools.vue` | 8 处 | C1(props)+C2(error字段)+D1(Promise隔离)+E5(running合并+onHistorySelect分发)+F1(WS回调)+F3(轮询) |
| `frontend/src/App.vue` | 1 处 | F2(WS handler design_id) |
| `frontend/src/components/design/DesignHistory.vue` | 2 处 | E4(状态徽标)+E5(emit传item) |

---

## 四、实施顺序与估算

```
Phase A — 管道韧性 (15min)     → 解决 P1
Phase B — 白屏+超时 (8min)     → 解决 P2, P3
Phase C — 历史记录加载 (5min)  → 解决 P4
Phase D — 状态+前端链路 (12min) → 解决 P5, P6
```

总计约 **40 分钟**。建议按顺序实施，每个 Phase 完成后跑一次 `verify_e2e.py` 确认核心链路正常。
