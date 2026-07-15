# LLM SSE Streaming / LLM 服务端推送流式输出

## 1. 概述 / Overview

为所有 LLM 分析端点提供 Server-Sent Events (SSE) 流式输出，避免前端长时间阻塞等待（现有超时 180s）。客户端通过 `EventSource` 接收逐 token 增量内容。

Provide SSE streaming for all LLM analysis endpoints to avoid long blocking waits (current 180s timeout). Client receives incremental tokens via `EventSource`.

---

## 2. 端点定义 / Endpoints

### 2.1 市场研判报告流式 / Market Report Stream

```
POST /api/v1/analysis/llm-report/stream
```

### 2.2 投资建议问答流式 / Investment Advice Stream

```
POST /api/v1/analysis/llm-advice/stream
```

### 2.3 组合设计流式 / Portfolio Design Stream

```
POST /api/v1/analysis/portfolio-design/stream
```

### 2.4 板块分析流式 / Sector Analysis Stream

```
POST /api/v1/analysis/sector-analysis/stream
```

### 2.5 标的深度解读流式 / Symbol Analysis Stream

```
POST /api/v1/analysis/symbol-analysis/stream
```

### 2.6 资讯影响分析流式 / News Impact Stream

```
POST /api/v1/analysis/news-impact/stream
```

---

## 3. 请求体 / Request Body

与对应的非流式端点完全一致，仅路径添加 `/stream` 后缀。

Same as non-streaming counterpart, only path adds `/stream` suffix.

**示例 / Example (llm-advice):**

```json
{
  "query": "当前市场风格偏向成长还是价值？",
  "context": {
    "include_market_data": true,
    "include_news": true,
    "portfolio_symbols": ["159338", "510050"]
  }
}
```

---

## 4. 响应格式 / Response Format

### Content-Type

```
text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### SSE 事件流 / Event Stream

每个事件为一行 JSON，以 `\n\n` 结尾。字段说明：

| Event | Data | 说明 |
|-------|------|------|
| `token` | `{ "token": "..." }` | 单个 token 增量内容 |
| `done` | `{ "full_text": "...", "metadata": {...} }` | 流式结束，包含完整文本及元数据 |
| `error` | `{ "code": "...", "message": "..." }` | 流式过程发生错误 |

**流式示例 / Stream Example:**

```
event: token
data: {"token": "当"}

event: token
data: {"token": "前"}

event: token
data: {"token": "市"}

event: done
data: {"full_text": "当前市场...", "metadata": {"model": "deepseek-chat", "prompt_tokens": 1234, "completion_tokens": 567, "total_tokens": 1801, "latency_ms": 12500}}

event: error
data: {"code": "UPSTREAM_TIMEOUT", "message": "DeepSeek API timeout after 120s"}
```

### done 事件 metadata 字段

| Field | Type | Description |
|-------|------|-------------|
| model | string | LLM model name |
| prompt_tokens | int | Input tokens |
| completion_tokens | int | Output tokens |
| total_tokens | int | Total tokens |
| latency_ms | int | End-to-end latency in milliseconds |
| function_name | string | Calling function (for token usage tracking) |

---

## 5. 客户端接入指南 / Client Integration Guide

### JavaScript (EventSource)

```javascript
const evtSource = new EventSource('/api/v1/analysis/llm-report/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ symbols: ['159338'] })
});

// 注：EventSource 原生不支持 POST，需用 fetch + ReadableStream 或 polyfill
// 推荐使用 fetch + ReadableStream (见下方)
```

### 推荐：fetch + ReadableStream (原生支持 POST)

```javascript
async function* streamLLM(endpoint, body) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const [eventLine, dataLine] = line.split('\n');
      const event = eventLine.replace('event: ', '');
      const data = JSON.parse(dataLine.replace('data: ', ''));
      yield { event, data };
    }
  }
}

// 使用
for await (const { event, data } of streamLLM('/api/v1/analysis/llm-report/stream', { symbols: ['159338'] })) {
  if (event === 'token') {
    appendToUI(data.token);
  } else if (event === 'done') {
    console.log('Complete:', data.full_text);
  } else if (event === 'error') {
    console.error('Stream error:', data.message);
  }
}
```

### Vue 3 Composables (建议封装)

```javascript
// composables/useLLMStream.js
export function useLLMStream() {
  const streaming = ref(false);
  const fullText = ref('');
  const error = ref(null);

  async function start(endpoint, body, onToken) {
    streaming.value = true;
    fullText.value = '';
    error.value = null;

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        for (const ev of events) {
          if (!ev.trim()) continue;
          const [eventLine, dataLine] = ev.split('\n');
          const event = eventLine.replace('event: ', '');
          const data = JSON.parse(dataLine.replace('data: ', ''));
          if (event === 'token' && onToken) onToken(data.token);
          else if (event === 'done') { fullText.value = data.full_text; streaming.value = false; return data; }
          else if (event === 'error') { error.value = data.message; streaming.value = false; throw new Error(data.message); }
        }
      }
    } catch (e) {
      streaming.value = false;
      throw e;
    }
  }

  return { streaming, fullText, error, start };
}
```

---

## 6. 后端实现要点 / Backend Implementation Notes

1. 使用 `httpx.AsyncClient.stream()` 调用 DeepSeek API 的流式端点 (`stream: true`)
2. 逐 chunk 解析 `data: {...}`，提取 `choices[0].delta.content`
3. 通过 `yield` 发送 SSE 格式数据：`f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"`
4. 最后发送 `done` 事件，包含完整文本和 token usage
5. 异常时发送 `error` 事件并关闭流
6. 超时设置：总超时 180s，流式过程每 30s 至少要有一个 token/心跳，否则断开

---

## 7. 错误码 / Error Codes

| Status Code | Meaning | Description |
|-------------|---------|-------------|
| 200 | OK | SSE stream started successfully |
| 400 | Bad Request | Invalid request body |
| 500 | Internal Server Error | LLM service unavailable, stream aborted |
| 504 | Gateway Timeout | Upstream DeepSeek timeout |

---

## 8. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| Route matches (/stream suffix) | ☐ | ☐ | All 6 endpoints |
| Request body same as non-stream | ☐ | ☐ | No new fields |
| SSE Content-Type | N/A | ☐ | text/event-stream |
| Token events parsed | ☐ | N/A | Append incrementally |
| Done event captured | ☐ | N/A | Full text + metadata |
| Error event handled | ☐ | N/A | Show toast, stop spinner |
| Connection cleanup | ☐ | N/A | AbortController on unmount |
| Loading state | ☐ | N/A | Skeleton until first token |