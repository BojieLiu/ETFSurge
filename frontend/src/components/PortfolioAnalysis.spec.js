import { describe, it, expect, vi, beforeAll } from 'vitest'
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

const appTabsStub = {
  props: ['modelValue', 'tabs'],
  template: '<div class="tabs-stub"><button v-for="tab in tabs" :key="tab.value" class="tab-btn" @click="$emit(\'update:modelValue\', tab.value)">{{ tab.label }}</button></div>',
  emits: ['update:modelValue'],
}

let PortfolioAnalysis

beforeAll(async () => {
  PortfolioAnalysis = (await import('../components/PortfolioAnalysis.vue')).default
})

const mountWithStubs = (opts = {}) => {
  return mount(PortfolioAnalysis, {
    global: {
      plugins: [createPinia()],
      stubs: {
        PageHeader: { template: '<div><slot name="action" /><div><slot /></div></div>' },
        Section: { template: '<section><slot /></section>' },
        AppTabs: appTabsStub,
        ...opts,
      },
    },
  })
}

describe('PortfolioAnalysis tabbed view', () => {
  it('renders three tab buttons', () => {
    const wrapper = mountWithStubs()
    const tabs = wrapper.findAll('.tab-btn')
    expect(tabs.length).toBe(3)
    expect(tabs[0].text()).toContain('AI工具')
    expect(tabs[1].text()).toContain('持仓')
    expect(tabs[2].text()).toContain('技术分析')
  })

  it('shows AI tools tab by default', () => {
    const wrapper = mountWithStubs()
    expect(wrapper.find('.ai-tools').exists()).toBe(true)
    expect(wrapper.find('.pm').exists()).toBe(false)
    expect(wrapper.find('.av').exists()).toBe(false)
  })

  it('switches to holdings tab on click', async () => {
    const wrapper = mountWithStubs()
    await wrapper.findAll('.tab-btn')[1].trigger('click')
    expect(wrapper.find('.pm').exists()).toBe(true)
    expect(wrapper.find('.ai-tools').exists()).toBe(false)
  })

  it('switches to analysis tab on click', async () => {
    const wrapper = mountWithStubs()
    await wrapper.findAll('.tab-btn')[2].trigger('click')
    expect(wrapper.find('.av').exists()).toBe(true)
    expect(wrapper.find('.ai-tools').exists()).toBe(false)
  })

  it('drives AnalysisView selection from the selected holding across tabs', async () => {
    const wrapper = mountWithStubs()
    await wrapper.findAll('.tab-btn')[1].trigger('click')
    expect(wrapper.find('.pm').exists()).toBe(true)
    wrapper.find('.sel').trigger('click')
    await wrapper.findAll('.tab-btn')[2].trigger('click')
    expect(wrapper.find('.av').exists()).toBe(true)
    expect(wrapper.find('.av').text()).toBe('510300')
  })
})
