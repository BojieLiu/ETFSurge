import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const apiMock = vi.hoisted(() => ({ search: vi.fn() }))
vi.mock('../../api', () => ({
  marketApi: { search: (...a) => apiMock.search(...a) },
}))

const storeMock = vi.hoisted(() => ({
  watchlist: [],
  fetchWatchlist: vi.fn().mockResolvedValue(),
  addWatchlist: vi.fn().mockResolvedValue(),
  removeWatchlist: vi.fn().mockResolvedValue(),
  updateWatchlist: vi.fn().mockResolvedValue(),
}))
vi.mock('../../stores/market', () => ({
  useMarketStore: () => storeMock,
}))

const WatchlistPanel = (await import('./WatchlistPanel.vue')).default

describe('WatchlistPanel — P0-3 (round20) 降级状态修复', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('_degraded=true 且无 realtime → 显示「行情暂不可用」（不是「行情加载中」）', async () => {
    // 后端 market.py:866-870 批量 realtime 失败时 realtime=null + _degraded=true（永久降级）
    storeMock.watchlist = [{
      id: 'hk1', symbol: '00700', name: '腾讯控股', asset_type: 'HK',
      realtime: null, _degraded: true, notes: '',
    }]
    const wrapper = mount(WatchlistPanel, { props: { marketTab: 'HK' } })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('行情暂不可用')
    // 负向断言：不得误标「加载中」（降级 ≠ 加载中，加载态另有 loading 分支）
    expect(text).not.toContain('行情加载中')
    // 不得渲染「—」冒充（formatPct(null) 对降级行也应走暂不可用文案）
    const degradedCells = wrapper.findAll('.muted')
    expect(degradedCells.length).toBeGreaterThan(0)
  })

  it('realtime 正常 → 仍显示实时价（降级文案不误伤正常行）', async () => {
    storeMock.watchlist = [{
      id: 'a1', symbol: '510300', name: '沪深300ETF', asset_type: 'A',
      realtime: { price: 4.02, change_pct: 1.23, volume: 123456 },
      _degraded: false, notes: '',
    }]
    const wrapper = mount(WatchlistPanel, { props: { marketTab: 'A' } })
    await flushPromises()
    expect(wrapper.text()).toContain('4.02')
    expect(wrapper.text()).not.toContain('行情暂不可用')
  })
})
