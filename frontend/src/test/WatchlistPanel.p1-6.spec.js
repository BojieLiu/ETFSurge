/**
 * P1-6 (round16 3.17): 自选列表行内「📈 技术 + 🤖 AI 分析」按钮。
 *
 * 验收:
 * ① 每行显示技术/AI 按钮；
 * ② 点击技术 → TechnicalAnalysisModal 打开，assetType 按 item.asset_type 推断
 *    （A/HK/US 混合自选必须——HK 标的 assetType=HK，US 标的=US）；
 * ③ 点击 AI → emit analyze（symbol 模式）。
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
  default: {
    name: 'TechnicalAnalysisModal',
    props: ['symbol', 'name', 'assetType'],
    template: '<div data-testid="ta-modal">{{ assetType }}</div>',
  },
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
describe('WatchlistPanel — P1-6 行内技术/AI 按钮', () => {
  beforeEach(() => vi.clearAllMocks())

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
