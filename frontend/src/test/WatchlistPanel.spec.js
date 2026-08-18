/**
 * WatchlistPanel 测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - Z29：搜索 include_stocks/market 随 tab + selectSuggestion asset_type 回填
 * - P0-3：_degraded=true 且无 realtime →「行情暂不可用」而非「加载中」
 * - P1-6：行内「技术/AI 分析」按钮 + assetType 推断 + analyze emit
 * - R20：美股/HK 实时不可用显式降级标注（暂无实时/估/—）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const apiMock = vi.hoisted(() => ({ search: vi.fn() }))
vi.mock('../api', () => ({
  marketApi: { search: (...a) => apiMock.search(...a) },
}))

const storeMock = vi.hoisted(() => ({
  watchlist: [],
  items: [],
  loading: false,
  fetchWatchlist: vi.fn().mockResolvedValue(),
  addWatchlist: vi.fn().mockResolvedValue(),
  removeWatchlist: vi.fn().mockResolvedValue(),
  updateWatchlist: vi.fn().mockResolvedValue(),
  updateNotes: vi.fn(),
}))
vi.mock('../stores/market', () => ({
  useMarketStore: () => storeMock,
}))

vi.mock('../components/market/TechnicalAnalysisModal.vue', () => ({
  default: {
    name: 'TechnicalAnalysisModal',
    props: ['symbol', 'name', 'assetType'],
    template: '<div data-testid="ta-modal">{{ assetType }}</div>',
  },
}))

import WatchlistPanel from '../components/market/WatchlistPanel.vue'

// 防跨文件合并后测试间污染：watchlist/items 状态在每用例前重置
beforeEach(() => {
  vi.clearAllMocks()
  storeMock.watchlist = []
  storeMock.items = []
})

describe('WatchlistPanel — Z29 asset_type backfill', () => {
  let wrapper

  beforeEach(() => {
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

describe('WatchlistPanel — P0-3 (round20) 降级状态修复', () => {
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

async function mountWithItems(items, marketTab = 'A') {
  const wrapper = mount(WatchlistPanel, {
    props: { marketTab },
    global: { stubs: { AppModal: { template: '<div><slot /></div>' } } },
  })
  await flushPromises() // 等 onMounted fetchItems 完成（避免覆盖）
  wrapper.vm.items = items
  await flushPromises()
  return wrapper
}

describe('WatchlistPanel — P1-6 行内技术/AI 按钮', () => {
  it('每行显示技术/AI 按钮', async () => {
    const wrapper = await mountWithItems([
      { id: 1, symbol: '510300', name: '沪深300ETF', asset_type: 'A', realtime: null, notes: '' },
    ])
    await flushPromises()
    const actions = wrapper.findAll('.row-actions button')
    const titles = actions.map(b => b.attributes('title'))
    expect(titles).toContain('技术分析')
    expect(titles).toContain('AI 分析')
  })

  it('HK 标的点击技术 → assetType=HK', async () => {
    const wrapper = await mountWithItems([
      { id: 1, symbol: '00700', name: '腾讯控股', asset_type: 'HK', realtime: null, notes: '' },
    ], 'HK')
    await flushPromises()
    const techBtn = wrapper.findAll('.row-actions button').find(b => b.attributes('title') === '技术分析')
    await techBtn.trigger('click')
    await flushPromises()
    expect(wrapper.vm.techModal).toBeTruthy()
    expect(wrapper.vm.techModal.assetType).toBe('HK')
  })

  it('US 标的点击技术 → assetType=US', async () => {
    const wrapper = await mountWithItems([
      { id: 1, symbol: 'AAPL', name: '苹果', asset_type: 'US', realtime: null, notes: '' },
    ], 'US')
    await flushPromises()
    const techBtn = wrapper.findAll('.row-actions button').find(b => b.attributes('title') === '技术分析')
    await techBtn.trigger('click')
    expect(wrapper.vm.techModal.assetType).toBe('US')
  })

  it('点击 AI → emit analyze（symbol 模式）', async () => {
    const wrapper = await mountWithItems([
      { id: 1, symbol: '510300', name: '沪深300ETF', asset_type: 'A', realtime: null, notes: '' },
    ])
    await flushPromises()
    const aiBtn = wrapper.findAll('.row-actions button').find(b => b.attributes('title') === 'AI 分析')
    await aiBtn.trigger('click')
    const emitted = wrapper.emitted('analyze')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toMatchObject({ mode: 'symbol', query: '510300', name: '沪深300ETF' })
  })
})

describe('WatchlistPanel — R20 美股/HK 实时降级显式标注', () => {
  it('realtime_unavailable=true → 显示「暂无实时」而非静默空白', async () => {
    const wrapper = await mountWithItems([
      { id: 1, symbol: 'QQQ', name: 'Invesco QQQ', asset_type: 'US',
        realtime: null, realtime_unavailable: true,
        realtime_note: '该市场数据源暂不可用（无实时行情）', notes: '' },
    ], 'US')
    await flushPromises()
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('QQQ'))
    expect(row.text()).toContain('暂无实时')
    expect(row.text()).not.toContain('行情加载中')
  })

  it('realtime.is_estimated（T-1 收盘兜底）→ 价格带「估」徽标', async () => {
    const wrapper = await mountWithItems([
      { id: 2, symbol: 'AAPL', name: '苹果', asset_type: 'US',
        realtime: { price: 210.5, change_pct: null, volume: null, is_estimated: true, estimate_source: 'last_close' },
        realtime_unavailable: true, notes: '' },
    ], 'US')
    await flushPromises()
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('AAPL'))
    expect(row.text()).toContain('210.50')
    expect(row.text()).toContain('估')
    // 收盘兜底无实时涨跌幅 → 涨跌幅列显示「—」而非空
    expect(row.text()).toContain('—')
  })

  it('A 股正常实时 → 精确价格，无「估」徽标、无「暂无实时」', async () => {
    const wrapper = await mountWithItems([
      { id: 3, symbol: '510300', name: '沪深300ETF', asset_type: 'A',
        realtime: { price: 3.987, change_pct: 0.23, volume: 12345 }, notes: '' },
    ], 'A')
    await flushPromises()
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('3.99')
    expect(row.text()).not.toContain('估')
    expect(row.text()).not.toContain('暂无实时')
    expect(row.text()).not.toContain('行情加载中')
  })

  it('realtime_unavailable 无 realtime → 涨跌幅/成交量列也显示「暂无实时」', async () => {
    const wrapper = await mountWithItems([
      { id: 4, symbol: 'SPY', name: 'SPDR S&P 500 ETF', asset_type: 'US',
        realtime: null, realtime_unavailable: true, notes: '' },
    ], 'US')
    await flushPromises()
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('SPY'))
    // 三列（价格/涨跌幅/成交量）均应有降级标注，不静默空白
    const unavailableCount = (row.text().match(/暂无实时/g) || []).length
    expect(unavailableCount).toBeGreaterThanOrEqual(2)
  })
})
