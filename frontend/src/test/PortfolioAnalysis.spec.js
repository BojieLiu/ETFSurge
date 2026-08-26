import { describe, it, expect, vi } from 'vitest'
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

const PortfolioAnalysis = (await import('../views/PortfolioAnalysis.vue')).default

describe('PortfolioAnalysis tabbed view', () => {
  it('renders three tab buttons', () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    const tabs = wrapper.findAll('.tabs__tab')
    expect(tabs.length).toBe(3)
    expect(tabs[0].text()).toContain('AI工具')
    expect(tabs[1].text()).toContain('持仓')
    expect(tabs[2].text()).toContain('技术分析')
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
    // Click the analysis tab (index 2)
    await wrapper.findAll('.tabs__tab')[2].trigger('click')
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
    // Holdings tab is default (index 1)
    await wrapper.findAll('.tabs__tab')[1].trigger('click')
    await wrapper.vm.$nextTick()
    // Click a holding in the PortfolioManager
    await wrapper.find('.sel').trigger('click')
    await wrapper.vm.$nextTick()

    // Switch to analysis tab
    await wrapper.findAll('.tabs__tab')[2].trigger('click')

    // The same symbol is passed down to AnalysisView
    expect(wrapper.find('.av').text()).toBe('510300')
  })
})
