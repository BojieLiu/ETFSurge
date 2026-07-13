import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useNewsWS } from './useNewsWS'

// Fake WebSocket that captures handlers and lets tests drive lifecycle events.
class FakeWebSocket {
  static instances = []
  constructor(url) {
    this.url = url
    this.readyState = 0
    this.sent = []
    FakeWebSocket.instances.push(this)
  }
  get OPEN() { return 1 }
  send(data) { this.sent.push(data) }
  close() {
    this.readyState = 3
    if (this.onclose) this.onclose()
  }
  // test helpers
  _open() { this.readyState = 1; if (this.onopen) this.onopen() }
  _message(data) { if (this.onmessage) this.onmessage({ data }) }
}

describe('useNewsWS', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('connects to the /ws/news endpoint', () => {
    const { connect } = useNewsWS()
    connect()
    expect(FakeWebSocket.instances.length).toBe(1)
    expect(FakeWebSocket.instances[0].url).toContain('/ws/news')
  })

  it('forwards parsed messages to the registered handler', () => {
    const handler = vi.fn()
    const { connect, onNews } = useNewsWS()
    onNews(handler)
    connect()
    const ws = FakeWebSocket.instances[0]
    ws._open()
    ws._message(JSON.stringify({ type: 'news', data: { id: 1, title: 'x' } }))
    expect(handler).toHaveBeenCalledWith({ type: 'news', data: { id: 1, title: 'x' } })
  })

  it('ignores pong heartbeat frames', () => {
    const handler = vi.fn()
    const { connect, onNews } = useNewsWS()
    onNews(handler)
    connect()
    FakeWebSocket.instances[0]._message(JSON.stringify({ type: 'pong' }))
    expect(handler).not.toHaveBeenCalled()
  })
})
