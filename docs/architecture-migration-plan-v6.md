# v6 Architecture Migration Plan

> 生成日期: 2026-07-31 | 版本: v6.0-草案
> 基于 `docs/v5_diagnostic_and_optimization_plan.md` Section 16+19

---

## 一、数据管道统一 (pool_manager → MarketDataHub)

### 1.1 当前状态分析

**现状**: 两套管道并存——`pool_manager.py`（主入口）和 `market_data_hub.py`（别名）。`market_data_hub.py` 仅一行 `MarketDataHub = PoolManager`，未完成真正迁移。

**PoolManager API 表面**（25 个方法）：

| 类别 | 方法 | 用途 | 调用方 |
|------|------|------|--------|
| 初始化/刷新 | `__init__`, `refresh()`, `_refresh_impl()` | 全市场数据加载 | strategy_design.py |
| 池管理 | `get_pool()`, `get_by_code()`, `set_opportunistic_signals()` | ETF 池访问 | strategy_design, admin |
| K线数据 | `get_kline()`, `get_kline_symbols()`, `get_kline_rows()`, `refresh_kline()` | 历史K线 → 因子计算 | factor_registry |
| 板块数据 | `get_sector_momentum()`, `get_hot_plates()`, `get_sector_heat()`, `update_sector_cache()` | 板块行情 | analysis, llm_context |
| 指数行情 | `get_index_realtime()` | 全球指数实时 | analysis, llm_context |
| 市态/情绪 | `get_market_regime()`, `update_market_regime()`, `get_market_sentiment()`, `refresh_sentiment_cache()` | 市场状态 | 广泛使用 |
| 因子矩阵 | `get_factor_matrix()` | 33维因子计算 | portfolio_service, strategy_design |
| 新闻 | `get_news()`, `refresh_news()` | 资讯缓存 | analysis, llm_context |
| 缓存同步 | `_sync_columnar_cache()`, `_build_symbol_extra()` | 内部数据缓存 | refresh 内部 |

**导入现状**（11 个源文件 + 5 个测试文件）：

**源文件引用**（9 处）：
- `admin.py`（1处）: `from ..services.pool_manager import pool_manager`
- `analysis.py`（5处）: `from ..services.pool_manager import pool_manager`（每个路由函数各自 import）
- `llm_context.py`（1处）: `from ..services.pool_manager import pool_manager`
- `portfolio_service.py`（2处）: `from ..services.pool_manager import pool_manager`
- `strategy_design.py`（1处）: `from ..services.pool_manager import pool_manager`
- `sector_refresh.py`（1处）: `from ..services.pool_manager import pool_manager`
- `market_service.py`（1处）: `from .pool_manager import pool_manager as pm`
- `market_context.py`（1处）: 直接使用 pool_manager

**测试文件引用**（5处）：
- `test_design_cascade_failure.py`（7个patch路径）: `app.services.pool_manager.PoolManager.*`
- `test_design_optimization_plan.py`（10个patch路径）: `app.services.pool_manager.pool_manager.*`
- `test_strategy_design.py`（5个patch路径）: `app.services.pool_manager.pool_manager.*`
- `test_system_diagnosis_fixes.py`（1个patch路径）: `app.services.pool_manager.pool_manager`
- `test_llm.py`（1个patch路径）: `app.services.pool_manager.pool_manager`



### 1.4 Review Round 1 Findings (2026-07-31)

**发现**: 实际 scope 比初始估计大很多。

#### 源文件（11 处, 10 个文件）
| 文件 | 引用形式 | 特殊处理 |
|------|---------|----------|
| main.py L260-262 | pool_manager.update_market_regime(), pool_manager.refresh_sentiment_cache() | 直接调用 |
| admin.py L216-227 | pool_manager.get_pool(), pool_manager._consecutive_failures | 私有属性访问 |
| analysis.py L74-93 | 5 个函数内 import | 每个路由各有独立 import |
| llm_context.py L14-121 | pool_manager 作为参数 + 直接使用 | 双重引用 |
| portfolio_service.py L425-681 | 2 处函数内 import | 延迟加载 |
| strategy_design.py L37-326 | pool_manager._by_code, pool_manager.etf_pool, 作为参数传递 | 私有属性访问 |
| sector_refresh.py L18 | 函数内 import | 简单 |
| market_context.py L10 | 直接使用 | 简单 |
| market_service.py L989 | 函数内 import as pm | 别名 |

#### 测试文件（14 个, 30+ mock 路径）
| 文件 | mock 模式 | 复杂度 |
|------|-----------|--------|
| test_pool_manager.py L68-227 | 创建 PoolManager 实例 + 方法调用 | 高（7 个测试类） |
| test_pool_manager_phase2.py L29-77 | 创建 PoolManager 实例 | 中 |
| test_pool_manager_layer.py L9-31 | 导入常量 + 函数 | 低 |
| test_design_cascade_failure.py L10-34 | 7 个 patch 路径 | 中 |
| test_design_optimization_plan.py L38-560 | 13 个 monkeypatch + 6 个 pool_manager | 非常高 |
| test_strategy_design.py L16-28 | 7 个 patch 路径 | 中 |
| test_factor_integration.py L183-248 | 4 次 import pool_manager as pm | 中 |
| test_integration_pipeline.py L34-37 | import pool_manager as live_pm | 低 |
| test_market_context.py L197-243 | 2 个 patch + PoolManager 构造 | 中 |
| test_phase0_7.py L143-534 | 5 次 PoolManager 实例化 | 高 |
| test_phase2a_data_quality.py L175-201 | 文件路径检查 | 低 |
| test_phase5_architecture.py L123-126 | 文件路径检查 | 低 |
| test_solution_design_plan.py L25-45 | 2 次 PoolManager 实例化 | 低 |
| test_phase5_architecture.py | MarketDataHub 别名测试 | 低 |

#### 关键风险
1. **strategy_design.py 访问 pool_manager._by_code (私有属性)**：MarketDataHub 包装类必须暴露这个属性
2. **strategy_design.py 传递 pool_manager 作为参数给 _build_market_context()**：函数签名不变，传 market_data_hub 实例
3. **14 个测试文件需要更新 mock 路径**：每个 patch 路径都必须检查
4. **pool_manager.py 末尾的 pool_manager = PoolManager()** 单例创建会一直触发—不能在 market_data_hub 导入时重复创建

#### 修正后的迁移策略
**由于 scope 较大，改为三阶段渐进式:**

1. **Stage 1 (30分钟)**: 只改 market_data_hub.py 为真正的包装类，不改任何 import
2. **Stage 2 (30分钟)**: 逐个改源文件 import，每改一个跑一次测试
3. **Stage 3 (45分钟)**: 更新测试文件 mock 路径

### 1.2 目标架构

```
┌──────────────────────────────────────────────────┐
│                  MarketDataHub                    │
│  (统一数据管道入口, 继承 PoolManager)              │
│                                                   │
│  - get_pool() / get_kline() / get_factor_matrix() │
│  - get_market_regime() / get_market_sentiment()   │
│  - get_sector_momentum() / get_hot_plates()       │
│  - get_index_realtime() / get_news()              │
│  - refresh() — 全量刷新入口                       │
│                                                   │
│  初始化时注册到 Container: MarketDataHub.instance  │
└──────────────────────┬────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   pool_manager.py  scanner.py   factor_registry.py
   (内部实现, 不直   (数据源)     (因子计算)
   接暴露给调用方)
```

**关键设计决策**：
1. **MarketDataHub 是单例容器**，内部持有 PoolManager 实例（而非继承）——松耦合
2. **pool_manager.py 保留为内部实现**，外部代码只能通过 MarketDataHub 访问
3. **渐进式迁移**：先加 MarketDataHub 层，再逐个替换 import，最后决定 pool_manager 去留

### 1.3 迁移步骤

#### Phase A: 创建 MarketDataHub 容器（低风险，~15 分钟）

```python
# app/services/market_data_hub.py

import warnings
from typing import Any
from .pool_manager import PoolManager

# 全局单例（保持现有 pool_manager 引用不变）
market_data_hub: "MarketDataHub" = None  # type: ignore


class MarketDataHub:
    """统一数据管道入口。
    
    包含 PoolManager 的所有公开方法。
    新代码统一通过 MarketDataHub 实例访问数据管道。
    
    用法:
        from app.services.market_data_hub import market_data_hub
        
        regime = market_data_hub.get_market_regime()
        pool = market_data_hub.get_pool()
    """
    
    def __init__(self, pool_manager_instance: PoolManager | None = None):
        self._pool = pool_manager_instance or PoolManager()
    
    # 池管理
    def get_pool(self, *args, **kwargs):
        return self._pool.get_pool(*args, **kwargs)
    
    def get_by_code(self, *args, **kwargs):
        return self._pool.get_by_code(*args, **kwargs)
    
    def set_opportunistic_signals(self, *args, **kwargs):
        return self._pool.set_opportunistic_signals(*args, **kwargs)
    
    # K线数据
    def get_kline(self, *args, **kwargs):
        return self._pool.get_kline(*args, **kwargs)
    
    def get_kline_symbols(self, *args, **kwargs):
        return self._pool.get_kline_symbols(*args, **kwargs)
    
    def get_kline_rows(self, *args, **kwargs):
        return self._pool.get_kline_rows(*args, **kwargs)
    
    async def refresh_kline(self, *args, **kwargs):
        return await self._pool.refresh_kline(*args, **kwargs)
    
    # 板块数据
    def get_sector_momentum(self, *args, **kwargs):
        return self._pool.get_sector_momentum(*args, **kwargs)
    
    def get_hot_plates(self, *args, **kwargs):
        return self._pool.get_hot_plates(*args, **kwargs)
    
    def get_sector_heat(self, *args, **kwargs):
        return self._pool.get_sector_heat(*args, **kwargs)
    
    async def update_sector_cache(self, *args, **kwargs):
        return await self._pool.update_sector_cache(*args, **kwargs)
    
    # 指数行情
    def get_index_realtime(self, *args, **kwargs):
        return self._pool.get_index_realtime(*args, **kwargs)
    
    # 市态/情绪
    def get_market_regime(self, *args, **kwargs):
        return self._pool.get_market_regime(*args, **kwargs)
    
    def update_market_regime(self, *args, **kwargs):
        return self._pool.update_market_regime(*args, **kwargs)
    
    def get_market_sentiment(self, *args, **kwargs):
        return self._pool.get_market_sentiment(*args, **kwargs)
    
    async def refresh_sentiment_cache(self, *args, **kwargs):
        return await self._pool.refresh_sentiment_cache(*args, **kwargs)
    
    # 因子矩阵
    def get_factor_matrix(self, *args, **kwargs):
        return self._pool.get_factor_matrix(*args, **kwargs)
    
    # 新闻
    def get_news(self, *args, **kwargs):
        return self._pool.get_news(*args, **kwargs)
    
    async def refresh_news(self, *args, **kwargs):
        return await self._pool.refresh_news(*args, **kwargs)
    
    # 刷新
    async def refresh(self, *args, **kwargs):
        return await self._pool.refresh(*args, **kwargs)


# 初始化全局单例
def init_market_data_hub(pool_instance: PoolManager | None = None) -> MarketDataHub:
    global market_data_hub
    if market_data_hub is None:
        market_data_hub = MarketDataHub(pool_instance)
    return market_data_hub


# 兼容别名：保持原有 pool_manager 实例
pool_manager = PoolManager()


__all__ = [
    "MarketDataHub", "market_data_hub", "pool_manager",
    "init_market_data_hub",
]
```

#### Phase B: 替换服务层 import（低风险，~15 分钟）

按模块逐个替换：

| 文件 | 原有 import | 替换为 | 备注 |
|------|------------|--------|------|
| `admin.py` (L216) | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 1行替换 |
| `analysis.py` (L74) | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 5处，每个路由函数各自 import |
| `llm_context.py` | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 1处 |
| `portfolio_service.py` (L425) | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 2处 |
| `strategy_design.py` (L37) | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 1处 |
| `sector_refresh.py` (L18) | `from ..services.pool_manager import pool_manager` | `from ..services.market_data_hub import market_data_hub` | 1处 |
| `market_service.py` (L989) | `from .pool_manager import pool_manager as pm` | `from .market_data_hub import market_data_hub` | 1行，pm → market_data_hub |
| `market_context.py` | 直接使用 pool_manager | `from ..services.market_data_hub import market_data_hub` | 1处 |

**调用站点替换**（所有 `pool_manager.xxx()` → `market_data_hub.xxx()`，无签名变更）：

| 原始调用 | 替换后 | 方法签名是否变 |
|----------|--------|---------------|
| `pool_manager.get_pool()` | `market_data_hub.get_pool()` | 否 |
| `pool_manager.get_market_regime(market)` | `market_data_hub.get_market_regime(market)` | 否 |
| ... | ... | 否 |

#### Phase C: 替换测试文件 mock 路径（中风险，~15 分钟）

测试文件的 mock 路径从 `app.services.pool_manager.pool_manager.X` 变为 `app.services.market_data_hub.market_data_hub.X`：

| 文件 | patch 路径数 | 新路径 |
|------|-------------|--------|
| `test_design_cascade_failure.py` | 7 | `app.services.market_data_hub.market_data_hub.*` |
| `test_design_optimization_plan.py` | 10 | `app.services.market_data_hub.market_data_hub.*` |
| `test_strategy_design.py` | 5 | `app.services.market_data_hub.market_data_hub.*` |
| `test_system_diagnosis_fixes.py` | 1 | `app.services.market_data_hub.market_data_hub` |
| `test_llm.py` | 1 | `app.services.market_data_hub.market_data_hub` |

#### Phase D: 清理与验证

1. 在 `pool_manager.py` 顶部加 deprecation warning（从 `warnings.warn` 触发）
2. 运行 `pytest` 全量回归
3. `git grep "pool_manager" app/services/` 检查是否还有直接引用
4. 更新 `main.py` 中初始化逻辑

### 1.4 风险控制

| 风险 | 概率 | 缓解措施 |
|------|------|----------|
| test mock 路径更新遗漏导致 CI 失败 | 中 | 先跑 `pytest -x` 单测，mock 路径逐条更新 |
| 运行时 import 循环 | 低 | `market_data_hub.py` 不 import `pool_manager.py` 外层内容 |
| 方法签名镜像漏掉 | 低 | 从 `PoolManager.__dict__` 自动生成 wrapper 方法列表 |
| 单例初始化顺序 | 低 | 延迟初始化 + `init_market_data_hub()` 显式调用 |

---

## 二、任务持久化统一（TaskManager JSON → DB）

### 2.1 当前状态分析

**现状**: TaskManager 使用 JSON 文件 `data/tasks.json` 持久化任务（Z27 已修路径），但设计任务同时写 SQLite DB。存在双轨断裂：重启后 JSON 文件丢失，但 DB 中仍有设计记录。

### 2.2 目标架构

- 添加 `TaskRecord` SQLAlchemy 模型
- TaskManager 改为读写 DB，JSON 作为兼容 fallback
- 迁移：自动将已有 JSON 任务导入 DB

### 2.3 迁移步骤

1. 定义 `TaskRecord` 模型（继承 Base）
2. 在 `main.py` lifespan 中创建表
3. TaskManager 新增 `_persist_task()`, `_load_tasks()` → 操作 DB
4. JSON 文件保留为读兼容（启动时导入到 DB）
5. 测试覆盖

**工作量**: ~半日

---

## 三、因子 ETL 第二路并行

### 3.1 当前状态

PoolManager 刷新是单路串行：`refresh_kline() → scan → classify → factor`。部分 ETF 数据和情绪数据在 scan 阶段获取不全。

### 3.2 目标

增加第二路并行的数据获取器，专门收集：
- ETF 特有数据（IOPV、折溢价、规模）
- 情绪指标（两市成交额、换手率、融资数据）

### 3.3 风险

- 增加启动时间（并行获取但受限于外部 API 限流）
- 数据一致性（两路数据可能有时间差）

---

## 四、验证标准

阶段 A-C 各有独立的验证标准：

| 阶段 | 验证 |
|------|------|
| Phase A | `pytest tests/test_market_data_hub.py`（新增）全部通过 |
| Phase B | `pytest .` 全量 39+ 测试通过 |
| Phase C | 所有 mock 路径正确，`assert_called_with` 通过 |
| Phase D | `git grep "pool_manager" app/` 结果为 `app/services/pool_manager.py` 和 `app/services/market_data_hub.py` 两个文件 |

---

## 五、回滚策略

每个 Phase 有独立 commit，可单独 revert：

```
git revert <phase-b-commit>   # 回退 import 替换
git revert <phase-a-commit>   # 回退 MarketDataHub 创建
```

---

## 六、时间线

| Phase | 内容 | 工作量 |
|-------|------|--------|
| Phase A | 创建 MarketDataHub + 单例 + 初始化 | ~15分钟 |
| Phase B | 替换 9 个源文件 import + 调用 | ~15分钟 |
| Phase C | 替换 5 个测试文件 mock 路径 | ~15分钟 |
| Phase D | deprecation warning + 验证 + CI 确保 | ~15分钟 |
| **合计** | **数据管道统一** | **~1小时** |
| | 任务持久化统一 | ~半日 |
| | 因子 ETL 第二路 | ~半日 |
