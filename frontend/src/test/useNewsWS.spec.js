import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useNewsWS } from '../composables/useNewsWS'
import { FakeWebSocket } from './helpers/fakeWebSocket' // round35 T-P1#8: 共享基建

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
