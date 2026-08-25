# Admin — LLM Health Probe / LLM 供应商健康探针

## 1. 概述 / Overview

**功能描述 / Description**: 实时探测已配置 LLM 供应商（OpenCode Zen / DeepSeek Official）的连通性与可用性，不调用完整业务链路。供运维监控、前端 `SourceMonitor` 面板和 `verify_e2e` 的 F17 连通性测试使用。

**触发场景 / Trigger**: 运维监控轮询；`verify_e2e.py` F17 连通性测试；用户在前端手动刷新 LLM 状态。

**对应方案项 / Plan item**: `system-diagnosis-and-optimization-plan.md` → **F7**（LLM 健康探针）。

---

## 2. 端点定义 / Endpoints

### 2.1 LLM 健康探针 / LLM Health

```
GET /api/v1/admin/llm/health
```

**Query 参数 / Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| timeout | float | No | 15.0 | 单供应商探测超时（秒），用于约束探针整体耗时 |
| refresh | bool | No | false | 强制实时探测（绕过 60s 结果缓存） |

> **缓存语义（2026-08-25 增补，降级日连接风暴治理）**：默认 60s TTL 返回缓存
> 结果（`checked_at` 为实际探测时刻）。背景：供应商全死日（如 Zen 持续 503）
> 单次探针持连 9-19s，e2e/监控连环调用形成长持连请求簇，尾部触发内核
> backlog 瞬时溢出 → WinError 10061 连发（round36 §9 四路仪器取证）。缓存后
> 重复调用毫秒级返回；需要强实时时传 `refresh=true`。与 `factor-health`
> 60s 缓存同款模式。

**成功响应 — `200 OK`:**

```json
{
  "status": "ok",
  "checked_at": 1753830000.0,
  "has_api_key": true,
  "providers": [
    {
      "id": "opencode_zen",
      "name": "OpenCode Zen",
      "model": "deepseek-v4-flash-free",
      "ok": true,
      "latency_ms": 2100.5,
      "status": "available",
      "error": null
    },
    {
      "id": "deepseek",
      "name": "DeepSeek Official",
      "model": "deepseek-v4-flash",
      "ok": false,
      "latency_ms": 91000.0,
      "status": "timeout",
      "error": "Client error '504 Gateway Timeout' ..."
    }
  ]
}
```

**无 API Key 响应 — `200 OK`:**

```json
{
  "status": "no_key",
  "checked_at": 1753830000.0,
  "has_api_key": false,
  "providers": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| status | string | 整体状态：`ok`（至少一个供应商可用）/ `degraded`（已配置 key 但全部探测失败）/ `no_key`（未配置任何 API key） |
| checked_at | float | 探测时间戳（Unix epoch，秒） |
| has_api_key | bool | 是否存在至少一个供应商的 API key |
| providers[].id | string | 供应商唯一标识（`opencode_zen` / `deepseek`） |
| providers[].name | string | 供应商可读名称 |
| providers[].model | string | 探测所用模型标识 |
| providers[].ok | bool | 探测是否成功（收到合法 `choices[0].message`） |
| providers[].latency_ms | float | 探测往返耗时（毫秒，含失败耗时） |
| providers[].status | string | 单供应商状态：`available` / `timeout` / `error` / `no_key` |
| providers[].error | string\|null | 失败时的错误信息（成功为 `null`） |

**行为约束 / Behavior:**
- 并发探测所有已配置供应商（`asyncio.gather`，`return_exceptions=True`），整体耗时受 `timeout` 约束（每供应商内部超时 = `timeout`）。
- 探针使用最小 prompt（"ping"），`max_tokens` 取小值（如 16），避免消耗 reasoning 预算。
- 探针**不写入** `token_store`（健康探测不应污染真实 token 用量统计）。
- 探测失败必须返回结构化结果，不得抛出 500。

---

## 3. 前端消费 / Frontend

前端 `SourceMonitor` / 运维面板读取 `status` 与 `providers[]` 展示每个供应商的连通灯（绿/黄/灰）与延迟。

---

## Frontend-Backend Checklist

- [ ] `GET /api/v1/admin/llm/health` 返回 200（含 `status` / `has_api_key` / `providers`）
- [ ] 无 key 时返回 `status="no_key"`，不报错
- [ ] 单供应商失败时不抛 500，记录于 `providers[].error`
- [ ] `verify_e2e` F17 用例消费该端点
