/**
 * round35 §12.7-B 第一步：定时行情推送链路删除后的 WS 消费契约守卫。
 *
 * 背景：APScheduler 定时推送 {type:'realtime'} 已删（调度决策 B，一个月无生产
 * 消息），market.js 的消费分支同批移除，行情更新走 REST TTL 轮询。
 * 本 spec 钉死删除后的行为：
 * - 负向：{type:'realtime'} 死格式必须被忽略——若分支复活/残留半截逻辑导致
 *   数据变异，本断言红（防「删了一半」）；
 * - 正向：portfolio_changed 防抖联动仍工作（红线：决策 B 绝不碰它）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { FakeWebSocket } from './helpers/fakeWebSocket' // round35 T-P1#8: 共享基建

vi.mock('../api', () => ({ marketApi: {} }))
vi.mock('../utils/logger', () => ({ default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() } }))

const fetchEtfs = vi.fn().mockResolvedValue([])
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ fetchEtfs }),
}))

let wsInstance = null
// 构造捕获子类：保持既有 wsInstance 用法不变（实现体已收敛到共享 helper）
class WS extends FakeWebSocket {
  constructor(url) {
    super(url)
    wsInstance = this
  }
}

describe('market store — §12.7-B 删除定时行情推送后的 WS 契约', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    wsInstance = null
    fetchEtfs.mockClear()
    globalThis.WebSocket = WS
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('{type:"realtime"} 死格式被忽略——realtimeData 不被变异（防分支复活/删一半）', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    const before = [
      { symbol: '510300', price: 4.0, change_pct: 0.1 },
    ]
    store.realtimeData = JSON.parse(JSON.stringify(before))
    store.connectWS()
    wsInstance.onmessage({ data: JSON.stringify({
      type: 'realtime',
      data: [{ symbol: '510300', price: 9.99, change_pct: 8.88 }],
    }) })
    expect(store.realtimeData[0]).toEqual(before[0])
  })

  it('portfolio_changed 广播仍触发防抖联动刷新（红线语义保持）', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.connectWS()
    wsInstance.onmessage({ data: JSON.stringify({ type: 'portfolio_changed' }) })
    expect(fetchEtfs).not.toHaveBeenCalled() // 1s 防抖窗口内未触发
    await vi.advanceTimersByTimeAsync(1100)
    expect(fetchEtfs).toHaveBeenCalledWith('on_exchange')
    expect(fetchEtfs).toHaveBeenCalledWith('off_exchange')
  })
})

// ── Round34 B4 / R119: 批量行情合并刷新（循环外一次性赋值）─────────────

describe('market store — R119 批量行情合并刷新', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = WS
  })

  it('同一微任务内 N 条 symbol 消息只做一次数组替换，且全部生效', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.realtimeData = [
      { symbol: '510300', price: 4.0, change_pct: 0.1 },
      { symbol: '518880', price: 7.0, change_pct: -0.2 },
      { symbol: '511010', price: 100.0, change_pct: 0.0 },
    ]
    const replacements = []
    // 以「引用变化」计数数组替换次数（响应式赋值即换引用）
    let lastRef = store.realtimeData
    store.$subscribe(() => {
      if (store.realtimeData !== lastRef) {
        replacements.push(1)
        lastRef = store.realtimeData
      }
    })
    store.connectWS()
    // 模拟 50 条批量推送（同微任务窗口内）
    for (let i = 0; i < 50; i++) {
      wsInstance.onmessage({ data: JSON.stringify({ symbol: '510300', price: 4.5, change_pct: 1.2 }) })
      wsInstance.onmessage({ data: JSON.stringify({ symbol: '518880', price: 7.5, change_pct: -1.0 }) })
    }
    await Promise.resolve() // 微任务 flush
    await Promise.resolve()
    expect(replacements.length).toBeLessThanOrEqual(2) // ≤2 次（旧实现 100 次）
    const row = store.realtimeData.find((x) => x.symbol === '510300')
    expect(row.price).toBe(4.5)
    expect(row.change_pct).toBe(1.2)
    expect(store.realtimeData.find((x) => x.symbol === '511010').price).toBe(100.0) // 未涉及行不动
  })

  it('未知 symbol 的消息不触发数组替换（changed 守卫）', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.realtimeData = [{ symbol: '510300', price: 4.0, change_pct: 0.1 }]
    const before = store.realtimeData
    store.connectWS()
    wsInstance.onmessage({ data: JSON.stringify({ symbol: 'UNKNOWN', price: 1.0, change_pct: 0 }) })
    await Promise.resolve()
    await Promise.resolve()
    expect(store.realtimeData).toBe(before) // 引用未变 → 零替换
  })
})
