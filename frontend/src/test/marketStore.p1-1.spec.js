/**
 * P1-1 (round16 3.9 B4): 行情 WS 推送消费——market_refresh 广播
 * {type:'realtime', data:[{symbol,price,change_pct},...]} 应更新 realtimeData
 * （负向：推送不消费 → realtimeData 不更新 → FAIL）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../api', () => ({ marketApi: {} }))
vi.mock('../utils/logger', () => ({ default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() } }))

let wsInstance = null
class FakeWebSocket {
  static OPEN = 1
  constructor(url) {
    this.url = url
    this.readyState = 1
    wsInstance = this
  }
  send() {}
  close() { this.onclose && this.onclose() }
}

describe('market store — P1-1 行情 WS 推送消费', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    wsInstance = null
    globalThis.WebSocket = FakeWebSocket
  })

  it('realtime 推送数组 → realtimeData 按 symbol 更新价格/涨跌幅', async () => {
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.realtimeData = [
      { symbol: '510300', price: 4.0, change_pct: 0.1 },
      { symbol: '00700', price: 470, change_pct: -0.5 },
    ]
    store.connectWS()
    // 模拟后端 market_refresh 广播 {type:'realtime', data:[...]}
    wsInstance.onmessage({ data: JSON.stringify({
      type: 'realtime',
      data: [
        { symbol: '510300', price: 4.05, change_pct: 0.35 },
        { symbol: '00700', price: 468, change_pct: -0.8 },
      ],
    }) })
    const updated = store.realtimeData
    expect(updated.find(i => i.symbol === '510300')).toMatchObject({ price: 4.05, change_pct: 0.35 })
    expect(updated.find(i => i.symbol === '00700')).toMatchObject({ price: 468, change_pct: -0.8 })
  })

  it('realtime 推送未包含的 symbol 不崩溃', async () => {
    // 负向：推送符号不在列表中 → 不抛错、列表不变（round35 §16.6 空心测试修复：
    // 原为恒绿空测试体；store 语义 = 未持仓 symbol 不入列，仅更新已有行）
    const { useMarketStore } = await import('../stores/market')
    const store = useMarketStore()
    store.realtimeData = [
      { symbol: '510300', price: 4.05, change_pct: 0.35 },
    ]
    store.connectWS() // 本用例自建 WS 连接（beforeEach 重置 wsInstance=null）
    wsInstance.onmessage({ data: JSON.stringify({
      type: 'realtime',
      data: [
        { symbol: '999999', price: 9.99, change_pct: +1.0 },  // 不在列表
        { symbol: '510300', price: 4.06, change_pct: 0.5 },   // 已有行正常更新
      ],
    }) })
    const updated = store.realtimeData
    expect(updated.find(i => i.symbol === '999999')).toBeUndefined()
    expect(updated.find(i => i.symbol === '510300')).toMatchObject({ price: 4.06, change_pct: 0.5 })
    expect(updated.filter(i => i.symbol === '510300')).toHaveLength(1)
  })
})
