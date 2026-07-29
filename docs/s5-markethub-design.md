# S5: MarketDataHub — 数据管道统一方案

> 版本: v3 (R3 COMPLETE) | 2026-07-29
> 关联: `docs/system-diagnosis-and-optimization-plan.md` §12

---

## 1. 问题陈述

当前系统存在 **三条独立的数据管道**，它们在各自层级重复执行相同的数据获取：

```
管道 A (因子计算):  scanner → factor_registry.compute() → _fetch_market_data() → ChinaMarket
管道 B (REST API):   market_service.get_history() → china_market.fetch_kline()
管道 C (技术指标):   compute_chart_data() → china_market.fetch_kline() → compute_all_indicators()
```

**每条管道** 会从 ChinaMarket fetcher 独立拉取同一批 ETF 的 60 天 K 线，耗时因每个 fetcher 内部的网络 I/O 而异。这在 80 只 ETF 的扫描场景中，因子计算管道的 `_fetch_market_data()` 平均耗时 4-16 秒——每轮都会做。

### 1.1 当前测量

| 指标 | 值 |
|------|----|
| ETF 池大小 | ~80 只 |
| 单次 get_pool 调用 | 平均 5.8s (max 10s) |
| 内部 _fetch_market_data() | 4-16s (同步 fetcher 链) |
| 推送图表的 compute_chart_data | 2-4s (独立重拉 K 线) |
| 三个管道总重复 I/O | ~200% overhead |

---

## 2. 当前架构全景

### 2.1 PoolManager 现有接口 (将被迁移到 MarketDataHub)

```
PoolManager
│
├─ refresh() → PoolDiff              # 入口：触发全量刷新
├─ get_pool(layer) → list[dict]      # 1. 候选池
├─ get_by_code(symbol) → dict        # 2. 单只查询
├─ get_factor_matrix() → dict        # 3. 因子矩阵
├─ get_market_regime(market) → str   # 4. 市场状态
├─ get_market_sentiment() → dict     # 5. 市场情绪
├─ get_news() → list[dict]           # 6. 新闻缓存
├─ get_kline(symbol) → dict          # 7. K线缓存 (Phase 14 S5初版)
└─ refresh_kline(symbols) → None     # 8. 增量刷新K线
```

### 2.2 外部消费者分析

| 消费者 | 数据需求 | 当前如何获取 | 是否应走 Hub |
|--------|---------|-------------|-------------|
| `market_router.get_realtime` | 实时行情 | `market_service.get_all_realtime()` | ❌ 实时行情不应缓存 |
| `market_router.get_history` | 历史 K 线 | `market_service.get_history()` | ✅ 可走 Hub 缓存 |
| `market_router.get_indicators` | 技术指标 | `compute_chart_data()` 内部自行 fetch | ✅ 可走 Hub K 线 |
| `portfolio_router.get_allocation` | 组合分配 | `portfolio_service.calculate_allocation()` 调用池数据 | ✅ 已走 Hub |
| `strategy_design.generate_enhanced_design` | 因子分 | `pool_manager.get_pool()` | ✅ 已走 Hub |
| `FactorModelView` 前端页面 | 因子矩阵 | `GET /factors` → `pool_manager.get_factor_matrix()` | ✅ 已走 Hub |

### 2.3 数据流图 (当前)

```
[Scanner] → | symbols  | → [factor_registry.compute()] → [_fetch_market_data()] → ChinaMarket
             | symbol_extra |                             ↘ 返回 data dict
                                                          → factor计算 → factor_scores
                                                          → 合并回 pool items
                                                          
[market_service.get_history()] → [china_market.fetch_kline()] → [indicator compute]
                                    ↑
[compute_chart_data()] ─────────────┘
  (完全独立的链路)
```

---

## 3. 设计方案

### 3.1 核心原则

1. **扫一次，大家读**：扫描器是唯一从外部数据源拉 K 线的角色，写入 Hub 缓存
2. **缓存优先**：所有消费者先从 Hub K 线缓存读取，命中即返回
3. **保持接口向后兼容**：现有调用方不改名，内部重定向到 Hub
4. **逐步替换**：不一次性重构，每次只替换一个消费者的数据源

### 3.2 MarketDataHub 类设计

```python
class MarketDataHub:
    """统一数据总线——全系统唯一的数据入口。
    
    继承 PoolManager 的所有能力，新增 K 线缓存编排和管理。
    """
    
    # ── K 线缓存 (R3: 统一行式格式 + 懒转换) ──
    async def refresh_kline(self, symbols: list[str]) -> None
        """增量刷新：每个 symbol 调一次 fetch_history，Semaphore(5) 控制并发。"""
    def get_kline(self, symbol: str, max_age: int = 300) -> dict | None
        """返回列式格式 (close: [], high: [], ...)：从行式缓存懒转换生成。"""
    def get_kline_rows(self, symbol: str, max_age: int = 300) -> list[dict] | None
        """返回行式格式 [{date, open, high, low, close, volume}] — 直接读缓存。"""
    async def get_kline_async(self, symbol: str) -> dict | None
        """异步获取 K 线列式：先查缓存(懒转换)，未命中时降级到市场 fetcher。"""
    
    # ── refresh() 增强 ──
    # 在 _refresh_impl 中新增 K 线缓存刷新步骤
    # 当前: scan → compute factor → merge
    # 增强后: scan → [refresh_kline(semaphore=5)] → compute factor → merge
    
    # ── 新增接口 ──
    def get_kline_symbols(self) -> list[str]
        """返回缓存中有 K 线的 ETF 代码列表"""
    
    def invalidate_kline(self, symbol: str) -> None
        """使单个 ETF 的 K 线缓存失效"""
```

### 3.3 数据流图 (改造后)

```
[Scanner] → | symbols | → [refresh_kline() → Cache] → [factor_registry.compute(kline_data)] → factor_scores
               ↓
             Hub K-line Cache
               ↓
    [market_service.get_history()] → Hub Cache (miss时直接 fetch)
    [compute_chart_data()] → Hub Cache (miss时直接 fetch)
    [任何 K 线消费者] → Hub Cache
```

---

## 4. 实施步骤

### Step 1: 完善 K 线缓存 (0.5 天) ✅ 已完成 (Phase 14)
**改动点**: `pool_manager.py`
- ✅ 添加 `_kline_cache` 和 `_kline_cache_ts` 字段
- ✅ `refresh_kline(symbols)` 方法
- ✅ `get_kline(symbol, max_age)` 方法
- ✅ TTL 检查与过期自动刷新

**待补全**:
- [ ] `clear_kline(symbol)` 方法：使单只缓存失效
- [ ] `get_kline_symbols()`：列出缓存中 ETF 代码
- [ ] `_kline_cache_lock`：使用 asyncio.Lock 而非 threading
- [ ] 序列化友好：JSON 可序列化格式（当前 Pandas Series 不可序列化）

### Step 2: 在 refresh() 中集成 K 线缓存 (1 天) 🆕
**改动点**: `pool_manager.py` → `_refresh_impl()`

```python
async def _refresh_impl(self) -> PoolDiff:
    # 1. 扫描 (现有)
    items, removed, added = await self._scanner.scan(force=True)
    
    # 2. K 线缓存刷新 (新增)
    symbols = [item["symbol"] for item in items]
    await self.refresh_kline(symbols)
    
    # 3. 因子计算 (已有 commercial_data 参数)
    market_data = self._kline_cache  # 从缓存读
    factor_scores = await self.factor_registry.compute(
        symbols, 
        symbol_extra=self._build_symbol_extra(symbols),
        market_data=market_data,  # 关键修改：传入缓存数据
    )
    # ... 后续不变
```

**风险**:
- `factor_registry.compute()` 的 `market_data` 参数已在 Phase 15 添加支持，需要验证数据格式兼容
- 需要处理 K 线数据格式：factor_registry 期望的是 `{symbol: {"close": [...], "high": [...], ...}}` 
- `refresh_kline()` 内部调用 `factor_registry._fetch_market_data()` → **循环依赖**！需要修改
  - 解法：`refresh_kline()` 直接调用 `china_market.fetch_kline()`，绕过 factor_registry

### Step 3: 重写 refresh_kline()，消除循环依赖 (0.5 天) 🆕
**当前**: `refresh_kline()` 调用 `factor_registry._fetch_market_data()`
**问题**: Step 2 中 `_refresh_impl` 要调 `refresh_kline`，而 `refresh_kline` 又调 `_fetch_market_data`，存循环依赖

**新实现 (R3: 单缓存 + 并发控制)**:
```python
async def refresh_kline(self, symbols: list[str]) -> None:
    """直接调用 fetch_history，Semaphore(5) 控制并发。存储行式格式。"""
    from ..fetchers.china_market import fetch_history
    from ..core.async_utils import run_sync
    
    sem = asyncio.Semaphore(5)  # R3: 并发控制
    
    async def _fetch_one(sym: str) -> tuple[str, list[dict] | None]:
        async with sem:
            rows = await run_sync(fetch_history, sym, "A", "daily", timeout=20)
            return sym, rows
    
    tasks = [_fetch_one(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    updated = {}
    for sym, rows in results:
        if isinstance(rows, list) and rows:
            updated[sym] = rows
    
    if updated:
        self._kline_cache_rows.update(updated)  # 统一存行式格式
        self._kline_cache_ts = time.time()
        self._kline_cache_lock = asyncio.Lock()
```

**数据格式**: 行式 `{symbol: [{date, open, high, low, close, volume}, ...]}`

**新增**: `china_market.fetch_kline_batch(symbols) → dict[str, dict]` — 见 §8.1 接口契约

### Step 4: factor_registry.compute() 接收外部 K 线 (0.5 天) ✅ 已完成 (Phase 15)
- ✅ `compute(symbols, symbol_extra, market_data)` 现已支持外部数据参数
- ✅ 当 `market_data` 非 None 时，跳过 `_fetch_market_data()` 内部调用
- ⚠️ **验证点**：`market_data` 的数据格式需要与 `_fetch_market_data()` 输出一致

### Step 5: market_service.get_history() 接入 Hub 缓存 (1 天) 🆕
```python
async def get_history(symbol, ...):
    hub = get_pool_manager()  # 全局 PoolManager 实例
    
    # 1. 先查 Hub 缓存
    cached = hub.get_kline(symbol)
    if cached:
        return cached.get("lines", [])
    
    # 2. 缓存未命中，降级到直接 fetch
    lines = await fetch_kline_direct(symbol)  # 当前逻辑
    return lines
```

**注意**: K 线缓存 60-300s，对于历史数据来说足够。用户点击图表时优先查缓存的 K 线数据，减少等待。

### Step 6: compute_chart_data() 接入 Hub K 线 (0.5 天) 🆕
`market_router.get_indicators()` 调用 `compute_chart_data()` 时，内部会调 `market_service.get_history()` → 通过 Step 5 接入 Hub。

不需要额外改动，只要 Step 5 完成即可。

### Step 7: compute_all_indicators() 复用 factor_registry 结果 (0.5 天)
当前 `compute_all_indicators()` 和 `compute_chart_data()` 做了大量相同的计算（RSI, MACD, KDJ, Bollinger）。它们的输出应该在 factor_registry 计算因子时已经算过了。

**方案**:
```python
def compute_all_indicators(df, factor_scores=None):
    # 如果提供了 factor_scores，先查其中是否已有 RSI/MACD/KDJ
    if factor_scores:
        rsi = factor_scores.get("rsi_14d")  # 如果因子注册表中有
        if rsi is not None:
            # 复用因子计算的结果
            ...
```

**风险**: factor_registry 可能不全包含 indicators 需要的所有指标。这个步骤可以推迟，先做其他步骤。

### Step 8: 命名迁移 PoolManager → MarketDataHub (0.5 天)
**方案**: 
1. 创建 `MarketDataHub` 别名类，继承 `PoolManager`
2. 所有内部引用保留 `PoolManager`（减少 diff）
3. 公开接口导出为 `MarketDataHub`

```python
# app/services/market_data_hub.py
from .pool_manager import PoolManager as _PoolManager

class MarketDataHub(_PoolManager):
    """统一数据入口。继承 PoolManager 所有能力，新增 K 线编排。"""
    pass

# 全局实例
hub = MarketDataHub()
```

后续逐步将所有 `pool_manager` 引用替换为 `market_data_hub`（接口不变）。

### Step 9: 清理废弃代码 (0.3 天)
- [ ] 删除 `factor_registry._fetch_market_data()` 私有方法
- [ ] 清理 `factor_registry` 中 `kline_cache` 相关字段（移入 Hub）
- [ ] 取消 `indicator` 中的重复指标计算

---

## 5. 接口变更管理

| 接口 | 变更类型 | 当前使用者 | 向后兼容 |
|------|---------|-----------|---------|
| `PoolManager.refresh()` | 内部增强 | `main.py` lifespan, task轮询 | ✅ 签名不变 |
| `PoolManager.get_pool()` | 不变 | strategy_design, routers | ✅ 不变 |
| `factor_registry.compute()` | 参数已加 | pool_manager | ✅ 可选参数 |
| `market_service.get_history()` | 内部增强 | market_router | ✅ 对外不变 |
| `compute_chart_data()` | 通过 Hub 间接 | market_router | ✅ 对外不变 |
| `PoolManager.refresh_kline()` | ✅ 已有 | 新增 consumers | ✅ 新接口 |
| `PoolManager.get_kline()` | ✅ 已有 | 新增 consumers | ✅ 新接口 |

**无破坏性变更**。所有外部 API 签名不变，内部数据源切换。

---

## 6. 测试计划

| 测试场景 | 覆盖内容 | 测试层级 |
|---------|---------|---------|
| K 线缓存读写 | save/load/expiry/clear | 单元 (已存在 11 个) |
| refresh_kline 集成 | 扫描后自动填充缓存 | 单元 (新) |
| factor_registry 外部数据 | market_data 参数 | 集成 (已有) |
| get_history Hub 路由 | 缓存命中/未命中/降级 | 集成 (新) |
| 端到端数据一致性 | 相同 ETF 从三条管道读 | E2E (verify_e2e.py) |

---

## 7. 实施顺序 & 依赖关系

```
Step 1 (0.5d, ✅ 完成) ← 无前驱
    ↓
Step 2 (1.0d, 🆕) ← 依赖于 Step 1
    ↓
Step 3 (0.5d, 🆕) ← 无前驱（与 Step 2 合并在同一轮）
    ↓
Step 4 (0.5d, ✅ 完成) ← 无前驱
    ↓
Step 5 (1.0d, 🆕) ← 依赖于 Step 2 (需要 cache 到位)
    ↓
Step 6 (0.5d, 🆕) ← 依赖于 Step 5
    ↓
Step 7 (0.5d, optional) ← 可独立
    ↓
Step 8 (0.5d, optional) ← 可以在任何时间点
    ↓
Step 9 (0.3d, optional) ← 依赖 Step 4 确认 + Step 7,8 完成

总计: ~3.8 天 (14-19) 核心路径
      可并行: Step 8 ↔ Step 9 ↔ Step 7
```

---

## 8. 关键数据格式规范

### 8.1 接口契约：fetch_kline_batch

```python
async def fetch_kline_batch(
    symbols: list[str],
    days: int = 60,
    period: str = "daily",
) -> dict[str, dict[str, Any]]:
    """批量获取 K 线数据，返回列式格式（与 compute() 兼容）。

    Args:
        symbols: ETF 代码列表。
        days: 历史数据天数（默认 60）。
        period: K 线周期（默认 daily）。

    Returns:
        {
            "510050": {
                "close": [3.456, 3.467, ...],   # 60 个收盘价
                "high": [3.470, 3.481, ...],
                "low": [3.440, 3.451, ...],
                "volume": [12345678, 9876543, ...],
                "change_pct": [0.32, -0.15, ...],
                "total_mv": 100000000000.0,       # 最新规模
                "float_mv": 80000000000.0,
            },
            ...
        }
    """
```

### 8.2 格式转换函数

```python
def _rows_to_columns(
    rows: list[dict], 
    symbol: str, 
    days: int = 60,
    total_mv: float | None = None,
) -> dict[str, Any]:
    """将行式 K 线数据转为列式。

    Input:  [{date: "2026-01-01", open: 3.4, high: 3.5, low: 3.3, close: 3.45, volume: 1e7}, ...]
    Output: {"close": [3.45, ...], "high": [3.5, ...], "low": [3.3, ...], "volume": [1e7, ...],
             "change_pct": [0.5, -0.2, ...], "total_mv": 1e11, "float_mv": 8e10}
    """
    closes = [r.get("close", r.get("收盘", 0)) for r in rows[-days:]]
    highs  = [max(r.get("close", 0), r.get("high", r.get("最高", 0))) for r in rows[-days:]]
    lows   = [min(r.get("close", 0), r.get("low", r.get("最低", 0))) for r in rows[-days:]]
    vols   = [r.get("volume", r.get("成交量", 0)) for r in rows[-days:]]
    
    change_pct = []
    for i in range(1, len(closes)):
        if closes[i-1]:
            change_pct.append(round((closes[i] - closes[i-1]) / closes[i-1] * 100, 2))
        else:
            change_pct.append(0.0)
    change_pct = [0.0] + change_pct  # 第一天无变化
    
    return {
        "close": closes[-days:],
        "high": highs[-days:],
        "low": lows[-days:],
        "volume": vols[-days:],
        "change_pct": change_pct[-days:],
        "total_mv": total_mv or 100e9,
        "float_mv": (total_mv or 100e9) * 0.8,
    }
```

### 8.3 单缓存策略 (R3 修订)

**改为统一存储行式格式，get_kline() 时懒转换。** 这是 R3 审查后对 §8.3 的修订。

**缓存格式**:
```python
# 唯一缓存：行式（与 fetch_history() 输出格式一致）
_kline_cache_rows: dict[str, list[dict]] = {
    "510050": [
        {"date": "2026-07-01", "open": 3.40, "high": 3.50, "low": 3.30, "close": 3.45, "volume": 12345678},
        ...
    ],
    ...
}

# 无独立列式缓存——get_kline() 在返回前调用 _rows_to_columns() 做懒转换
# 无独立锁——统一用 self._kline_cache_lock (asyncio.Lock)
```

**get_kline() 实现**:
```python
def get_kline(self, symbol: str, max_age: int = 300) -> dict | None:
    rows = self.get_kline_rows(symbol, max_age)
    if rows is None:
        return None
    return _rows_to_columns(rows, symbol)

def get_kline_rows(self, symbol: str, max_age: int = 300) -> list[dict] | None:
    import time
    async with self._kline_cache_lock:
        cache = self._kline_cache_rows.get(symbol)
        if cache and (time.time() - self._kline_cache_ts) < max_age:
            return cache
        return None
```

**受益**:
- 一致性自动保证（只有一个源）
- 内存减半
- 不需要锁同步（单锁保护单缓存）
- 代价：每次 compute() 调用的 0.01s 转换延迟，可忽略


## 8.4 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| K 线格式不一致 (`_fetch_market_data` vs `fetch_kline`) | 中 | 高 | Step 2 前后各做一条格式断言 |
| `refresh_kline` 耗时导致 `refresh()` 超时 | 中 | 高 | K 线刷新与因子计算并行（gather） |
| Step 5 缓存命中率过低（用户总是查看冷门 ETF） | 低 | 中 | 缓存未命中时降级到 direct fetch |
| Step 3 的 `fetch_kline_batch` 新增的网络调用对现有 fetcher 造成竞态 | 低 | 高 | 用 asyncio 信号量限制并发 (如 Semaphore(5)) |

---

## 9. Review Checklist

- [ ] 数据流图是否准确反映了所有数据消费者？
- [ ] K 线缓存格式是否能被 `compute()` 消费？
  - `_fetch_market_data()` 返回列式；`fetch_history()` 返回行式
  - **已解决**: 存行式缓存，get_kline() 懒转换
- [x] `refresh_kline()` 调用链路是否消除了循环依赖？
  - **已解决**: `refresh_kline` → 直接 `fetch_history` + `Semaphore(5)`，不经过 factor_registry
- [ ] Step 5 中 `get_history()` 的降级路径是否正确实现了 fallback？
- [ ] get_kline 缓存是否与 get_history 的格式统一？
  - **已解决**: 统一行式缓存 + get_kline 懒转换
- [x] `market_trends.py` 是否被纳入 Hub 消费？
  - **R3 发现**: `market_trends.py:352` 直接调 `fetch_history()`，需在 Step 5 改为 `hub.get_kline_rows()`
- [ ] 并发控制(Semaphore)是否加在了正确的位置？
- [ ] 测试是否覆盖了缓存未命中场景？
- [ ] 命名迁移 (Step 8) 是否应该有专用的 import 别名以避免破坏现有引入？
- [ ] Rollback 策略（§11）是否在实施前确认？

## 10. Rollback 策略

> R3 新增。保证每步实施不会破坏生产环境。

### 10.1 Feature Flag

在 `app/config.py` 添加：
```python
# S5: Hub K 线缓存开关。出问题时关掉，回退到旧路径。
USE_HUB_CACHE: bool = os.getenv("USE_HUB_CACHE", "true").lower() == "true"
```

### 10.2 分步回退协议

| 步骤 | Flag 值 | 回退动作 | 影响范围 |
|------|---------|---------|---------|
| Step 1-4 (K 线缓存) | `USE_HUB_KLINE_CACHE` | 将 `_kline_cache_rows` 设为 None | 因子计算从 Hub 退回 _fetch_market_data() |
| Step 5 (get_history) | `USE_HUB_HISTORY` | `get_history()` 跳过 Hub 缓存 | market_service 走旧路径 |
| Step 6 (compute_chart) | `USE_HUB_KLINE` | compute_chart_data 走旧的 `get_history()` → 不经过 Hub | 技术指标图表 |
| Step 7 (指标复用) | `REUSE_FACTOR_INDICATORS` | compute_all_indicators 独立计算 | 零影响 |

### 10.3 紧急回退

如果某步实施后在 5 分钟内出现数据异常：
1. 设置环境变量：`$env:USE_HUB_CACHE = "false"`
2. 重启后端：`restart.bat`
3. 确认旧路径恢复后，再排查原因

### 10.4 灰度策略 (Optional)

先对特定 symbol 启用 Hub 缓存，验证 15 分钟后再全量开启：
```python
# 灰度名单
_grayscale_symbols: set[str] = {"510050", "510300", "159915"}

def _should_use_hub(symbol: str) -> bool:
    if not USE_HUB_CACHE:
        return False
    if os.getenv("HUB_GRAYSCALE") and symbol not in _grayscale_symbols:
        return False
    return True
```


## 11. Review Record

| 轮次 | 审核人 | 日期 | 发现 | 状态 |
|------|--------|------|------|------|
| R1 | 自审 | 2026-07-29 | refresh_kline 使用 _fetch_market_data（私有方法外部调用） | 已确认，需 Step 3 修复 |
| R1 | 自审 | 2026-07-29 | refresh_kline → _fetch_market_data 导致循环引用（_refresh_impl 要调 refresh_kline，再调 _fetch_market_data） | 已确认，需要新建 china_market.fetch_kline_batch 接口 |
| R1 | 自审 | 2026-07-29 | 未定义 china_market.fetch_kline_batch 的接口契约 | 待补充 |
| R2 | 自审 | 2026-07-29 | `_fetch_market_data()` 与 `fetch_history()` 数据格式完全不同（列式 vs 行式） | 需要新增格式转换层 |
| R2 | 自审 | 2026-07-29 | `fetch_history()` 有完整多源降级，但 `_fetch_market_data()` 只用 Sina+Akshare | 缓存应基于 fetch_history 的降级链 |
| R2 | 自审 | 2026-07-29 | get_kline 缓存列式格式，但 get_history 消费行式格式 → 不兼容 | 需要双格式支持或加适配层 |
| R2 | 自审 | 2026-07-29 | china_market.py 无 `fetch_kline_batch` 函数，需新增 | 待补充接口契约 |
| R3 | 自审 | 2026-07-29 | `market_trends.py:352` 直接调 `china_market.fetch_history()` — 绕过 Hub 管道 | 漏掉了 K 线消费者 |
| R3 | 自审 | 2026-07-29 | `fetch_kline_batch` 无并发控制，80 只串行会超时 | 需加 asyncio.Semaphore(5) |
| R3 | 自审 | 2026-07-29 | 双缓存没有统一锁：`_kline_cache` 和 `_kline_cache_rows` 需要同一把 asyncio.Lock | 需要加锁 |
| R3 | 自审 | 2026-07-29 | `compute_chart_data` 重复计算因子阶段已算过的 KDJ/RSI（Step 7 未完成） | 低优先级优化 |
| R3 | 自审 | 2026-07-29 | 设计文档无回滚策略：如果某步实施后数据异常，如何回退？ | 需要 Session 6 补充：版本切换开关 |
| R3 | 自审 | 2026-07-29 | **建议**：双缓存过于复杂（维护成本高），改为统一存行式格式，get_kline 时懒转换 | 简化方案 |
