# Circuit Breaker / 熔断器监控 API

## 1. 概述 / Overview

**功能描述 / Description**: 管理所有数据源的熔断器状态，支持查询、重置和 try_call 调用模式。

**触发场景 / Trigger**: 管理员监控页面加载时获取；运维人员手动重置熔断器。

---

## 2. 端点定义 / Endpoints

### 2.1 熔断器状态查询

```
GET /api/v1/admin/sources/circuit-breakers
```

**成功响应 — `200 OK`:**

```json
{
  "circuit_breakers": [
    {
      "name": "push2.eastmoney.com",
      "state": "open",
      "failures": 3,
      "failure_threshold": 3,
      "cooldown_secs": 60,
      "cool_until": 1700000000.0
    },
    {
      "name": "sina",
      "state": "closed",
      "failures": 0,
      "failure_threshold": 3,
      "cooldown_secs": 30,
      "cool_until": null
    }
  ]
}
```

> T11 契约校准：原契约声明 `GET /admin/circuit-breaker`（后端从未实现），实际路由为
> `GET /admin/sources/circuit-breakers`（admin.py）。

### 2.2 熔断器重置（**未实现** — 契约校准删除声明）

> T11 契约校准：原契约声明 `POST /admin/circuit-breaker/reset`，后端无此路由，
> 删除该端点声明（契约只反映已实现接口）。

### 2.3 内联调用模型

不暴露为 HTTP API，为 Python 内部调用模型：

```python
# try_call 包装器：健康检查 → 执行 → 记录结果，三合一
result = registry.try_call(
    name="push2.eastmoney.com",
    fn=run_in_thread,
    args=(_p,),
    kwargs={"timeout": 8, "executor": "long"},
)

# 手动检查熔断状态
h = registry._health("push2.eastmoney.com")
if h.available(time.time()):
    # 执行调用
    ...
```

---

## 3. 数据结构 / Data Structures

### SourceHealth 增强

| 字段 | 类型 | 说明 |
|------|------|------|
| base_cooldown | float | 基础冷却时长 (60s) |
| max_cooldown | float | 最大冷却时长 (600s / 10min) |
| consecutive_cycles | int | 连续冷却周期数（指数退避用） |

### try_call 行为

```python
def try_call(self, name, fn, *args, timeout=0, **kwargs):
    """健康检查 → 执行 → 记录结果，三合一。
    
    如果熔断器打开，直接返回 None。
    如果调用失败，自动调用 record_failure 或 record_hard_failure。
    如果调用成功，自动调用 record_success。
    
    自动检测 fast-fail（<500ms 的失败视为硬失败）。
    """
```

---

## Frontend-Backend Checklist

- [ ] API 契约已定义
- [ ] 后端实现完成
- [ ] 单元测试通过
- [ ] 前端 SourceMonitor 页面已适配（如有）
