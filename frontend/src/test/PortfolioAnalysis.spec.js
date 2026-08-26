import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('../components/portfolio/PortfolioManager.vue', () => ({
  default: {
    name: 'PortfolioManager',
    props: ['selectedSymbol'],
    template: '<div class="pm"><button class="sel" @click="$emit(\'select\', { symbol: \'510300\' })">sel</button></div>',
  },
}))
vi.mock('../components/portfolio/AnalysisView.vue', () => ({
  default: {
    name: 'AnalysisView',
    props: ['selectedSymbol'],
    template: '<div class="av">{{ selectedSymbol }}</div>',
  },
}))
vi.mock('../views/AiDesign.vue', () => ({
  default: {
    name: 'DashboardAiTools',
    template: '<div class="ai-tools"></div>',
  },
}))
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    onExchange: [],
    fetchEtfs: vi.fn(() => Promise.resolve()),
  }),
}))
vi.mock('../stores/toast', () => ({ useToastStore: () => ({ show: vi.fn() }) }))
// round34-B7 C2：mock 盈亏 tab 的数据管道，验证懒加载初始化
vi.mock('../composables/useDashboardData', () => ({
  useDashboardData: vi.fn(),
}))

import { useDashboardData } from '../composables/useDashboardData'

const dashInstance = () => ({
  allocationOn: ref2({ allocations: [] }),
  allocationOff: ref2({ allocations: [] }),
  pnlHistory: ref2(null), pnlHistoryLoading: ref2(false),
  loading: ref2(true), fetchAttempted: ref2(false),
  totalAll: ref2(0), pnlOn: ref2(0), pnlOff: ref2(0),
  pnlItems: ref2([]), pnlTotal: ref2(0), pnlTotalAmount: ref2(0),
  pnlWeightedChange: ref2(0),
  cashPctOn: ref2(0), cashOn: ref2(0), cashPctOff: ref2(0), cashOff: ref2(0),
  refreshAll: vi.fn(() => Promise.resolve()),
  fetchPnlHistory: vi.fn(),
})
import { ref as ref2 } from 'vue'

const PortfolioAnalysis = (await import('../views/PortfolioAnalysis.vue')).default

describe('PortfolioAnalysis tabbed view', () => {
  // round34-B7 C2：主 tabs = AI工具/持仓/盈亏/技术分析。
  // AppTabs 为多根组件（tabs 条与 panels 兄弟节点），class 透传失效——
  // 用「.portfolio-analysis 直接子代的 .tabs」定位主导航，避开「盈亏」tab 内嵌的范围子 tabs。
  const mainTab = (wrapper, label) =>
    wrapper.findAll('.portfolio-analysis > .tabs .tabs__tab').find((t) => t.text().includes(label))
  const mainTabCount = (wrapper) => wrapper.findAll('.portfolio-analysis > .tabs .tabs__tab').length

  beforeEach(() => {
    // 默认给所有用例一个可用的盈亏数据管道实例（最后一个用例会取回断言）
    useDashboardData.mockImplementation(() => dashInstance())
  })

  it('renders four tab buttons (B7: 新增盈亏 tab)', () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    expect(mainTabCount(wrapper)).toBe(4)
    expect(mainTab(wrapper, 'AI工具')).toBeTruthy()
    expect(mainTab(wrapper, '持仓')).toBeTruthy()
    expect(mainTab(wrapper, '盈亏')).toBeTruthy()
    expect(mainTab(wrapper, '技术分析')).toBeTruthy()
  })

  it('shows holdings tab by default', () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // Holdings panel is visible by default (activeTab = 'holdings')
    expect(wrapper.find('.pm').isVisible()).toBe(true)
    // Other panels are rendered but not visible (AppTabs uses hidden attr)
    expect(wrapper.find('.ai-tools').exists()).toBe(true)
    expect(wrapper.find('.ai-tools').isVisible()).toBe(false)
    expect(wrapper.find('.av').exists()).toBe(true)
    expect(wrapper.find('.av').isVisible()).toBe(false)
  })

  it('switches tabs on click', async () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    await mainTab(wrapper, '技术分析').trigger('click')
    await wrapper.vm.$nextTick()
    // Analysis panel should now be visible
    expect(wrapper.find('.av').isVisible()).toBe(true)
    // AI tools should not be visible
    expect(wrapper.find('.ai-tools').isVisible()).toBe(false)
  })

  it('drives AnalysisView selection from the selected holding across tabs', async () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // Holdings tab is default
    await mainTab(wrapper, '持仓').trigger('click')
    await wrapper.vm.$nextTick()
    // Click a holding in the PortfolioManager
    await wrapper.find('.sel').trigger('click')
    await wrapper.vm.$nextTick()

    // Switch to analysis tab
    await mainTab(wrapper, '技术分析').trigger('click')

    // The same symbol is passed down to AnalysisView
    expect(wrapper.find('.av').text()).toBe('510300')
  })

  it('B7: 盈亏 tab 首次进入时懒加载初始化（refreshAll + 累计历史各一次）', async () => {
    let inst
    useDashboardData.mockImplementation(() => {
      inst = dashInstance()
      return inst
    })
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    expect(inst.refreshAll).not.toHaveBeenCalled() // 默认 holdings tab，不预取
    await mainTab(wrapper, '盈亏').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(inst.refreshAll).toHaveBeenCalledTimes(1)
    expect(inst.fetchPnlHistory).toHaveBeenCalledWith('combined')
  })
})
