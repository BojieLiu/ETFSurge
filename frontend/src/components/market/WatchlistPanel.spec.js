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

  it('doSearch passes include_stocks:true + market 随 tab（默认 A tab 过滤为 A）', async () => {
    vi.useFakeTimers()
    apiMock.search.mockResolvedValue({ data: [{ market: 'US', symbol: 'AAPL', name: '苹果' }] })
    wrapper.vm.form.symbol = 'AAPL'
    await wrapper.vm.doSearch()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(apiMock.search).toHaveBeenCalledWith('AAPL', { include_stocks: true, market: 'A' })
    expect(wrapper.vm.suggestions.length).toBeGreaterThan(0)
    vi.useRealTimers()
  })

  it('doSearch 在 HK tab 下传 market=HK（补全不再混入 A 股标的）', async () => {
    vi.useFakeTimers()
    apiMock.search.mockResolvedValue({ data: [{ market: 'HK', symbol: '00700', name: '腾讯控股' }] })
    await wrapper.setProps({ marketTab: 'HK' })
    wrapper.vm.form.symbol = '0070'
    await wrapper.vm.doSearch()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(apiMock.search).toHaveBeenCalledWith('0070', { include_stocks: true, market: 'HK' })
    vi.useRealTimers()
  })

  it('selectSuggestion 选中 US 标的 → 输入框回填「代码+名称」且 form.asset_type 为 US', async () => {
    await flushPromises()
    wrapper.vm.suggestions = [{ market: 'US', symbol: 'AAPL', name: '苹果' }]
    wrapper.vm.selectSuggestion(wrapper.vm.suggestions[0])
    expect(wrapper.vm.form.symbol).toBe('AAPL 苹果') // 输入框显示「代码 + 名称」
    expect(wrapper.vm.form.name).toBe('苹果')
    expect(wrapper.vm.form.asset_type).toBe('US')
  })

  it('selectSuggestion 选中 HK 标的 → 输入框回填「代码+名称」且 form.asset_type 为 HK', async () => {
    await flushPromises()
    wrapper.vm.suggestions = [{ market: 'HK', symbol: '00700', name: '腾讯控股' }]
    wrapper.vm.selectSuggestion(wrapper.vm.suggestions[0])
    expect(wrapper.vm.form.symbol).toBe('00700 腾讯控股')
    expect(wrapper.vm.form.name).toBe('腾讯控股')
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
