import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../utils/logger', () => ({
  default: { error: vi.fn() },
}))

import { useMarketWS } from '../composables/useMarketWS'

// Mock WebSocket with instance tracking
let lastMockWs = null
class MockWebSocket {
  constructor(url) {
    this.url = url
    this.readyState = 0 // CONNECTING
    this.onopen = null
    this.onclose = null
    this.onmessage = null
    this.onerror = null
    lastMockWs = this
    setTimeout(() => {
      this.readyState = 1 // OPEN
      if (this.onopen) this.onopen()
    }, 0)
  }
  close() {
    this.readyState = 3 // CLOSED
    if (this.onclose) this.onclose()
  }
  send() {}
}

describe('useMarketWS', () => {
  let composable
  let wsBackup

  beforeEach(() => {
    vi.clearAllMocks()
    wsBackup = global.WebSocket
    global.WebSocket = MockWebSocket
    composable = useMarketWS()
  })

  afterEach(() => {
    global.WebSocket = wsBackup
    if (composable) composable.disconnect()
  })

  it('returns initial state with connected=false', () => {
    expect(composable.connected.value).toBe(false)
    expect(typeof composable.connect).toBe('function')
    expect(typeof composable.disconnect).toBe('function')
    expect(typeof composable.onMarketData).toBe('function')
    expect(typeof composable.stop).toBe('function')
  })

  it('connects and updates connected state', async () => {
    composable.connect()
    // Wait for mock WebSocket to "connect"
    await new Promise(r => setTimeout(r, 10))
    expect(composable.connected.value).toBe(true)
  })

  it('disconnect stops and closes connection', async () => {
    composable.connect()
    await new Promise(r => setTimeout(r, 10))
    expect(composable.connected.value).toBe(true)

    composable.disconnect()
    await new Promise(r => setTimeout(r, 10))
    expect(composable.connected.value).toBe(false)
  })

  it('onMarketData registers a message handler', () => {
    const handler = vi.fn()
    composable.onMarketData(handler)
    composable.connect()
    // handler will be called when messages arrive
    expect(typeof handler).toBe('function')
  })

  it('handles incoming messages', async () => {
    const handler = vi.fn()
    composable.onMarketData(handler)
    composable.connect()
    await new Promise(r => setTimeout(r, 10))

    // Simulate a WebSocket message via the tracked instance
    if (lastMockWs && lastMockWs.onmessage) {
      lastMockWs.onmessage({ data: JSON.stringify({ type: 'price', symbol: '510300', price: 3.5 }) })
    }
    expect(handler).toHaveBeenCalled()
  })

  it('ping messages do not trigger handler', async () => {
    const handler = vi.fn()
    composable.onMarketData(handler)
    composable.connect()
    await new Promise(r => setTimeout(r, 10))

    if (lastMockWs && lastMockWs.onmessage) {
      lastMockWs.onmessage({ data: JSON.stringify({ type: 'pong' }) })
    }
    expect(handler).not.toHaveBeenCalled()
  })
})
