# WebSocket Endpoints / WS 端点总览

> R185 批次（冗余评审 P2-2，docs/redundant-review.md §5.4/§2.2 S5）：`/ws/market/{symbol}`
> 后端存在但前端零消费（实际行情 WS 逻辑走 `/ws/portfolio`，AGENTS.md conventions 已记载），
> 本契约显式标注 deprecated 防「有端点无调用」的脚手架观感；后续清理轮可移除。

## 端点清单 / Endpoint Inventory

| 路径 | 状态 | 消费方 | 说明 |
|---|---|---|---|
| `/api/v1/ws/news` | ✅ 活跃 | `useNewsWS.js` | 资讯推送（single + batch），详见 `api-contracts/news/all.md` |
| `/api/v1/ws/portfolio` | ✅ 活跃 | `stores/market.js` + `useTaskWS.js`（行情 WS 逻辑实际载体） | 组合/行情推送 |
| `/api/v1/ws/task-notifications` | ✅ 活跃 | `useTaskWS.js` | 设计/检查/报告任务进度 |
| `/api/v1/ws/market/{symbol}` | ⚠️ **deprecated** | **无（前端零消费）** | 单标的行情 WS；round35 FE4/RC-B4 起前端走 `/ws/portfolio` |

## `/api/v1/ws/market/{symbol}` deprecated 标注

- **状态**: deprecated（保留端点，未删除——移除属清理轮独立决策，需同步
  `backend/app/routers/ws.py:86` 与 check_routes 基线）；
- **替代**: `/api/v1/ws/portfolio`（组合池全标的行情，前端唯一行情 WS 消费路径）；
- **风险**: 若未来需要单标的高频推送，应走新契约评审而非复活本端点。

## Frontend-Backend Checklist

- [x] 三活跃 WS 路径与 AGENTS.md conventions 段一致
- [x] deprecated 标注与 `backend/app/routers/ws.py` 现状核对（存在但零消费）
- [x] Vite 代理顺序注记：`/api/v1/ws` 规则须在 `/api` 之前（`vite.config.js`）
