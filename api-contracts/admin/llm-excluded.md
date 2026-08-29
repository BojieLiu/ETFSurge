# Admin — LLM 排除名单管理 / LLM mark_excluded Management

## 1. 概述 / Overview

**功能描述 / Description**: 持久化管理 LLM 熔断三件套护栏 3 (排除表) 的运行时
黑名单. 此前 model_catalog._exclusions 仅 in-memory set[str], 后端重启即清零;
本端点通过 AppConfig 表 (`llm_excluded:<provider>:<model>` = "1") 持久化, 启动期
由 main.py lifespan 灌回 in-memory.

**触发场景 / Trigger**: 运维手工剔除持续 503/400 的免费模型 (b.ai / openrouter);
R143 熔断三件套自动 mark_excluded 后, 通过 GET 端点查证; DELETE 取消 (如临时
故障恢复后).

**对应方案项 / Plan item**: R143 改进熔断三件套 (commit 934d2a4) 护栏 3 持久化;
round46 §1.

---

## 2. 端点定义 / Endpoints

### 2.1 列出全部 LLM 排除项 / List LLM Excluded

```
GET /api/v1/admin/llm-excluded
```

**响应 / Response (200):**
```json
{
  "items": [
    {"provider": "opencode_zen", "model": "gpt-5-nano-free"},
    {"provider": "openrouter", "model": "z-ai/glm-4.5-air:free"}
  ],
  "total": 2
}
```

排序: (provider, model) 字典序; `total` 与 `len(items)` 一致.

### 2.2 添加 LLM 排除项 / Add LLM Excluded

```
POST /api/v1/admin/llm-excluded
```

**请求体 / Request Body:**
```json
{
  "provider": "opencode_zen",
  "model": "gpt-5-nano-free",
  "reason": "持续 503"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| provider | string (1-64) | Yes | provider id: opencode_zen / openrouter / b_ai / deepseek |
| model | string (1-128) | Yes | 模型 id |
| reason | string (0-256) | No | 排除原因 (仅记日志, 不持久化到 DB) |

**响应 / Response (200):**

成功:
```json
{
  "status": "added",
  "provider": "opencode_zen",
  "model": "gpt-5-nano-free",
  "persisted": true
}
```

重复添加 (已在 in-memory set 中):
```json
{
  "status": "already_excluded",
  "provider": "opencode_zen",
  "model": "gpt-5-nano-free"
}
```

`persisted=false` 表示 DB 写入失败 (in-memory 已生效, 下次启动会丢) — 客户端可
重试或运维查日志.

### 2.3 取消 LLM 排除项 / Remove LLM Excluded

```
DELETE /api/v1/admin/llm-excluded/{provider}/{model}
```

**路径参数 / Path Parameters:**
- `provider`: provider id
- `model`: 模型 id (URL 编码, 罕见含 `/` 的 OpenRouter model id 需 `:`-split)

**响应 / Response (200):**
```json
{
  "status": "removed",
  "provider": "opencode_zen",
  "model": "gpt-5-nano-free",
  "in_mem_removed": true,
  "db_deleted": true
}
```

未找到 (in-memory + DB 都无):
```json
{
  "status": "not_found",
  "provider": "opencode_zen",
  "model": "never-added",
  "in_mem_removed": false,
  "db_deleted": false
}
```

---

## 3. 持久化 / Persistence

- DB 表: `app_config` (与 `config_manager.set_override` 同一张表)
- Key 格式: `llm_excluded:<provider>:<model>`
- Value: `"1"` (存在即排除, value 内容无意义)
- 启动加载: `main.py` lifespan `load_llm_excluded` 阶段调
  `config_manager.list_keys_with_prefix("llm_excluded:")` + 
  `model_catalog.load_excluded_from_keys(...)`; banner 日志
  `[lifespan] LLM exclusions loaded: N/N (DB keys scanned=M)`.

---

## 4. 鉴权 / Auth

无中间件鉴权 (与 `token-usage` / `metrics` 等 admin 端点一致). 部署侧建议
通过 reverse proxy 限制 admin 路径仅内网可达.

---

## 5. 前端集成 / Frontend Integration

前端 SourceMonitor 面板 (admin UI) 可加 "Mark Excluded" 按钮:
- 调 POST (添加) — 立即从候选池隐藏该模型
- 调 DELETE (取消) — 恢复候选
- 调 GET (列表) — 启动时拉取填充
- 提交理由 (reason) 仅记日志, 不展示

---

## 6. Frontend-Backend Checklist

- [ ] 字段命名 (provider/model/reason) 与后端 Pydantic `LLMExcludedCreate` 一致
- [ ] GET 响应 items 数组元素为 `{provider, model}` (无 reason 字段)
- [ ] POST 已存在模型时 status="already_excluded" (前端应静默忽略)
- [ ] DELETE 返回的 `in_mem_removed` / `db_deleted` 用于诊断持久化失败
- [ ] 鉴权: 前端不需带 token, 由 reverse proxy 网关控
- [ ] URL 编码: 含 `/` 的 model id (OpenRouter: `meta-llama/llama-3.3-70b:free`)
      需用 `:` 替换 `/` 或 full encode (后端 route param 不强校验)
