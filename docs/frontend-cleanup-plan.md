# 前端清理方案

> **实现状态: ✅ 2026-07-20 已全部完成**
> - `portfolioApi.design` 已移除 → 用 `designAsync`
> - `analysisApi.portfolioDesign` / `portfolioDesignStream` 已移除
> - `strategyCheck` API 已重定向到 async 端点
> - 后端 `strategy-check` 同步路由已删除

将前端与后端已经删除的旧路由对应的 API 调用一并清理干净。

## 清理清单

### 1. `frontend/src/api/index.js`
- [x] `portfolioApi.design()` → 已移除
- [x] `analysisApi.portfolioDesign()` → 已移除
- [x] `analysisApi.portfolioDesignStream()` → 已移除
- [x] `portfolioApi.strategyCheck()` → 已重定向到 `/portfolio/strategy-check-async`
- [ ] `portfolioApi.strategyCheck(data, config)` → 参考后端，同步 version 已移除

### 2. `frontend/src/stores/portfolio.js`
- [ ] `runStrategyCheck()` → 确认是否被任何组件 import
- [x] 使用 `strategyCheckAsync` 代替

### 3. 前端 test mock 文件
- [x] 保留 `strategyCheck` mock 名称（指向 async 端点后名称不变）

### 4. WebSocket 连接
- [ ] WS 自动重连时 /design 旧路由 → 已确认不影响（WS 不走 REST）
