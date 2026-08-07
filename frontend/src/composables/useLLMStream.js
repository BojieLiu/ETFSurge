// SSE Streaming hook for LLM analysis endpoints
// Connects to /api/v1/analysis/*/stream endpoints and yields incremental tokens
import { ref } from 'vue'
import logger from '@/utils/logger'

const API_BASE = '/api/v1/analysis'

export function useLLMStream() {
  const streaming = ref(false)
  const fullText = ref('')
  const error = ref(null)
  const metadata = ref(null)
  const disclaimer = ref('')

  let abortController = null

  async function start(endpoint, body, onToken) {
    streaming.value = true
    fullText.value = ''
    error.value = null
    metadata.value = null
    disclaimer.value = ''

    abortController = new AbortController()
    const signal = abortController.signal

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal,
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(errData.detail || `HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          const [eventLine, dataLine] = line.split('\n')
          const event = eventLine?.replace('event: ', '').trim()
          const data = dataLine?.replace('data: ', '').trim()
          
          if (!data) continue

          try {
            const parsed = JSON.parse(data)
            
            if (event === 'token' && onToken) {
              onToken(parsed.token)
              fullText.value += parsed.token
            } else if (event === 'done') {
              fullText.value = parsed.full_text || fullText.value
              metadata.value = parsed.metadata || {}
              disclaimer.value = parsed.disclaimer || ''
              streaming.value = false
              return { fullText: fullText.value, metadata: metadata.value, disclaimer: disclaimer.value }
            } else if (event === 'error') {
              // O24 (round8 §7 §5.1K): SSE error 透传 code 标识——前端据此分类
              // 文案（[rate-limited]/429 → 请求过于频繁，[timeout] → 无响应，
              // DATA_UNAVAILABLE → 数据源暂不可用），而非笼统「网络错误」。
              const code = parsed.code ? `[${parsed.code}] ` : ''
              throw new Error(code + (parsed.message || 'Stream error'))
            }
          } catch (e) {
            logger.error('SSE parse error:', e, 'data:', data)
          }
        }
      }

      streaming.value = false
      return { fullText: fullText.value, metadata: metadata.value, disclaimer: disclaimer.value }
    } catch (e) {
      if (e.name === 'AbortError') return
      error.value = e.message
      streaming.value = false
      throw e
    }
  }

  function stop() {
    if (abortController) {
      abortController.abort()
    }
    streaming.value = false
  }

  return {
    streaming,
    fullText,
    error,
    metadata,
    disclaimer,
    start,
    stop,
  }
}