/**
 * PortfolioManager 测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - UX 改进：搜索 placeholder/热门建议/表单校验/等权分配/权重滑块/成功 toast
 * - 选择指示：aria-selected 高亮 + select emit + 场内/场外徽标
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const storeMock = vi.hoisted(() => ({
  onExchange: [
    { symbol: '510050', name: '上证50ETF', asset_type: 'A', target_weight: 0.3, portfolio_type: 'on_exchange' },
    { symbol: '510300', name: '沪深300ETF', asset_type: 'A', target_weight: 0.4, portfolio_type: 'on_exchange' },
    { symbol: '159915', name: '创业板ETF', asset_type: 'A', target_weight: 0.3, portfolio_type: 'on_exchange' },
  ],
  offExchange: [],
  etfs: [],
  fetchEtfs: vi.fn(() => Promise.resolve()),
  addEtf: vi.fn(() => Promise.resolve()),
  updateEtf: vi.fn(() => Promise.resolve()),
  removeEtf: vi.fn(() => Promise.resolve()),
}))

vi.mock('../stores/portfolio', () => ({ usePortfolioStore: () => storeMock }))
const toastShow = vi.fn()
vi.mock('../stores/toast', () => ({ useToastStore: () => ({ show: toastShow }) }))
vi.mock('../api', () => ({
  portfolioApi: {
    dailyPnl: vi.fn(() => Promise.resolve({ data: { items: [] } })),
    addEtf: vi.fn(() => Promise.resolve()),
    updateEtf: vi.fn(() => Promise.resolve()),
    removeEtf: vi.fn(() => Promise.resolve()),
  },
  marketApi: { search: vi.fn(() => Promise.resolve({ data: [] })) },
}))

const PortfolioManager = (await import('../components/portfolio/PortfolioManager.vue')).default

describe('PortfolioManager UX improvements', () => {
  it('shows improved search placeholder with example', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()
    const searchInput = wrapper.find('.form-field--search input')
    expect(searchInput.exists()).toBe(true)
    expect(searchInput.attributes('placeholder')).toContain('510300')
  })

  it('displays hot/common ETF suggestions when search field is focused', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    const searchInput = wrapper.find('.form-field--search input')
    await searchInput.trigger('focus')
    await wrapper.vm.$nextTick()

    const hotSection = wrapper.find('.hot-etfs')
    expect(hotSection.exists()).toBe(true)

    const hotItems = wrapper.findAll('.hot-etf-item')
    expect(hotItems.length).toBeGreaterThan(2)
    expect(hotItems[0].text()).toContain('510050')
  })

  it('shows form validation errors when required fields are empty', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    const addForm = wrapper.find('form')
    await addForm.trigger('submit.prevent')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.form-error').exists()).toBe(true)
    expect(wrapper.find('.form-error').text()).toContain('请搜索并选择')
  })

  it('provides auto-equalize weights button', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    // The button may be stubbed, check the card-actions exists
    const cardActions = wrapper.find('.etf-list-card .card-actions')
    expect(cardActions.exists()).toBe(true)
    // Check the component exposes the autoDistributeWeights method
    expect(typeof wrapper.vm.autoDistributeWeights).toBe('function')
  })

  it('auto-equalize weights distributes equally among active ETFs', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.vm.autoDistributeWeights()
    await flushPromises()

    const updateCalls = storeMock.updateEtf.mock.calls
    expect(updateCalls.length).toBe(3)
    for (const [, data] of updateCalls) {
      expect(data.target_weight).toBeCloseTo(0.333, 1)
    }
  })

  it('shows weight slider in add form with real-time percentage', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    const weightLabel = wrapper.find('.weight-label')
    expect(weightLabel.exists()).toBe(true)
    expect(weightLabel.text()).toMatch(/\d+%/)

    const slider = wrapper.find('.form-field--weight input[type="range"]')
    expect(slider.exists()).toBe(true)
  })

  it('shows weight slider value display next to each ETF row', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    const weightVals = wrapper.findAll('.weight-val')
    expect(weightVals.length).toBe(3)
    expect(weightVals[0].text()).toMatch(/\d+%/)
  })

  it('confirms add with success toast and resets form', async () => {
    const wrapper = mount(PortfolioManager, {
      global: { stubs: { AppButton: true, AppInput: false, AppSelect: true } },
    })
    await flushPromises()

    wrapper.vm.form = {
      symbol: '588000', name: '科创50ETF', asset_type: 'A',
      weight: 20, tracked_index: '', avg_cost: null, shares_held: null,
    }
    await wrapper.vm.$nextTick()

    const addForm = wrapper.find('form')
    await addForm.trigger('submit.prevent')
    await flushPromises()

    expect(storeMock.addEtf).toHaveBeenCalled()
    expect(toastShow).toHaveBeenCalledWith(expect.stringContaining('科创50ETF'), 'success')
  })
})

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
