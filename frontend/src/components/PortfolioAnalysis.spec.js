import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

vi.mock('../components/PortfolioManager.vue', () => ({
  default: {
    name: 'PortfolioManager',
    props: ['selectedSymbol'],
    template: '<div class="pm"><button class="sel" @click="$emit(\'select\', { symbol: \'510300\' })">sel</button></div>',
  },
}))
vi.mock('../components/AnalysisView.vue', () => ({
  default: {
    name: 'AnalysisView',
    props: ['selectedSymbol'],
    template: '<div class="av">{{ selectedSymbol }}</div>',
  },
}))
vi.mock('../views/DashboardAiTools.vue', () => ({
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

const PortfolioAnalysis = (await import('../components/PortfolioAnalysis.vue')).default

describe('PortfolioAnalysis tabbed view', () => {
  it('renders three tab buttons', () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    const tabs = wrapper.findAll('.pa-tab')
    expect(tabs.length).toBe(3)
    expect(tabs[0].text()).toContain('AI工具')
    expect(tabs[1].text()).toContain('持仓')
    expect(tabs[2].text()).toContain('技术分析')
  })

  it('shows AI tools tab by default', () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // AI tools panel is visible by default
    expect(wrapper.find('.ai-tools').exists()).toBe(true)
    // Other panels are hidden
    expect(wrapper.find('.pm').exists()).toBe(false)
    expect(wrapper.find('.av').exists()).toBe(false)
  })

  it('switches to holdings tab on click', async () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // Click the holdings tab
    await wrapper.findAll('.pa-tab')[1].trigger('click')
    expect(wrapper.find('.pm').exists()).toBe(true)
    expect(wrapper.find('.ai-tools').exists()).toBe(false)
  })

  it('switches to analysis tab on click', async () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // Click the analysis tab
    await wrapper.findAll('.pa-tab')[2].trigger('click')
    expect(wrapper.find('.av').exists()).toBe(true)
    expect(wrapper.find('.ai-tools').exists()).toBe(false)
  })

  it('drives AnalysisView selection from the selected holding across tabs', async () => {
    const wrapper = mount(PortfolioAnalysis, {
      global: { plugins: [createPinia()] },
    })
    // Switch to holdings tab first
    await wrapper.findAll('.pa-tab')[1].trigger('click')
    await wrapper.vm.$nextTick()
    // Click a holding in the PortfolioManager
    await wrapper.find('.sel').trigger('click')
    await wrapper.vm.$nextTick()

    // Switch to analysis tab
    await wrapper.findAll('.pa-tab')[2].trigger('click')

    // The same symbol is passed down to AnalysisView
    expect(wrapper.find('.av').text()).toBe('510300')
  })
})
