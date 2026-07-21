# 全球指数展示无数据 — 根因分析与修复方案

> 生成日期: 2026-07-22 | 版本: v2（Review #1 after self-review）
> 状态: **已修订 — 待二次 Review**
> 范围: 前端 GlobalIndicesStrip + 后端 `get_global_indices()` 全链路

---

## 目录

1. [问题现象](#1-问题现象)
2. [全链路追踪](#2-全链路追踪)
3. [根因分析](#3-根因分析)
4. [修复方案](#4-修复方案)
5. [实施路线图](#5-实施路线图)
6. [验证方案](#6-验证方案)
7. [Risks & Mitigations](#7-risks--mitigations)

---

## 1. 问题现象

Dashboard 顶部「全球主流指数」卡片始终显示「暂无数据，点击刷新获取」，手动点击「刷新」按钮后仍无数据，或偶有数据后再次消失。

## 2. 全链路追踪

### 数据流概览

```
GlobalIndicesStrip.vue                    <-- 前端组件
  └─ fetchIndices()
       └─ marketApi.indicesGlobal()
            └─ GET /api/v1/market/indices/global   <-- 后端路由
                 └─ get_global_indices()            <-- Service 层
                      ├─ _global_index_defs()         -- 从 DB indices 表读取 / 硬编码
                      ├─ fetch_index_realtime()       -- A 股指数 (mootdx → Tencent QQ)
                      └─ _foreign() × 7 symbols       -- 海外指数 (5 级降级)
                           ├─ Tier 1: Sina      (3s, 免费, 国内直连)
                           ├─ Tier 2: Twelve Data (4s, 需 API key, 自动跳过)
                           ├─ Tier 3: Finnhub    (4s, 需 API key, 自动跳过)
                           ├─ Tier 4: Stooq     (4s, 免费)
                           ├─ Tier 5: Yfinance  (4s, 国内可能被墙)
                           └─ Fallback: placeholder (available: False)
```

### 关键文件清单

| 层 | 文件 | 角色 |
|----|------|------|
| Backend Route | `backend/app/routers/market.py:57-59` | `GET /indices/global` → `get_global_indices()` |
| Backend Service | `backend/app/services/market_service.py:120-236` | `get_global_indices()` 主逻辑 |
| Backend Fetcher | `backend/app/fetchers/china_market.py:510-546` | `fetch_sina_global_index()` (Sina 层) |
| Backend Fetcher | `backend/app/fetchers/stooq_fetcher.py:102-140` | `fetch_global_index_realtime()` (Stooq 层) |
| Backend Fetcher | `backend/app/fetchers/yfinance_fetcher.py:56-89` | `fetch_index_realtime()` (Yfinance 层) |
| Backend Model | `backend/app/models/search.py:41-52` | `Index` 表（`indices` 表） |
| Frontend Comp | `frontend/src/components/GlobalIndicesStrip.vue` | 全局指数展示卡片 |
| Frontend Compos | `frontend/src/composables/useDashboardData.js:56-66` | Dashboard 的 globalIndices 状态 |
| Frontend View | `frontend/src/views/Dashboard.vue:174-188` | Dashboard WS 更新处理 |
| E2E Test | `backend/scripts/verify_e2e.py:81-92` | 全球指数端到端检查 |

## 3. 根因分析

共发现 **9 个独立问题**，按影响程度排序。

### P0 — 导致数据完全不显示

#### 根因 #1: GlobalIndicesStrip.vue 没有自动触发首次请求 ★★★ 最高优先级

**位置**: `frontend/src/components/GlobalIndicesStrip.vue`

组件在 `<script setup>` 中没有 `onMounted` 钩子。它只暴露了 `defineExpose({ refresh })`，但父组件 Dashboard.vue 从未调用 `globalIndicesStripRef.value.refresh()`。

**效果**: 用户首次进入 Dashboard，组件加载时 `globalIndices.value = ref({})`，始终为 `{}`。只有手动点击「刷新」按钮才会触发 `fetchIndices()`。

**证据**:
- `GlobalIndicesStrip.vue` 脚本中没有 `import { onMounted } from 'vue'`
- Dashboard.vue 声明了 `globalIndicesStripRef` 但未在 `onMounted` 中使用
- 这**单独一个原因**就足以导致「打开页面永远是空的」现象

#### 根因 #2: `get_global_indices()` 无顶层异常处理 ★★★

**位置**: `backend/app/services/market_service.py:120-236`

整个 `get_global_indices()` 函数没有 `try/except` 包裹。以下任一异常都会导致 HTTP 500：
- Sina 响应格式变更（虽然 `_foreign` 内部有 catch，但非预期错误可能逃逸）
- `asyncio.wait_for` 超时在 Python 3.8+ 中抛出 `TimeoutError`（从 `asyncio` 导入的版本）
- 模块导入失败（`from ..fetchers.china_market import fetch_sina_global_index` 等）

**效果**: 任何意外错误 → 500 响应 → 前端 `catch` 设置 `globalIndices.value = {}` → 显示空。

#### 根因 #3: 缓存机制用 `.update()` 合并而非覆盖，且返回新建 dict ★★☆

**位置**: `backend/app/services/market_service.py:233-236`

```python
_global_indices_cache.update(regions)
_global_indices_cache_ts = time.time()
return regions
```

问题：
1. `_global_indices_cache.update(regions)` 是合并操作：若 `regions` 只有部分 region key，旧 region 数据残留（例如 A 股数据昨天获取的混入今天的港股数据中）。
2. **函数返回 `regions` 而非 `_global_indices_cache`**：当所有数据源失败时，`regions` 为空 `{}`，但 `_global_indices_cache` 还有旧数据。发回给前端的是空 `{}`。
3. 缓存 TTL 内（30s）第二次调用返回的是旧 cache，但新 TTL 到期后的调用返回空数据。

**场景演示**:
1. T0: 首次调用，全量获取成功 → regions = {A股: [数据1, 数据2], 美股: [...]} → cache.update(regions) → return regions ✅
2. T1: 30s 内第二次调用 → 缓存命中 → return _global_indices_cache ✅
3. T2: 30s 后第三次调用，全部数据源超时 → regions = {} → cache.update({}) → return {} ❌

**修正**: 应改为 `_global_indices_cache = dict(regions)` + `return _global_indices_cache`。

### P1 — 导致数据不稳定/偶发空白

#### 根因 #4: 海外指数三级降级链本身可能全部超时 ★★☆

**位置**: `backend/app/services/market_service.py:167-217`

每个海外 Symbol 的 `_foreign()` 内部时序：
| 降级层 | 超时 | 备注 |
|--------|------|------|
| Sina | 4s | 国内实测 0.2s，但非交易时段可能返回空格式 |
| Stooq | 6s | 代码注释承认「SSL 握手慢」 |
| Yfinance | 8s | 中国大陆无代理可能被墙 |

**最坏单 symbol 等待**: 4+6+8 = 18s。7 个 symbol 并行执行，总耗时约 18s。

虽然 `_foreign()` 的 fallback 最终会返回 placeholder（`available: False`），确保 `regions` 不为空，但：
- 18s 的响应时间接近前端 axios 60s timeout 的边缘——若加上 A 股请求时间，整体可能超过 25s
- 用户等待近 20s 才看到 placeholder 数据，体验极差

#### 根因 #5: A 股指数池与 DB region 值可能不匹配 ★☆☆

**位置**: `backend/app/services/market_service.py:150-159`

```python
for sym, name, region in defs:
    if region != "A股":
        continue
```

如果 DB `indices` 表中某条记录的 region 为 `"A"` 而非 `"A股"`，该行会被静默跳过。检查 `sync_indices.py` 确认：它使用硬编码的 `_GLOBAL_INDEX_DEFS`（region 为 "A股"），所以同步产生的行没问题。但：
- 若有手动添加的自定义 index 行，region 可能不匹配
- 非同步产生的 DB 行（如其他脚本插入）可能使用不同 region 名

#### 根因 #6: Dashboard WS 更新与 GlobalIndicesStrip 数据隔离 ★☆☆

**位置**: `frontend/src/views/Dashboard.vue:177-186`

Dashboard 的 WS 回调更新的是 `useDashboardData` 中的 `globalIndices` ref，但 `GlobalIndicesStrip` 维护自己独立的 `globalIndices` ref。WS 推送的实时价格永远不会进入 GlobalIndicesStrip 的渲染数据。

**影响**: WS 连接后，指数价格无法实时更新。但 60s 轮询补救了这个问题，所以仅影响轮询间隔内的实时性。

### P2 — 可观测性与测试

#### 根因 #7: E2E 测试验证不足 ★☆☆

**位置**: `backend/scripts/verify_e2e.py:87-88`

```python
indices = data.get("indices", []) if isinstance(data, dict) else data
check(f"指数数据 {len(indices)} 条", len(indices) > 0)
```

- `data.get("indices", [])` 默认值 `[]` 是错误的——实际返回的是 dict。如果 API 返回空 `{}`，测试失败。
- **不检查 region 内是否有 items，也不检查价格是否有效**。即使所有 region 都只有 placeholder（`available: False`），测试也通过。

#### 根因 #8: 缺少前端组件测试 ★☆☆

`GlobalIndicesStrip.vue` 没有任何 vitest 测试用例。CI 无法捕获「缺少 onMounted 导致不自动请求」这类问题。

#### 根因 #9: 组件 CSS 样式缺失 ★☆☆（仅影响视觉，不影响功能）

**位置**: `frontend/src/components/GlobalIndicesStrip.vue`

组件使用 CSS 类 `indices-scroll`、`index-card-compact`、`indices-empty-compact` 等，但没有任何 `<style>` 标签或全局 CSS 定义这些类。组件功能正常渲染 DOM，但完全无样式。

---

## 4. 修复方案

### Fix #1: GlobalIndicesStrip 添加自动首次请求

**文件**: `frontend/src/components/GlobalIndicesStrip.vue`

**变更**:
1. 在 `import` 中添加 `onMounted`
2. 在 `setup` 中添加 `onMounted(() => { fetchIndices() })`

**代码**:
```javascript
import { ref, computed, onMounted, onUnmounted } from 'vue'

// 在 const timer = ref(null) 之后添加：
onMounted(() => {
  fetchIndices()
})
```

**注意**: 不需要防抖——后端已有 30s TTL 缓存保护。

### Fix #2: 给 `get_global_indices()` 添加顶层异常保护

**文件**: `backend/app/services/market_service.py`

**变更**: 在函数体加 `try/except`，异常时返回空结构并用 `logger.error` + `exc_info=True` 记录。

**代码**:
```python
async def get_global_indices() -> dict[str, list[dict[str, Any]]]:
    global _global_indices_cache, _global_indices_cache_ts
    try:
        import time
        now = time.time()
        if _global_indices_cache and (now - _global_indices_cache_ts) < _GLOBAL_INDICES_TTL:
            return _global_indices_cache

        defs = await _global_index_defs()
        # ... 现有所有逻辑 ...

        _global_indices_cache = _to_json_native(regions)
        _global_indices_cache_ts = time.time()
        return _global_indices_cache
    except asyncio.CancelledError:
        logger.warning("[get_global_indices] 请求被取消")
        return _global_indices_cache if _global_indices_cache else {}
    except Exception as e:
        logger.error(f"[get_global_indices] 获取全球指数异常: {e}", exc_info=True)
        # 降级返回上次缓存（如果有），否则返回空
        return _global_indices_cache if _global_indices_cache else {}
```

### Fix #3: 修复缓存语义 — 全量替换 + 返回 cache

**文件**: `backend/app/services/market_service.py`

**变更**: 将 `update()` 改为全量赋值，函数返回 `_global_indices_cache`。

**修正前后对比**:

| 行 | 当前代码 | 修正后代码 |
|----|----------|-----------|
| 233 | `_global_indices_cache.update(regions)` | `_global_indices_cache = _to_json_native(regions)` |
| 235 | `return regions` | `return _global_indices_cache` |

### Fix #4: 给 `_foreign()` 添加 symbol 级日志

**文件**: `backend/app/services/market_service.py`

**变更**: 在每个 fallback 的 catch 块中添加 debug 日志。

**代码示例**:
```python
# 第1优先：新浪
try:
    d = await asyncio.wait_for(
        loop.run_in_executor(None, functools.partial(sina_index, sym)),
        timeout=4,
    )
    if d and d.get("price") is not None:
        ...
except (asyncio.TimeoutError, Exception) as e:
    logger.debug("[global_indices] Sina %s failed: %s", sym, e)
```

### Fix #5: 新增数据源降级层（Twelve Data + Finnhub）

**背景**: 当前 `_foreign()` 仅 3 层降级（Sina → Stooq → Yfinance），全部免费无 key。在中国网络环境下，Sina
可能空响应、Stooq SSL 慢、Yfinance 被墙——三层同时失效的概率不低。项目中已有多个配置了 API key 的第三方数据源
（Twelve Data / Finnhub / Alpha Vantage），其中两个适合加入全球指数的降级链路。

#### 候选数据源评估

| 数据源 | 已有代码 | 需 API key | 免费额度 | 中国可用 | Symbol 格式 | 评估 |
|--------|----------|-----------|----------|---------|------------|------|
| **Twelve Data** | `twelvedata_fetcher.fetch_realtime()` | ✅ `twelvedata_api_key` | 800 calls/天 | ✅ 直连 | `^GSPC` → `SPX`（需映射） | ✅ **推荐** |
| **Finnhub** | `finnhub_fetcher.fetch_realtime()` | ✅ `finnhub_api_key` | 60 calls/分 | ✅ 直连 | `^GSPC` 直接支持 | ✅ **推荐** |
| Alpha Vantage | `alphavantage_fetcher.fetch_realtime()` | ✅ `alphavantage_api_key` | 25 calls/天 ❌ | ✅ 直连 | `^GSPC` 支持 | ❌ 额度太低 |
| Tencent QQ | `_tencent_realtime()` 内联函数 | ❌ 无需 | 无限制 | ✅ 直连 | 需自定义映射 | ⚠️ 需研究与测试 |
| akshare | 仅 re-export | ❌ 无需 | 无限制 | ✅ 直连 | 需查 API 文档 | ⚠️ 慢且不稳定 |

**结论**: **Twelve Data** 和 **Finnhub** 是性价比最高的新增源——代码已存在、零新增依赖、API key 未配置时自动跳过。

#### Symbol 映射

`_foreign()` 接收到的是 `^` 前缀的标准代码（`^GSPC`, `^IXIC` 等）。不同数据源需要的格式：

| APP 代码 | Sina | Twelve Data | Finnhub | Stooq | Yfinance |
|----------|------|-------------|---------|-------|----------|
| ^GSPC | `gb_$spx` | `SPX` | `^GSPC` | `spx` | `^GSPC` |
| ^IXIC | `gb_$ixic` | `IXIC` | `^IXIC` | `^ixic` | `^IXIC` |
| ^DJI | `gb_$dji` | `DJI` | `^DJI` | `^dji` | `^DJI` |
| ^N225 | `gb_$n225` | `N225` | `^N225` | `^n225` | `^N225` |
| ^HSI | `gb_$hsi` | `HSI` | `^HSI` | `^hsi` | `^HSI` |
| ^HSCE | `gb_$hsce` | `HSCE` | `^HSCE` | `^hsce` | `^HSCE` |
| ^HSTECH | `gb_$hstech` | `HSTECH` | `^HSTECH` | `^hstech` | `^HSTECH` |
| ^KS11 | `gb_$ks11` | `KS11` | `^KS11` | `^ks11` | `^KS11` |

Twelve Data 需要去除 `^` 前缀，其余源复用原始代码。

#### 实现方案

**文件**: `backend/app/services/market_service.py`

**新增 `_TWELVEDATA_INDEX_MAP` 映射表**：
```python
_TWELVEDATA_INDEX_MAP: dict[str, str] = {
    "^GSPC": "SPX", "^IXIC": "IXIC", "^DJI": "DJI",
    "^N225": "N225", "^HSI": "HSI", "^HSCE": "HSCE",
    "^HSTECH": "HSTECH", "^KS11": "KS11",
}
```

**在 `_foreign()` 中添加 Tier 2 (Twelve Data) 和 Tier 3 (Finnhub)**：

```python
async def _foreign(sym: str, name: str, region: str):
    loop = asyncio.get_running_loop()
    import functools

    # ── Tier 1: Sina (3s) ──
    try:
        d = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(sina_index, sym)),
            timeout=3,
        )
        if d and d.get("price") is not None:
            d["name"] = name
            d["region"] = region
            return region, d
    except (asyncio.TimeoutError, Exception):
        pass

    # ── Tier 2: Twelve Data (4s, 需 API key) ──
    from ..fetchers.twelvedata_fetcher import fetch_realtime as td_fetch
    td_sym = _TWELVEDATA_INDEX_MAP.get(sym)
    if td_sym:
        try:
            d = await asyncio.wait_for(
                loop.run_in_executor(None, functools.partial(td_fetch, td_sym)),
                timeout=4,
            )
            if d and d.get("price") is not None:
                d["name"] = name
                d["region"] = region
                d["asset_type"] = "index"
                d["available"] = True
                return region, d
        except (asyncio.TimeoutError, Exception):
            pass

    # ── Tier 3: Finnhub (4s, 需 API key, 直接用 ^ 前缀) ──
    from ..fetchers.finnhub_fetcher import fetch_realtime as fh_fetch
    try:
        d = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(fh_fetch, sym)),
            timeout=4,
        )
        if d and d.get("price") is not None:
            d["name"] = name
            d["region"] = region
            d["asset_type"] = "index"
            d["available"] = True
            return region, d
    except (asyncio.TimeoutError, Exception):
        pass

    # ── Tier 4: Stooq (4s) ──
    try:
        d = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(stooq_index, sym, name, 4)),
            timeout=4,
        )
        if d and d.get("price") is not None:
            d["region"] = region
            return region, d
    except (asyncio.TimeoutError, Exception):
        pass

    # ── Tier 5: Yfinance (4s) ──
    try:
        d = await asyncio.wait_for(
            loop.run_in_executor(None, functools.partial(yf_index, sym)),
            timeout=4,
        )
        if d and d.get("price") is not None:
            d = dict(d)
            d["name"] = name
            d["region"] = region
            d["asset_type"] = "index"
            d["available"] = True
            return region, d
    except (asyncio.TimeoutError, Exception):
        pass

    # ── 全部失败，返回 placeholder ──
    return region, {
        "symbol": sym, "name": name, "region": region,
        "asset_type": "index", "price": None, "change_pct": None,
        "available": False,
    }
```

#### Key 可用性说明

- Twelve Data 和 Finnhub 的 fetcher 内部会在 API key 为空时返回 `None`
- 因此即使 `.env` 中未配置这两个 key，链路会静默跳过 Tier 2/3，继续到 Stooq/Tier 4
- **零风险、零额外异常**

#### 超时对比

| 指标 | 当前 | 修正后 |
|------|------|--------|
| 层数 | 3（Sina+Stooq+Yfinance） | **5**（Sina+TD+Finnhub+Stooq+Yfinance） |
| 最坏单 symbol 等待 | 4+6+8 = 18s | 3+4+4+4+4 = **19s** |
| 数量（7 symbol 并行） | ~18s | ~19s |
| 全部源失效 → placeholder | ✅ 是 | ✅ 是 |
| 需 API key 的源 | 0 | **2**（自动跳过） |

19s 仍然在前端 60s axios timeout 之内，且多两层保护显著降低了「全球指数全空」的概率。

### Fix #6: 统一 Dashboard WS 更新与 GlobalIndicesStrip 数据

**方案选择**: 当前 60s 轮询间隔足够覆盖全球指数的更新频率。WS 实时推送做 Bonus 优化。

**方案 A（荐）**: Dashboard.vue 在 `onMounted` 中调用 `globalIndicesStripRef.value.refresh()`，明确触发 GlobalIndicesStrip 的首次加载。WS 更新同步暂不做。

**代码**:
```javascript
// Dashboard.vue onMounted — 在现有 fetchGlobalIndices() 后添加
if (globalIndicesStripRef.value) {
  globalIndicesStripRef.value.refresh()
}
```

### Fix #7: 增强 E2E 测试

**文件**: `backend/scripts/verify_e2e.py`

**变更**: 将简单 `len(indices) > 0` 改为内容级检查。

**代码**:
```python
if r.status_code == 200:
    data = r.json()
    indices = data.get("indices", {}) if isinstance(data, dict) else {}
    region_count = len(indices)
    total_items = sum(len(items) for items in indices.values())
    items_with_price = sum(
        1 for items in indices.values() for it in items
        if it.get("price") is not None and it.get("available", False)
    )
    check(f"全球指数: {region_count} 个区域, {total_items} 项, {items_with_price} 项有价格",
          region_count > 0 and total_items > 0)
    check("至少 1 个区域有实时价格数据", items_with_price > 0,
          f"当前 {items_with_price} 项有价格")
```

### Fix #8: 添加前端 vitest 测试

**文件**: `frontend/src/test/components/GlobalIndicesStrip.spec.js`（新建）

**测试用例**:
1. 组件挂载后自动调用 `marketApi.indicesGlobal()`（mock axios）
2. API 返回数据后正确展平并渲染指数卡片
3. API 失败时显示空状态「暂无数据」
4. 点击刷新按钮触发新请求并更新数据

### Fix #9: 补充 GlobalIndicesStrip CSS 样式

**文件**: `frontend/src/components/GlobalIndicesStrip.vue` — 添加 `<style scoped>` 块

或者引入全局样式文件。鉴于组件只有一个，推荐 `scoped`。

---

## 5. 实施路线图

### 阶段 A: 核心修复（让数据能显示）- 约 1.5h

| 任务 | 文件 | 描述 | 依赖 |
|------|------|------|------|
| A1 | `GlobalIndicesStrip.vue` | 添加 `onMounted` 自动请求 | 无 |
| A2 | `market_service.py` | 缓存全量替换 + 返回 cache | 无 |
| A3 | `market_service.py` | 顶层 try/except 异常保护 | A2 |
| A4 | `market_service.py` | _foreign symbol 级 debug 日志 | A2 |
| A5 | `market_service.py` | 新增 Twelve Data + Finnhub 降级层 + 映射表 | A2 |

### 阶段 B: 体验优化 - 约 1h

| 任务 | 文件 | 描述 | 依赖 |
|------|------|------|------|
| B1 | `market_service.py` | 缩短其他源超时（Sina 3s, Stooq/Yfinance 4s） | A2 |
| B2 | `Dashboard.vue` + `GlobalIndicesStrip.vue` | Dashboard onMounted 调用 refresh() | A1 |
| B3 | `GlobalIndicesStrip.vue` | 添加 scoped CSS 样式 | 无 |

### 阶段 C: 测试加固 - 约 1h

| 任务 | 文件 | 描述 | 依赖 |
|------|------|------|------|
| C1 | `verify_e2e.py` | 增强 E2E 检查为内容级 | A2 |
| C2 | `GlobalIndicesStrip.spec.js` | 新建 vitest 组件测试 | A1 |

### 实施建议

1. **先做完阶段 A 再提交一次**，确保数据能显示
2. **阶段 B 和 C 可以并行**
3. 每个阶段跑 `verify_e2e.py --smoke` 回归

---

## 6. 验证方案

### 后端验证
```bash
cd backend
# 1. 启动
uvicorn app.main:app --reload

# 2. 手动调 API
curl -s http://localhost:8000/api/v1/market/indices/global | python -m json.tool
# 期望: {"indices": {"A股": [...], "港股": [...], "美股": [...], "日经": [...], "韩国": [...]}}
# 每项有 price, change_pct, available

# 3. 调 E2E
python scripts/verify_e2e.py
# 期望: [PASS] 全球指数: 5 个区域, 13 项, 约 5+ 项有价格
```

### 前端验证
```bash
cd frontend && cmd /c "npm run dev"
# 1. 打开 http://localhost:5173/dashboard
# 2. ✅ 「全球主流指数」卡片自动加载并显示数据
# 3. ✅ 每项有名称、价格、涨跌幅（红色涨/绿色跌）
# 4. ✅ 点击「刷新」按钮重新请求
# 5. 断网测试：确认显示「暂无数据」

# 组件单测
npm test -- GlobalIndicesStrip
# 期望: 全 PASS
```

### 回归验证
```bash
cd backend && python scripts/verify_e2e.py --smoke
# 全 PASS
```

---

## 7. Risks & Mitigations

| Risk | 描述 | Mitigation |
|------|------|------------|
| Sina API 格式变更 | 新浪可能改变 hq.sinajs.cn 输出 → 所有 Sina 层失效 | 已有 Stooq/Yfinance 灾备 + 日志可快速定位 |
| Stooq 中国不可达 | SSL 握手慢 / 被 GFW 影响 | 注释已承认，Yfinance 层兜底 |
| Yfinance 无代理不可用 | 中国大陆直连 Yahoo Finance 不稳定 | 设置 `YFINANCE_PROXY` 环境变量 |
| 缓存竞态 | 并发调用 get_global_indices 时 cache 读写冲突 | return 的是局部 region → 无数据竞争；Fix#3 完全赋值后也无问题 |
| 后端 try/except 隐藏真实错误 | 静默降级让上游不报错但数据不准 | `exc_info=True` 确保日志可查；监控告警应检查 indices 端点的空响应 |
| A 股指数返回空 | mootdx / Tencent QQ 数据不可用 | 海外指数独立获取，不影响显示；A 股指数缺位仅影响 A 股市值 |
| 组件 CSS 缺失 | 无样式渲染但功能正常 | Fix#9 新增 scoped 样式，不影响其他组件 |

---

## 附录 A: 当前缓存代码与修正后对比

### 当前 `market_service.py:229-236`

```python
    # 清洗为 JSON 原生类型
    regions = _to_json_native(regions)
    # 写入缓存（即使部分为空也缓存，避免非交易时段重复采集）
    _global_indices_cache.update(regions)  # ❌ merge → 旧数据残留
    _global_indices_cache_ts = time.time()
    return regions  # ❌ 返回新建 dict → 数据全丢
```

### 修正后（Fix#2 + Fix#3 合并）

```python
    try:
        # ... 数据获取逻辑 ...
        _global_indices_cache = _to_json_native(regions)  # ✅ 全量替换
        _global_indices_cache_ts = time.time()
        return _global_indices_cache  # ✅ 返回缓存
    except asyncio.CancelledError:
        logger.warning("[get_global_indices] 请求被取消")
        return _global_indices_cache if _global_indices_cache else {}
    except Exception as e:
        logger.error(f"[get_global_indices] 获取全球指数异常: {e}", exc_info=True)
        return _global_indices_cache if _global_indices_cache else {}
```

## 附录 B: 前端组件未 mount 的证据

`GlobalIndicesStrip.vue` 的 `<script setup>` 当前内容摘要：

```javascript
import { ref, computed, onUnmounted } from 'vue'    // ← 无 onMounted！
import { marketApi } from '../api'
// ...

const globalIndices = ref({})
// ...

onUnmounted(() => { ... })   // ← 有卸载，无挂载！
defineExpose({ refresh })
```

父组件 Dashboard.vue：

```javascript
const globalIndicesStripRef = ref(null)     // ← 正确声明了 ref
// 但 onMounted 中从未使用！
```

需要改为：

```javascript
// GlobalIndicesStrip.vue
import { ref, computed, onMounted, onUnmounted } from 'vue'

onMounted(() => { fetchIndices() })

// Dashboard.vue — 可选增强
onMounted(async () => {
  await Promise.allSettled([...])
  if (globalIndicesStripRef.value) {
    globalIndicesStripRef.value.refresh()
  }
})
```

---

## 附录 C: 已确认的现有保护机制

- `_call()` 桥接: 统一 sync fetcher → async + timeout + try/except
- `_global_index_defs()`: DB 异常/空表 → 自动降级到硬编码
- `_foreign()` 三级降级: 每层超时独立，失败进入下一层
- `_to_json_native()`: 清洗 numpy 标量，防止缓存命中时 JSON 序列化 500
- `_foreign` fallback 确保即使所有源失败也返回 placeholder：`available: False, price: None`

---

*文档版本: v2 — 已根据自审修订（修复缓存代码误读、增加 CancelledError 处理、增加 CSS 缺失根因、调整实施路线图）*
