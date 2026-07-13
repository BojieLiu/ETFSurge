import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// Stub the two heavy child components so we test the WIRING of the merged view
// (PortfolioManager select -> AnalysisView selectedSymbol) without echarts.
vi.mock('../components/PortfolioManager.vue', () => ({
  default: {
    name: 'PortfolioManager',
    props: ['selectedSymbol'],
    emits: ['select'],
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
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    onExchange: [],
    fetchEtfs: vi.fn(() => Promise.resolve()),
  }),
}))

const PortfolioAnalysis = (await import('../components/PortfolioAnalysis.vue')).default

describe('PortfolioAnalysis merged view', () => {
  it('renders the two-pane layout', () => {
    const wrapper = mount(PortfolioAnalysis)
    expect(wrapper.find('.pa-layout').exists()).toBe(true)
    expect(wrapper.find('.pm').exists()).toBe(true)
    expect(wrapper.find('.av').exists()).toBe(true)
  })

  it('drives AnalysisView selection from the selected holding', async () => {
    const wrapper = mount(PortfolioAnalysis)
    // AnalysisView starts with no selection
    expect(wrapper.find('.av').text()).toBe('')

    // User clicks a holding in the PortfolioManager list
    await wrapper.find('.sel').trigger('click')
    await wrapper.vm.$nextTick()

    // The same symbol is now passed down to AnalysisView
    expect(wrapper.find('.av').text()).toBe('510300')
  })
})
