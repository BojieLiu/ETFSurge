# Admin — Lifespan NAV 预热健康度 / Lifespan NAV Warmup Health

## 1. 概述 / Overview

**功能描述 / Description**: 暴露 lifespan 后台 NAV Redis 预热任务
(`_nav_warmup_loop`, 853fcf2) 的健康度. 拉数据不触网, 只读
`app.state.nav_warmup` 共享 dict. 供运维监控 / 前端运维面板 / verify_e2e
确认后台预热真在跑 (不是卡死 / 异常退出).

**触发场景 / Trigger**: 运维轮询 (5min 间隔); 交易时段重启后 70s 拉一次确认
首轮完成; 二次启动 lifespan 1618 任务 < 1s 命中验证 (R45 治本验收).

**对应方案项 / Plan item**: R49 B3 (lifespan 预热 health 端点); 衔接 R45
option C (commit 853fcf2).

---

## 2. 端点定义 / Endpoints

### 2.1 拉取 lifespan 预热健康度 / Get Lifespan Warmup Health

```
GET /api/v1/admin/lifespan-warmup
```

**响应 / Response (200, state 已初始化):**

```json
{
  "enabled": true,
  "redis_available": true,
  "started_at": "2026-08-29T10:00:00Z",
  "warmup_period_s": 3600,
  "first_run_delay_s": 60,
  "last_cycle": {
    "ts": "2026-08-29T10:01:00Z",
    "cycle": 1,
    "total": 1618,
    "ok": 1500,
    "skip": 100,
    "err": 18,
    "duration_s": 412.5,
    "reason": null
  },
  "next_run_eta_s": 3540
}
```

**响应 / Response (200, state 未初始化, 启动 60s 内):**

```json
{
  "enabled": true,
  "redis_available": false,
  "started_at": null,
  "warmup_period_s": 3600,
  "first_run_delay_s": 60,
  "last_cycle": null,
  "next_run_eta_s": null,
  "_state_uninitialized": true
}
```

**字段说明:**

| 字段 | 类型 | 说明 |
|---|---|---|
| enabled | bool | 后台预热任务是否启用 (本轮恒为 true) |
| redis_available | bool | 最近一次 ping 状态; 决定 next cycle 是否跑 |
| started_at | ISO8601 string \| null | lifespan 启动时戳 (UTC); null = 启动 60s 内 |
| warmup_period_s | int | 周期秒数 (1h = 3600) |
| first_run_delay_s | int | 启动后首轮延迟秒数 (60s) |
| last_cycle | object \| null | 最近一轮指标; null = 首轮未跑完 |
| last_cycle.cycle | int | 第几轮 (从 1 开始) |
| last_cycle.total | int | 本轮候选总数 |
| last_cycle.ok | int | 成功拉取数 (Redis miss → fetch → set) |
| last_cycle.skip | int | Redis 已命中数 (无需拉取) |
| last_cycle.err | int | 异常数 (fetch 失败 / 网络错 / timeout) |
| last_cycle.duration_s | float | 本轮总耗时 (秒) |
| last_cycle.reason | string \| null | null=正常; "redis_unavailable"=Redis ping 失败; "pool_empty"=候选池空; "exception: <Name>"=整体异常 |
| next_run_eta_s | int | 距下一轮启动秒数 (按 elapsed 调整) |
| _state_uninitialized | bool | 仅在 state 未初始化时存在, 客户端可识别 |

---

## 3. 数据源 / Source

- 共享状态 `app.state.nav_warmup` (dict) 在 `_nav_warmup_loop` 启动时初始化, 每轮结束更新.
- 端点只读, 不修改 state.
- 不触网, 不调 Redis (health 度已 ping 过, 缓存在 state).

---

## 4. 鉴权 / Auth

无中间件鉴权 (与 `token-usage` / `llm-excluded` 一致). 部署侧建议 reverse proxy
限制 admin 路径仅内网可达.

---

## 5. 前端集成 / Frontend Integration

运维面板聚合端点 (R49 C3 留尾) 候选列表:
- `/admin/lifespan-warmup` (本端点)
- `/admin/llm-excluded` (R46 §1)
- `/admin/thread-pool` (既有)
- `/admin/metrics` (既有)
- `/admin/token-usage` (既有)

聚合后运维 1 个面板看全后端健康.

---

## 6. Frontend-Backend Checklist

- [ ] 字段命名 (enabled/redis_available/started_at/...) 与后端 dict 键一致
- [ ] `_state_uninitialized` 仅在启动 60s 内出现, 前端应静默展示"等待首轮"
- [ ] `last_cycle` 为 null 时前端不显示数字, 显示 "暂无数据 (启动 < 60s)"
- [ ] `next_run_eta_s` 单调递减, 到达 0 后下次拉取变回 3600 (新一轮开始)
- [ ] `reason` 字段非 null 时前端应给视觉提示 (e.g. 黄色 "Redis 不可用" 标签)
- [ ] 鉴权: 前端不需带 token, 由 reverse proxy 网关控
- [ ] 拉取频率建议 5min/次, 避免高频打 lifespan 状态读取
