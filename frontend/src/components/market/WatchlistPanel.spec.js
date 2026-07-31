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

describe('WatchlistPanel — Z29 asset_type backfill', () => {
  let wrapper

  beforeEach(() => {
    vi.clearAllMocks()
    wrapper = mount(WatchlistPanel)
  })

  it('doSearch passes include_stocks:true (自选可搜到个股)', async () => {
    vi.useFakeTimers()
    apiMock.search.mockResolvedValue({ data: [{ market: 'US', symbol: 'AAPL', name: '苹果' }] })
    wrapper.vm.form.symbol = 'AAPL'
    await wrapper.vm.doSearch()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(apiMock.search).toHaveBeenCalledWith('AAPL', { include_stocks: true })
    expect(wrapper.vm.suggestions.length).toBeGreaterThan(0)
    vi.useRealTimers()
  })

  it('selectSuggestion 选中 US 标的 → form.asset_type 回填为 US', async () => {
    await flushPromises()
    wrapper.vm.suggestions = [{ market: 'US', symbol: 'AAPL', name: '苹果' }]
    wrapper.vm.selectSuggestion(wrapper.vm.suggestions[0])
    expect(wrapper.vm.form.symbol).toBe('AAPL')
    expect(wrapper.vm.form.asset_type).toBe('US')
  })

  it('selectSuggestion 选中 HK 标的 → form.asset_type 回填为 HK', async () => {
    await flushPromises()
    wrapper.vm.suggestions = [{ market: 'HK', symbol: '00700', name: '腾讯控股' }]
    wrapper.vm.selectSuggestion(wrapper.vm.suggestions[0])
    expect(wrapper.vm.form.symbol).toBe('00700')
    expect(wrapper.vm.form.asset_type).toBe('HK')
  })

  it('selectSuggestion 选中 A 股标的 → form.asset_type 回落 A（即使之前是 US）', async () => {
    await flushPromises()
    wrapper.vm.form.asset_type = 'US' // 模拟先选了 AAPL
    wrapper.vm.suggestions = [{ market: 'A', symbol: '600519', name: '贵州茅台' }]
    wrapper.vm.selectSuggestion(wrapper.vm.suggestions[0])
    expect(wrapper.vm.form.asset_type).toBe('A')
  })
})
