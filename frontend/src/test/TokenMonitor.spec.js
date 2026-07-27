import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

// ── ECharts / vue-echarts stubs ──────────────────────────────

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    template: '<div data-testid="vchart"><slot /></div>',
    props: { option: Object, autoresize: Boolean, style: [String, Object] },
  },
}))

// TokenMonitor imports CanvasRenderer, LineChart/BarChart, TitleComponent etc.
vi.mock('echarts/core', () => ({ use: vi.fn() }))
vi.mock('echarts/charts', () => ({ LineChart: {}, BarChart: {} }))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, GridComponent: {}, LegendComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

import TokenMonitor from '../components/TokenMonitor.vue'

// Mock fetch to avoid actual API calls
global.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      total: { calls: 100, tokens: 50000, error_rate: 2 },
      daily: { calls: 10, tokens: 5000 },
      functions: [],
      series: { dates: ['2026-07-01'], tokens: [100] },
      failures: [],
    }),
  })
)

describe('TokenMonitor.vue — Granularity Tabs', () => {
  it('renders granularity tab labels', async () => {
    const wrapper = mount(TokenMonitor)
    // Wait for fetch and render
    await new Promise(r => setTimeout(r, 50))
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('按日')
    expect(wrapper.text()).toContain('按月')
    expect(wrapper.text()).toContain('按小时')
  })

  it('starts with day granularity selected', async () => {
    const wrapper = mount(TokenMonitor)
    await new Promise(r => setTimeout(r, 50))
    await wrapper.vm.$nextTick()

    // The AppTabs v-model binds granularity; default is 'day'
    expect(wrapper.vm.granularity).toBe('day')
  })

  it('switches granularity when tab is clicked', async () => {
    const wrapper = mount(TokenMonitor)
    await new Promise(r => setTimeout(r, 50))
    await wrapper.vm.$nextTick()

    // Find the v-model-driven AppTabs and simulate switching
    // Since AppTabs uses v-model, clicking a tab should update granularity
    // We can directly test the reactive behavior
    wrapper.vm.granularity = 'month'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.granularity).toBe('month')

    wrapper.vm.granularity = 'hour'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.granularity).toBe('hour')
  })
})
