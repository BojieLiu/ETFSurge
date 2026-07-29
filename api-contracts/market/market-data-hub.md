# MarketDataHub Contract / 市场数据枢纽契约

> **Version**: 1.0 | **Date**: 2026-07-29

---

## 1. 概述 / Overview

**功能描述 / Description**: MarketDataHub 是系统唯一的数据管道入口，统一管理 K 线缓存、数据源健康追踪和消费者分发。

**设计目标 / Goals**:
- 消除三条独立数据管道的重复 I/O（scanner→factor→market_service 三路独立）
- 标准化缓存格式（行式 + 列式懒转换）
- 所有 K 线消费者从 Hub 读取，减少 60% 网络开销

**命名策略 / Naming**: `MarketDataHub` 是 `PoolManager` 的别名（继承），现有调用方无需修改。

---

## 2. API / 内部接口

### 2.1 K 线缓存统一

```
PoolManager (现有) → MarketDataHub (别名, 新增)
```

| 方法 | 签名 | 说明 | 消费者 |
|------|------|------|--------|
| `get_kline_rows(symbol, max_age=300)` | `(str, int) → list[dict] | None` | 行式读取（供 get_history） | `market_service.get_history()` |
| `get_kline(symbol, max_age=300)` | `(str, int) → dict | None` | 列式读取（懒转换，供 compute） | `factor_registry.compute()` |
| `refresh_kline(symbols)` | `(list[str]) → None` | 增量刷新 | `_refresh_impl()` |
| `get_kline_symbols()` | `() → list[str]` | 列出缓存中的代码 | 运维/诊断 |

### 2.2 数据流

```
refresh_kline(symbols):
  [P0] push2delay fetch_history      (主力, 已用)
    → [P1] NetEase fetch_history_netease  (S12, 新增降级)
    → [P2] tushare get_k_data         (已有Token)

get_history(symbol):
  [P0] Hub 缓存 get_kline_rows()
    → [P1] 降级：直接 fetch_history()

compute_chart_data(symbol, days):
  [P0] Hub 缓存 get_kline()(列式)
    → [P1] 降级：直接 fetch + 指标计算
```

---

## 3. 数据格式规范 / Data Format Specification

### 3.1 行式格式（缓存存储）

```python
{
    "date": "2026-07-28",       # str: 日期
    "open": 3.45,               # float: 开盘价
    "high": 3.52,               # float: 最高价
    "low": 3.42,                # float: 最低价
    "close": 3.48,              # float: 收盘价
    "volume": 12345678.0,       # float: 成交量
}
```

### 3.2 列式格式（懒转换，供 factor compute）

```python
{
    "close": [3.45, 3.48, ...],     # list[float]: 收盘价序列(60天)
    "high": [3.50, 3.52, ...],      # list[float]: 最高价序列
    "low": [3.40, 3.42, ...],       # list[float]: 最低价序列
    "volume": [1e7, 1.2e7, ...],    # list[float]: 成交量序列
    "change_pct": [0.0, 0.87, ...], # list[float]: 涨跌幅序列(%)
}
```

---

## 4. 接口变更 / API Changes

| 变更 | 类型 | 向后兼容 |
|------|------|---------|
| 新增 `MarketDataHub` 别名类 | 新增 | ✅ — 不影响现有 `PoolManager` |
| 新增 `get_kline_rows()` | 新增 | ✅ — 新方法 |
| 重写 `get_kline()` | 内部 | ✅ — 签名不变 |
| `get_history()` 走 Hub 缓存 | 内部 | ✅ — JSON 响应不变 |
| `compute_chart_data()` 走 Hub K 线 | 内部 | ✅ — ECharts 数据格式不变 |

---

## 5. 测试计划 / Test Plan

| 测试 | 覆盖内容 | 类型 |
|------|---------|------|
| `test_get_kline_rows` | 缓存读写/过期 | 单元 |
| `test_market_data_hub_alias` | MarketDataHub 别名正常导入 | 单元 |
| `test_get_history_hub_cache` | get_history 优先走缓存 | 集成（mock） |
| `test_compute_chart_data_hub` | chart data 走 Hub K 线 | 集成（mock） |
| `test_etf_shares_real_data` | fetch_etf_shares 返回非 None | 单元（mock） |

---

## 6. Frontend-Backend Checklist

- [x] 后端接口：无前端变化的接口变更（纯内部重构）
- [x] 数据格式：get_history、get_indicators 响应格式不变
- [x] ECharts 兼容性：compute_chart_data 返回格式与之前完全一致
- [ ] Lighthouse 验证：build 后验证无性能回归
