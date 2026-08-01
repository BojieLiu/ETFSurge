# Analysis — LLM Reports & Advice / AI 分析报告与建议

## 1. All endpoints overview / 所有端点一览

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/analysis/llm-report` | Generate LLM analysis report for given symbols |
| POST | `/api/v1/analysis/llm-advice` | Get investment advice with context |
| POST | `/api/v1/analysis/llm-news-analysis` | Analyze latest news impact |
| POST | `/api/v1/analysis/portfolio-design` | Generate portfolio design (see `portfolio/design.md`) |

---

## 2. LLM Report / LLM 分析报告

```
POST /api/v1/analysis/llm-report
```

**请求体 / Request Body:**

```json
{
  "symbols": ["510050", "510880"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbols | array of string | Yes | Target symbols to analyze |

**成功响应 / Success Response — `200 OK`:**

```json
{
  "report": "Detailed LLM-generated analysis...",
  "symbols": ["510050", "510880"],
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 3. LLM Advice / LLM 投资建议

```
POST /api/v1/analysis/llm-advice?query=<question>
```

**查询参数 / Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | Yes | Natural language question |

**请求体 / Request Body:** Arbitrary context data passed as JSON payload.

**成功响应 / Success Response — `200 OK`:**

```json
{
  "advice": "LLM-generated advice...",
  "query": "当前应该加仓还是减仓？",
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 4. LLM News Analysis / LLM 资讯分析

```
POST /api/v1/analysis/llm-news-analysis
```

**请求体:** Empty (uses server-side fetched news).

**成功响应 / Success Response — `200 OK`:**

```json
{
  "analysis": "News impact analysis...",
  "key_events": ["event1", "event2"],
  "disclaimer": "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负"
}
```

---

## 5. 错误码 / Error Codes

| Code | Meaning | When |
|------|---------|------|
| 400 | Bad Request | Missing required fields |
| 502 | Bad Gateway | LLM API call failed |
| 500 | Internal Server Error | Unexpected error |

---

## 5.1 变更记录 / Changelog (F1-3 / F1-4 / F1-7)

### market 参数（F1-4）

`llm-report` 与 `llm-advice` 请求体均支持 `market` 字段（`A` | `HK` | `US`，默认 `A`）：

```json
{ "symbols": ["^HSI"], "market": "HK" }
```

| market | index_realtime 来源 | sector_momentum |
|--------|--------------------|-----------------|
| `A`    | 本地指数缓存（上证/深成/创业板等） | 采集 A 股板块动量 |
| `HK`   | 全球指数分组「港股」（恒生/恒生科技等） | 不采集（无本地板块数据） |
| `US`   | 全球指数分组「美股」（标普/纳指/道指） | 不采集 |

### LLM 输出过滤（F1-7）

所有流式/非流式 LLM 输出的 `full_text` / `content` 均经过
`strip_internal_leak` 过滤：系统提示词泄漏片段（如「我们只需要回答…」、
reasoning_content 复述）被整行剔除。**前端无需变更**，仅保证最终文本不含
内部指令。

---

## 6. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `llm-report` accepts symbols array | ☐ | ☐ | |
| `llm-advice` accepts query param | ☐ | ☐ | |
| `llm-news-analysis` returns analysis | ☐ | ☐ | |
| All endpoints handle LLM timeout gracefully | ☐ | ☐ | |
| Loading state for all 3 endpoints | ☐ | N/A | |
| Error state on 502 (LLM failure) | ☐ | N/A | |
| All AI responses include disclaimer field | ☐ | ☐ | "本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负" |
| Frontend displays disclaimer below AI output | ☐ | N/A | |
