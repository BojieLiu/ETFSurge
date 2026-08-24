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
