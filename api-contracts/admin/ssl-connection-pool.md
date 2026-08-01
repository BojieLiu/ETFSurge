# API 契约: SSL 连接池握手优化 (Z05)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z05
> 变更类型: 内部实现优化（无 API 契约变更，仅新增可观测指标）
> 版本: v1.0

## 1. 概述 / Overview

**功能描述**: 修复 SSL 连接池已配置但握手次数未达标（<5）的问题。核心是让 NAV/全球指数路径复用共享 `httpx.AsyncClient`（连接池），并新增预热握手计数指标暴露到 `/admin/sources` 和日志。

**触发场景**: 后端启动预热、定时刷新 NAV/全球指数、verify_e2e 验证。

---

## 2. 无 API 变更 / No API Changes

此问题不涉及对外 API 契约变更，仅内部实现优化。

**验收指标（暴露在现有端点）**:

| 端点 | 新增字段 | 说明 |
|------|----------|------|
| `GET /api/v1/admin/sources/connection-pool` | `sources[].connection_pool.handshakes` | 该数据源累计 SSL 握手次数 |
| `GET /api/v1/admin/sources/connection-pool` | `sources[].connection_pool.reused` | 连接复用次数 |
| `GET /api/v1/system/warmup` | `warmup.market_cache.handshakes` | 预热阶段握手计数 |
| 日志 | `logger.info("[warmup] SSL handshakes: %d", count)` | 启动日志可见 |

**验收口径**: **可控 host 级握手 ≤ 1**（同一 host 复用连接，不重复握手）。不可控外部源（akshare 内部、yfinance 等）不在考核范围。

---

## 3. 实现契约 / Implementation Contract

### 3.1 共享 httpx.AsyncClient 单例

**位置**: `backend/app/services/global_markets_fetcher.py` `backend/app/services/market_data_hub.py` 等

**模式**: 模块级单例 `_shared_client: httpx.AsyncClient | None = None`，配置：
```python
httpx.AsyncClient(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    timeout=httpx.Timeout(10.0, connect=5.0),
    http2=True,
)
```

### 3.2 NAV 路径接入共享 Client

**位置**: `backend/app/services/market_service.py` → `fetch_nav_batch()` / `get_nav()` 等

**修改**: 将 `urllib.request` 裸调用替换为 `await _shared_client.get(url, ...)`，并累计握手计数。

### 3.3 全球指数路径接入共享 Client

**位置**: `backend/app/fetchers/global_markets_fetcher.py` 中的 `urllib.request` 调用点（约 5 处）

**修改**: 统一改用共享 client。

### 3.4 预热握手计数

**位置**: `backend/app/main.py` lifespan 中 `refresh_market_cache()` 调用前后

**指标**: 记录预热前后握手计数差值，写入 warmup 状态对象。

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| /admin/sources 返回 connection_pool.handshakes | N/A | ☐ | 新增字段 |
| /admin/sources 返回 connection_pool.reused | N/A | ☐ | 新增字段 |
| /system/warmup 返回 handshakes 计数 | ☐ | ☐ | 前端可展示 |
| 启动日志含 SSL handshakes 计数 | N/A | ☐ | 可观测 |
| 可控 host 握手 ≤ 1 (verify_e2e 验证) | N/A | ☐ | 验收口径 |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_z05_ssl_pool.py`（mock httpx.Client 验证复用）
- verify_e2e: `section_admin` 验证 sources 含 connection_pool 字段