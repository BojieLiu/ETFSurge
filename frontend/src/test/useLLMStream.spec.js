import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/utils/logger', () => ({
  default: { error: vi.fn() },
}))

import { useLLMStream } from '../composables/useLLMStream'

describe('useLLMStream', () => {
  let composable

  beforeEach(() => {
    vi.clearAllMocks()
    composable = useLLMStream()
  })

  it('returns initial state correctly', () => {
    expect(composable.streaming.value).toBe(false)
    expect(composable.fullText.value).toBe('')
    expect(composable.error.value).toBeNull()
    expect(composable.metadata.value).toBeNull()
    expect(composable.disclaimer.value).toBe('')
  })

  it('stop() aborts and sets streaming to false', () => {
    composable.streaming.value = true
    composable.stop()
    expect(composable.streaming.value).toBe(false)
  })

  it('start() fails on network error', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
    await expect(composable.start('test', {})).rejects.toThrow()
    expect(global.fetch).toHaveBeenCalled()
  })

  it('handles HTTP error response', async () => {
    const mockResponse = {
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: 'Server error' }),
    }
    global.fetch = vi.fn().mockResolvedValue(mockResponse)
    await expect(composable.start('/report', {})).rejects.toThrow('Server error')
  })

  it('handles SSE stream with token and done events', async () => {
    const encoder = new TextEncoder()
    const streamData = [
      'event: token\ndata: {"token":"Hello"}\n\n',
      'event: token\ndata: {"token":" World"}\n\n',
      'event: done\ndata: {"full_text":"Hello World","metadata":{"model":"test"},"disclaimer":"Test disclaimer"}\n\n',
    ]
    let index = 0
    const mockReader = {
      read: vi.fn().mockImplementation(() => {
        if (index < streamData.length) {
          return Promise.resolve({
            done: false,
            value: encoder.encode(streamData[index++]),
          })
        }
        return Promise.resolve({ done: true, value: undefined })
      }),
    }
    const mockResponse = {
      ok: true,
      body: { getReader: () => mockReader },
    }
    global.fetch = vi.fn().mockResolvedValue(mockResponse)

    const onToken = vi.fn()
    const result = await composable.start('/report', {}, onToken)

    expect(onToken).toHaveBeenCalledTimes(2)
    expect(onToken).toHaveBeenNthCalledWith(1, 'Hello')
    expect(onToken).toHaveBeenNthCalledWith(2, ' World')
    expect(result.fullText).toBe('Hello World')
    expect(result.metadata).toEqual({ model: 'test' })
    expect(result.disclaimer).toBe('Test disclaimer')
    expect(composable.streaming.value).toBe(false)
  })

  it('handles SSE error event gracefully', async () => {
    const encoder = new TextEncoder()
    let callCount = 0
    const mockReader = {
      read: vi.fn().mockImplementation(() => {
        callCount++
        if (callCount === 1) {
          return Promise.resolve({
            done: false,
            value: encoder.encode('event: error\ndata: {"message":"API error"}\n\n'),
          })
        }
        return Promise.resolve({ done: true, value: undefined })
      }),
    }
    const mockResponse = {
      ok: true,
      body: { getReader: () => mockReader },
    }
    global.fetch = vi.fn().mockResolvedValue(mockResponse)

    const onToken = vi.fn()
    // SSE error events are logged internally; stream ends gracefully
    const result = await composable.start('/report', {}, onToken)
    expect(composable.streaming.value).toBe(false)
    expect(composable.fullText.value).toBe('')
  })
})
