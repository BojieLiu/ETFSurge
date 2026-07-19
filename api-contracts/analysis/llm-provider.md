# LLM Provider Failover / LLM 提供商降级方案

## 1. 概述 / Overview

定义双层 LLM 提供商自动降级机制：优先使用 OpenCode Zen（DeepSeek V4 Flash Free），失败或超时时自动降级到官方 DeepSeek API（DeepSeek V4 Flash）。

Defines a dual-tier LLM provider failover mechanism: primary uses OpenCode Zen (DeepSeek V4 Flash Free), with automatic fallback to the official DeepSeek API (DeepSeek V4 Flash) on failure or timeout.

---

## 2. Provider 定义 / Provider Definitions

| Property | Primary | Fallback |
|----------|---------|----------|
| ID | `opencode_zen` | `deepseek` |
| Name | OpenCode Zen | DeepSeek Official |
| API Base URL | `https://opencode.ai/zen/v1` | `https://api.deepseek.com` |
| Chat Endpoint | `https://opencode.ai/zen/v1/chat/completions` | `https://api.deepseek.com/chat/completions` |
| Model | `deepseek-v4-flash-free` | `deepseek-v4-flash` |
| Auth Header | `Bearer {OPENCODE_ZEN_API_KEY}` | `Bearer {DEEPSEEK_API_KEY}` |
| Timeout | 120s (configurable) | 120s (configurable) |

---

## 3. 降级行为 / Failover Behavior

### 3.1 优先级 / Priority

```
Primary (opencode_zen) → Fallback (deepseek)
```

### 3.2 触发条件 / Trigger Conditions

以下任一情形触发降级：

- **超时 (Timeout)**：请求在 `llm_primary_timeout` 秒内未返回
- **HTTP 错误 (HTTP Error)**：`4xx` 或 `5xx` 状态码（除 `429 Too Many Requests` 外）
- **网络错误 (Network Error)**：DNS 解析失败、连接被拒绝、SSL 错误等
- **JSON 解析错误**：响应体不是合法 JSON 或缺少 `choices` 字段

### 3.3 重试策略 / Retry Policy

| Layer | Max Retries | Notes |
|-------|-------------|-------|
| Per provider | 1 次 (已有 `max_retries` 在 `AgentConfig`) | registry 中已有的重试逻辑不变 |
| Cross-provider | 主失败 → 降级 | 降级后不再重试主 provider |

`AgentRuntime.run()` 的 `max_retries` 重试当前 provider，失败后由 `llm_complete_with_system` 的 failover 逻辑切换到下一个 provider。

### 3.4 降级日志 / Logging

每次降级记录 WARNING 级别日志：

```
[LLM] Provider opencode_zen failed after 15.2s: HTTP 503 (Service Unavailable)
[LLM] Falling back to deepseek (provider deepseek)
```

### 3.5 用量记录 / Token Usage

`UsageRecord` 新增 `provider` 字段，记录实际使用的 provider ID。

---

## 4. 配置项 / Configuration

| Env Variable | Type | Default | Description |
|-------------|------|---------|-------------|
| `OPENCODE_ZEN_API_KEY` | string | `""` | OpenCode Zen API key |
| `OPENCODE_ZEN_MODEL` | string | `"deepseek-v4-flash-free"` | OpenCode Zen model name |
| `OPENCODE_ZEN_API_URL` | string | `"https://opencode.ai/zen/v1/chat/completions"` | OpenCode Zen endpoint |
| `LLM_PRIMARY_PROVIDER` | string | `"opencode_zen"` | Primary provider ID |
| `LLM_FALLBACK_PROVIDER` | string | `"deepseek"` | Fallback provider ID |
| `LLM_PRIMARY_TIMEOUT` | int (s) | `120` | Primary provider request timeout |
| `LLM_FALLBACK_TIMEOUT` | int (s) | `120` | Fallback provider request timeout |

---

## 5. 调用流程 / Call Flow

```
Caller (generate_* / AgentRuntime.run)
  │
  ▼
llm_complete_with_system()
  │
  ├─► [Primary] opencode_zen: POST to https://opencode.ai/zen/v1/chat/completions
  │   ├─ Success → return result (with provider="opencode_zen")
  │   └─ Failure → log warning, switch to fallback
  │
  └─► [Fallback] deepseek: POST to https://api.deepseek.com/chat/completions
      ├─ Success → return result (with provider="deepseek")
      └─ Failure → raise last exception
```

---

## 6. 错误处理 / Error Handling

| Scenario | Behavior |
|----------|----------|
| 主 provider 不可用 | 自动降级到备，耗时增加 |
| 备 provider 也不可用 | 抛 `RuntimeError`，调用方捕获后返回 fallback 数据（如 `_fallback_portfolio_plans`） |
| 主 provider 成功但响应格式异常 | 视为失败，尝试降级 |
| 流式连接中断 | 作为 error 抛出，下游 `run_stream` 捕获并 yield error |

---

## 7. 安全说明 / Security Notes

- API keys 存储在 `backend/.env`，已在 `.gitignore` 中排除
- 所有测试 **必须 mock 所有 HTTP 调用**，不能包含真实 API key
- OpenCode Zen API key: `sk-NNhpf3PJLlHKelhzsoT4aCjkctQ5M7xjIXaJjTjQFAl0B47EbdtZrsxdHINBaaT5`（仅本地 `.env`）
- DeepSeek API key: 已有的 `DEEPSEEK_API_KEY`（仅本地 `.env`）

---

## 8. 前后端检查表 / Frontend-Backend Checklist

| Item | Backend | Notes |
|------|---------|-------|
| New config fields in `config.py` | ☐ | OPENCODE_ZEN_API_KEY, LLM_PRIMARY_PROVIDER, etc. |
| `provider.py` module with provider config + failover | ☐ | New file under `app/analysis/` |
| `llm.py` core functions use failover | ☐ | llm_complete, llm_complete_with_system, llm_complete_stream |
| `token_usage.py` records provider field | ☐ | UsageRecord + DB migration |
| `design_report.py` updated timeout | ☐ | 90s → 180s for failover budget |
| Tests for all failover scenarios | ☐ | P0-P3, P0.5, UX3, UX4 |
| `.env.example` updated (without real keys) | ☐ | Document new env vars |
| No API keys in git history | ☐ | Verify before commit |
