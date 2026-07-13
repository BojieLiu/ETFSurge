import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const storeMock = vi.hoisted(() => ({
  onExchange: [
    { symbol: '510050', name: '上证50ETF', asset_type: 'A', target_weight: 0.3, portfolio_type: 'on_exchange' },
    { symbol: '510300', name: '沪深300ETF', asset_type: 'A', target_weight: 0.3, portfolio_type: 'on_exchange' },
  ],
  offExchange: [],
  etfs: [],
  fetchEtfs: vi.fn(() => Promise.resolve()),
  addEtf: vi.fn(() => Promise.resolve()),
  updateEtf: vi.fn(() => Promise.resolve()),
  removeEtf: vi.fn(() => Promise.resolve()),
}))

vi.mock('../stores/portfolio', () => ({ usePortfolioStore: () => storeMock }))
vi.mock('../stores/toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('../api', () => ({
  portfolioApi: {
    dailyPnl: vi.fn(() => Promise.resolve({ data: { items: [] } })),
    addEtf: vi.fn(() => Promise.resolve()),
    updateEtf: vi.fn(() => Promise.resolve()),
    removeEtf: vi.fn(() => Promise.resolve()),
  },
  marketApi: { search: vi.fn(() => Promise.resolve({ data: [] })) },
}))

const PortfolioManager = (await import('../components/PortfolioManager.vue')).default

describe('PortfolioManager selection indicator', () => {
  it('applies the active class + aria-selected to the selected row', async () => {
    const wrapper = mount(PortfolioManager, {
      props: { selectedSymbol: '510300' },
      global: { stubs: { AppButton: true, AppInput: true, AppSelect: true } },
    })
    await flushPromises()
    await wrapper.vm.$nextTick()

    const selectedRows = wrapper.findAll('tr[aria-selected="true"]')
    expect(selectedRows.length).toBe(1)
    expect(selectedRows[0].classes()).toContain('etf-row--selected')
    expect(selectedRows[0].text()).toContain('510300')
  })

  it('emits "select" with the holding when its row is clicked', async () => {
    const wrapper = mount(PortfolioManager, {
      props: { selectedSymbol: '' },
      global: { stubs: { AppButton: true, AppInput: true, AppSelect: true } },
    })
    await flushPromises()

    // click the first holding row (not an action button)
    const firstRow = wrapper.findAll('tbody tr')[0]
    await firstRow.trigger('click')

    const ev = wrapper.emitted('select')
    expect(ev).toBeTruthy()
    expect(ev[0][0].symbol).toBe('510050')
  })

  it('renders an on-exchange badge distinguishing 场内 vs 场外', async () => {
    const wrapper = mount(PortfolioManager, {
      props: { selectedSymbol: '' },
      global: { stubs: { AppButton: true, AppInput: true, AppSelect: true } },
    })
    await flushPromises()
    expect(wrapper.find('.exchange-badge.on').exists()).toBe(true)
  })
})
