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
