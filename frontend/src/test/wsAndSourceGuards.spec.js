/**
 * WS 状态机 + 源码级链路守卫（§7.2 归位合并，2026-08-18）。
 *
 * 合并自 round19-batch1/batch2：
 * - MarketAnalysis @analyze 绑定（P7-②）+ fetch_history 前缀归一化（P7-①）
 * - market store wsStatus 五态状态机 + portfolio_changed 广播消费（P6-②/P2-②）
 * - App.vue 全站 WS 建连 + 导航栏状态文案（P6-①/②）
 * - PortfolioManager 快照层移除（P2-①）
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')

vi.mock('../api', () => ({ marketApi: {}, portfolioApi: { list: vi.fn() } }))
vi.mock('../utils/logger', () => ({ default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() } }))

import { FakeWebSocket } from './helpers/fakeWebSocket' // round35 T-P1#8: 共享基建

let wsInstance = null
class WS extends FakeWebSocket {
  constructor(url) {
    super(url)
    wsInstance = this
  }
}


// ── round19 P7-②: MarketAnalysis @analyze 绑定 ──

describe('MarketAnalysis @analyze 绑定（round19 P7-②）', () => {
  const src = fs.readFileSync(path.join(srcRoot, 'views', 'MarketAnalysis.vue'), 'utf-8')

  it('WatchlistPanel 组件行绑定 @analyze="onQuickAnalyze"', () => {
    const line = src.split('\n').find((l) => l.includes('<WatchlistPanel'))
    expect(line).toBeTruthy()
    expect(line).toContain('@analyze="onQuickAnalyze"')
  })

  it('onQuickAnalyze 实现存在（滚动到分析区 + 触发 UnifiedAnalysis）', () => {
    expect(src).toContain('function onQuickAnalyze({ mode, query, name })')
    expect(src).toContain('externalTrigger.value = { mode, query, name }')
  })

  it('SectorHeatMap 对照绑定仍在（回归）', () => {
    const line = src.split('\n').find((l) => l.includes('<SectorHeatMap'))
    expect(line).toContain('@analyze="onQuickAnalyze"')
  })
})

// ── round19 P7-①: fetch_history 入口归一化 ──

describe('fetch_history 入口归一化（round19 P7-①）', () => {
  const src = fs.readFileSync(
    path.join(srcRoot, '..', '..', 'backend', 'app', 'fetchers', 'china_market.py'),
    'utf-8',
  )

  it('fetch_history 函数体首段含前缀剥离逻辑', () => {
    const fnStart = src.indexOf('def fetch_history(')
    const fnBody = src.slice(fnStart, fnStart + 1200)
    expect(fnBody).toMatch(/startswith\(\("sh", "sz", "bj"\)/)
    // review 修复（round23 审计前）：剥前缀仅限 A 股且用 str() 包裹（US 字母代码
    // SHOP/SHW 等不得剥）——断言放宽为匹配 str(symbol)[2:] 形式
    expect(fnBody).toMatch(/symbol = str\(symbol\)\[2:\]/)
  })
})

// ── round19 P6-②: market store wsStatus 五态状态机 ──

describe('market store — wsStatus 五态状态机（round19 P6-②）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = WS
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

// ── round19 P2-②: portfolio_changed 广播消费 ──

describe('market store — portfolio_changed 广播消费（round19 P2-②）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = WS
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

// ── round19 P6-①/②: App.vue 导航栏状态文案 ──

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

// ── round19 P2-①: PortfolioManager 快照层移除 ──

describe('PortfolioManager 快照层移除（round19 P2-①，源码断言）', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'components', 'portfolio', 'PortfolioManager.vue'), 'utf-8')

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
