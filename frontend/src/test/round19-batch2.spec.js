/**
 * round19 批次 2 测试（2026-08-12）：
 * - P6-①/② WS 全站常驻（App.vue 建连）+ wsStatus 五态状态机（market.js）
 * - P2-② portfolio_changed 广播消费（防抖 1s 触发 portfolio store 刷新）
 *
 * 对照 §二十六 T1/T2（负向：disconnectWS 后仍 connected → FAIL；stopped 时仍渲染「离线」→ FAIL）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

vi.mock('../api', () => ({ marketApi: {}, portfolioApi: { list: vi.fn() } }))
vi.mock('../utils/logger', () => ({ default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() } }))

let wsInstance = null
class FakeWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSING = 2
  static CLOSED = 3
  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.OPEN
    wsInstance = this
  }
  send() {}
  close() { this.onclose && this.onclose() }
}

describe('market store — wsStatus 五态状态机（round19 P6-②）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = FakeWebSocket
  })

  it('初始 idle → connectWS 后 connecting → onopen 后 connected', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    expect(store.wsStatus).toBe('idle')
    store.connectWS()
    expect(store.wsStatus).toBe('connecting')
    wsInstance.onopen()
    expect(store.wsStatus).toBe('connected')
  })

  it('disconnectWS → stopped（负向：主动断开仍显示 connected → FAIL）', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.connectWS()
    wsInstance.onopen()
    expect(store.wsStatus).toBe('connected')
    store.disconnectWS()
    expect(store.wsStatus).toBe('stopped')
    expect(store.wsConnected).toBe(false)
  })

  it('onclose 后进入 reconnecting（自动重连中，非故障「离线」）', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.connectWS()
    wsInstance.onopen()
    wsInstance.onclose()
    expect(store.wsStatus).toBe('reconnecting')
    store.disconnectWS() // 清理重连定时器，避免测试悬挂
  })
})

describe('market store — portfolio_changed 广播消费（round19 P2-②）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = FakeWebSocket
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('收到 portfolio_changed → 防抖 1s 后触发 portfolio store fetchEtfs 双 tab', async () => {
    const { portfolioApi } = await import('../api')
    portfolioApi.list.mockResolvedValue({ data: [] })
    const { useMarketStore } = await import('../stores/market')
    const { usePortfolioStore } = await import('../stores/portfolio')
    const store = useMarketStore()
    const pstore = usePortfolioStore()
    store.connectWS()
    // 收到结构变更广播
    wsInstance.onmessage({ data: JSON.stringify({
      type: 'portfolio_changed',
      data: { portfolio_type: 'on_exchange', symbol: '510300' },
    }) })
    expect(portfolioApi.list).not.toHaveBeenCalled() // 防抖期内不立即刷
    await vi.advanceTimersByTimeAsync(1100)
    expect(portfolioApi.list).toHaveBeenCalledWith('on_exchange')
    expect(portfolioApi.list).toHaveBeenCalledWith('off_exchange')
    expect(pstore.onExchange).toEqual([])
    store.disconnectWS()
  })

  it('realtime 消息不触发 portfolio 刷新（仅结构变更走该分支）', async () => {
    const { portfolioApi } = await import('../api')
    portfolioApi.list.mockResolvedValue({ data: [] })
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.realtimeData = [{ symbol: '510300', price: 4.0 }]
    store.connectWS()
    wsInstance.onmessage({ data: JSON.stringify({
      type: 'realtime',
      data: [{ symbol: '510300', price: 4.05 }],
    }) })
    await vi.advanceTimersByTimeAsync(1500)
    expect(portfolioApi.list).not.toHaveBeenCalled()
    store.disconnectWS()
  })
})

describe('App.vue 导航栏状态文案（round19 P6-①/②，源码断言）', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'App.vue'), 'utf-8')

  it('不再有「离线」文案（stopped/idle 显示中性态，负向：仍渲染「离线」→ FAIL）', () => {
    expect(src).not.toMatch(/case 'disconnected': return '离线'/)
    expect(src).toMatch(/case 'stopped': return '行情连接未启用'/)
    expect(src).toMatch(/case 'idle': return ''/)
  })

  it('App.vue onMounted 建立全站连接（连接职责从 Dashboard 移交）', () => {
    expect(src).toMatch(/marketStore\.connectWS\(\)/)
    expect(src).toMatch(/marketStore\.disconnectWS\(\)/)
  })

  it('Dashboard.vue 不再 connect/disconnect（改注册/注销消费回调）', () => {
    const dSrc = fs.readFileSync(path.join(__dirname, '..', 'views', 'Dashboard.vue'), 'utf-8')
    expect(dSrc).not.toMatch(/marketStore\.connectWS\(/)
    expect(dSrc).not.toMatch(/marketStore\.disconnectWS\(\)/)
    expect(dSrc).toMatch(/marketStore\.onWSMessage\(updateGlobalIndicesFromWS\)/)
    expect(dSrc).toMatch(/marketStore\.offWSMessage\(updateGlobalIndicesFromWS\)/)
  })
})

describe('PortfolioManager 快照层移除（round19 P2-①，源码断言）', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'components', 'PortfolioManager.vue'), 'utf-8')

  it('cachedEtfs 快照层已移除（分页由响应式 currentEtfs 派生）', () => {
    // 允许注释提及，但不得有快照声明/同步行
    expect(src).not.toMatch(/const cachedEtfs = ref/)
    expect(src).not.toMatch(/cachedEtfs\.value\s*=/)
    expect(src).toMatch(/paginatedEtfs = computed\(\(\) => \{/)
  })

  it('onAdd/onRemove 后同步 loadTab（PnL 数据一致）', () => {
    const onAddBody = src.slice(src.indexOf('async function onAdd'), src.indexOf('async function onRemove'))
    expect(onAddBody).toMatch(/await loadTab\(\)/)
    const onRemoveBody = src.slice(src.indexOf('async function onRemove'), src.indexOf('async function autoDistributeWeights'))
    expect(onRemoveBody).toMatch(/await loadTab\(\)/)
  })
})
