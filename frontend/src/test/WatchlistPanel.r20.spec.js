/**
 * round24 R20: 美股/HK 自选实时不可用 → 显式降级标注（docs/round24 §12.3 R20）。
 *
 * 问题（round24 §4 步骤5 实证）：QQQ/AAPL/SPY realtime.price=null，旧 UI 只显示
 * 「行情加载中」——用户无法分辨「没波动」vs「没数据」（F21 未实施）。
 *
 * 验收：
 * ① realtime_unavailable=true → 显示「暂无实时」（非静默 null）；
 * ② realtime.is_estimated（T-1 收盘兜底）→ 价格带「估」徽标；
 * ③ A 股正常实时 → 精确价格，无「估」徽标。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('../api', () => ({ marketApi: {} }))
vi.mock('../stores/market', () => ({
  useMarketStore: () => ({
    watchlist: [], items: [], loading: false, fetchWatchlist: vi.fn(), addWatchlist: vi.fn(),
    removeWatchlist: vi.fn(), updateNotes: vi.fn(),
  }),
}))
vi.mock('./TechnicalAnalysisModal.vue', () => ({
  default: { name: 'TechnicalAnalysisModal', props: ['symbol', 'name', 'assetType'],
             template: '<div data-testid="ta-modal" />' },
}))

import WatchlistPanel from '../components/market/WatchlistPanel.vue'

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

describe('WatchlistPanel — R20 美股/HK 实时降级显式标注', () => {
  beforeEach(() => vi.clearAllMocks())

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