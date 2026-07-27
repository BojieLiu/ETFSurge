import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// ── ECharts / vue-echarts stubs ──────────────────────────────
// Both AllocationPieChart and PnLBarChart use VChart from vue-echarts.
// We stub it as a plain component so tests can read the `option` prop.

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    template: '<div :style="style" data-testid="vchart"><slot /></div>',
    props: { option: Object, autoresize: Boolean, style: [String, Object] },
  },
}))

vi.mock('echarts/core', () => ({
  use: vi.fn(),
}))

import AllocationPieChart from '../components/dashboard/AllocationPieChart.vue'
import PnLBarChart from '../components/dashboard/PnLBarChart.vue'

// ── AllocationPieChart ──────────────────────────────────────

describe('AllocationPieChart.vue', () => {
  const sampleItems = [
    { name: '沪深300ETF', target_weight: 0.50, target_amount: 50000 },
    { name: '中证500ETF', target_weight: 0.30, target_amount: 30000 },
    { name: '债券ETF', target_weight: 0.20, target_amount: 20000 },
  ]

  it('renders title in card header', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: [], title: '资产配置' },
    })
    expect(wrapper.text()).toContain('资产配置')
  })

  it('renders VChart stub when items are provided', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: sampleItems, title: '资产配置' },
    })
    const vchart = wrapper.findComponent({ name: 'VChart' })
    expect(vchart.exists()).toBe(true)
  })

  it('renders VChart stub even with empty items (no v-if)', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: [], title: '资产配置' },
    })
    expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(true)
  })

  it('passes items as data series in chart option', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: sampleItems, title: '资产配置' },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option).toBeDefined()
    expect(option.series).toBeDefined()
    expect(option.series[0].data).toHaveLength(3)
    expect(option.series[0].data[0].value).toBe(50000)
    expect(option.series[0].data[1].value).toBe(30000)
    expect(option.series[0].data[2].value).toBe(20000)
  })

  it('formats weight percentages in data labels', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: sampleItems, title: '资产配置' },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.series[0].data[0].name).toContain('50.0%')
    expect(option.series[0].data[1].name).toContain('30.0%')
    expect(option.series[0].data[2].name).toContain('20.0%')
  })

  it('handles single item gracefully', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: [{ name: 'ETF', target_weight: 1.0, target_amount: 100000 }], title: '单只' },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.series[0].data).toHaveLength(1)
    expect(option.series[0].data[0].name).toContain('100.0%')
  })

  it('passes empty data array when no items', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: [], title: '资产配置' },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.series[0].data).toEqual([])
  })

  it('uses AppCard wrapper with card variant', () => {
    const wrapper = mount(AllocationPieChart, {
      props: { items: [], title: '资产配置' },
    })
    // AppCard renders its title in a slot; verify card structure
    expect(wrapper.findComponent({ name: 'AppCard' }).exists()).toBe(true)
  })
})

// ── PnLBarChart ─────────────────────────────────────────────

describe('PnLBarChart.vue', () => {
  const sampleItems = [
    { name: '沪深300ETF', short_name: '300', daily_pnl: 150 },
    { name: '中证500ETF', short_name: '500', daily_pnl: -80 },
    { name: '债券ETF', short_name: '债券', daily_pnl: 12 },
  ]

  it('renders default title', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: [], loading: false },
    })
    expect(wrapper.text()).toContain('当日盈亏分布')
  })

  it('renders VChart stub when items exist', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: sampleItems, loading: false },
    })
    expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(true)
  })

  it('does NOT render VChart stub when items empty (v-if)', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: [], loading: false },
    })
    expect(wrapper.findComponent({ name: 'VChart' }).exists()).toBe(false)
  })

  it('shows empty state text when no items and not loading', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: [], loading: false },
    })
    expect(wrapper.text()).toContain('暂无盈亏数据')
  })

  it('passes daily_pnl values as chart series data', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: sampleItems, loading: false },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.series).toBeDefined()
    expect(option.series[0].data).toEqual([150, -80, 12])
  })

  it('passes short_name as xAxis category labels', () => {
    const wrapper = mount(PnLBarChart, {
      props: { items: sampleItems, loading: false },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.xAxis.data).toEqual(['300', '500', '债券'])
  })

  it('prefers short_name over name for xAxis labels', () => {
    const items = [{ name: '沪深300ETF', short_name: 'HS300', daily_pnl: 100 }]
    const wrapper = mount(PnLBarChart, {
      props: { items, loading: false },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.xAxis.data[0]).toBe('HS300')
  })

  it('falls back to name when short_name is missing', () => {
    const items = [{ name: '沪深300ETF', daily_pnl: 100 }]
    const wrapper = mount(PnLBarChart, {
      props: { items, loading: false },
    })
    const option = wrapper.findComponent({ name: 'VChart' }).props('option')
    expect(option.xAxis.data[0]).toBe('沪深300ETF')
  })
})
