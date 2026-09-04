// R174 (round52 §7.3 方案D): 盈亏 tab 范围（scope）切换时，分配饼图/表只显示对应侧。
// round52 §7.2: 渲染条件原只看数据非空 → scope='on_exchange' 时场外饼图仍显示（反之亦然）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { ref } from 'vue'

vi.mock('../components/portfolio/PortfolioManager.vue', () => ({
  default: { name: 'PortfolioManager', template: '<div class="pm"/>' },
}))
vi.mock('../components/portfolio/AnalysisView.vue', () => ({
  default: { name: 'AnalysisView', template: '<div class="av"/>' },
}))
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ onExchange: [], fetchEtfs: vi.fn(() => Promise.resolve()) }),
}))
vi.mock('../stores/toast', () => ({ useToastStore: () => ({ show: vi.fn() }) }))
vi.mock('../composables/useDashboardData', () => ({ useDashboardData: vi.fn() }))

import { useDashboardData } from '../composables/useDashboardData'

// 子组件 stub：AllocationPieChart/AllocationTable 以 title 区分场内/场外
vi.mock('../components/dashboard/AllocationPieChart.vue', () => ({
  default: {
    name: 'AllocationPieChart',
    props: ['items', 'title'],
    template: '<div class="pie-stub">{{ title }}</div>',
  },
}))
vi.mock('../components/dashboard/AllocationTable.vue', () => ({
  default: {
    name: 'AllocationTable',
    props: ['items', 'cashPct', 'cashAmount', 'title'],
    template: '<div class="atable-stub">{{ title }}</div>',
  },
}))

const PortfolioAnalysis = (await import('../views/PortfolioAnalysis.vue')).default

const dashInstance = (scopeInitial) => ({
  allocationOn: ref({ allocations: [{ symbol: '510300', weight: 1 }] }),
  allocationOff: ref({ allocations: [{ symbol: '022449', weight: 1 }] }),
  pnlHistory: ref(null), pnlHistoryLoading: ref(false),
  loading: ref(false), fetchAttempted: ref(true),
  totalAll: ref(0), pnlOn: ref(0), pnlOff: ref(0),
  pnlItems: ref([]), pnlTotal: ref(0), pnlTotalAmount: ref(0),
  pnlWeightedChange: ref(0),
  cashPctOn: ref(0), cashOn: ref(0), cashPctOff: ref(0), cashOff: ref(0),
  refreshAll: vi.fn(() => Promise.resolve()),
  fetchPnlHistory: vi.fn(),
})

const findTab = (wrapper, label) =>
  wrapper.findAll('.tabs__tab').find((t) => t.text().includes(label))

describe('R174: 盈亏 tab scope 过滤饼图/分配表', () => {
  beforeEach(() => {
    useDashboardData.mockImplementation(() => dashInstance())
  })

  const mountPnl = async () => {
    const wrapper = mount(PortfolioAnalysis, { global: { plugins: [createPinia()] } })
    await findTab(wrapper, '盈亏').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    return wrapper
  }

  const pieTitles = (wrapper) => wrapper.findAll('.pie-stub').map((w) => w.text())
  const tableTitles = (wrapper) => wrapper.findAll('.atable-stub').map((w) => w.text())

  it('combined：双饼图 + 双表都在（既有行为）', async () => {
    const wrapper = await mountPnl()
    expect(pieTitles(wrapper)).toEqual(expect.arrayContaining(['场内分配', '场外分配']))
    expect(tableTitles(wrapper)).toEqual(expect.arrayContaining(['场内 ETF 目标分配', '场外 ETF 目标分配']))
  })

  it('负向：scope=on_exchange 时场外饼图/表必须消失', async () => {
    const wrapper = await mountPnl()
    await findTab(wrapper, '场内').trigger('click')
    await wrapper.vm.$nextTick()
    expect(pieTitles(wrapper)).toContain('场内分配')
    expect(pieTitles(wrapper)).not.toContain('场外分配')
    expect(tableTitles(wrapper)).not.toContain('场外 ETF 目标分配')
  })

  it('负向：scope=off_exchange 时场内饼图/表必须消失', async () => {
    const wrapper = await mountPnl()
    await findTab(wrapper, '场外').trigger('click')
    await wrapper.vm.$nextTick()
    expect(pieTitles(wrapper)).toContain('场外分配')
    expect(pieTitles(wrapper)).not.toContain('场内分配')
    expect(tableTitles(wrapper)).not.toContain('场内 ETF 目标分配')
  })
})
