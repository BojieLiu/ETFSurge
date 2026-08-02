/**
 * AnalysisView 周期切换（R5 修复）：
 * - 旧缺陷：indicators/signal 请求不传 period → 切换周期后指标/信号仍为日线；
 *   api 层 indicators()/signal() 不接受 period 参数。
 * - 修复：api 层加 period 参数 + fetchChart 传入 period.value（+ watch(period) 兜底）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

// ECharts 在 jsdom 下不可渲染 → mock 入口
vi.mock('echarts/core', () => ({ use: vi.fn() }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('echarts/charts', () => ({ CandlestickChart: {}, BarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, GridComponent: {}, LegendComponent: {}, DataZoomComponent: {},
}))

const { chartMock, indicatorsMock, signalMock } = vi.hoisted(() => ({
  chartMock: vi.fn(),
  indicatorsMock: vi.fn(),
  signalMock: vi.fn(),
}))

vi.mock('../api', () => ({
  marketApi: {
    chart: (...a) => chartMock(...a),
    indicators: (...a) => indicatorsMock(...a),
    signal: (...a) => signalMock(...a),
  },
}))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    onExchange: [{ symbol: '510300', portfolio_type: 'on_exchange', name: '沪深300ETF', tracked_index: null }],
    offExchange: [],
    fetchEtfs: vi.fn().mockResolvedValue([]),
  }),
}))

import AnalysisView from '../components/AnalysisView.vue'
import AppSelect from '../components/ui/AppSelect.vue'

beforeEach(() => {
  chartMock.mockReset().mockResolvedValue({ data: { dates: ['2026-07-31'], closes: [4.65], opens: [4.6], highs: [4.7], lows: [4.5] } })
  indicatorsMock.mockReset().mockResolvedValue({ data: { data_available: true, ma5: 4.66, rsi: 43 } })
  signalMock.mockReset().mockResolvedValue({ data: { signal: 'hold', score: 0 } })
})

describe('AnalysisView 周期切换 (R5)', () => {
  it('初始加载：chart/indicators/signal 均以 daily 请求', async () => {
    mount(AnalysisView, {
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
    })
    await nextTick()
    await nextTick()
    expect(chartMock).toHaveBeenCalledWith('510300', 'A', 'daily')
    expect(indicatorsMock).toHaveBeenCalledWith('510300', 'A', 'daily')
    expect(signalMock).toHaveBeenCalledWith('510300', 'A', 'daily')
  })

  it('切换周期：indicators/signal 不再固定日线，以新周期请求', async () => {
    const wrapper = mount(AnalysisView, {
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
    })
    await nextTick()
    await nextTick()
    // ControlPanel 中第 2 个 AppSelect 是周期选择器（第 1 个是 ETF 选择）
    const selects = wrapper.findAllComponents(AppSelect)
    expect(selects.length).toBeGreaterThanOrEqual(2)
    selects[1].vm.$emit('update:model-value', 'weekly')
    await nextTick()
    await nextTick()
    expect(chartMock).toHaveBeenLastCalledWith('510300', 'A', 'weekly')
    expect(indicatorsMock).toHaveBeenLastCalledWith('510300', 'A', 'weekly')
    expect(signalMock).toHaveBeenLastCalledWith('510300', 'A', 'weekly')
  })

  it('切换周线后指标/信号响应携带新周期数据（非日线残留）', async () => {
    const wrapper = mount(AnalysisView, {
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
    })
    await nextTick()
    await nextTick()
    const selects = wrapper.findAllComponents(AppSelect)
    selects[1].vm.$emit('update:model-value', 'monthly')
    await nextTick()
    await nextTick()
    expect(indicatorsMock).toHaveBeenLastCalledWith('510300', 'A', 'monthly')
    expect(signalMock).toHaveBeenLastCalledWith('510300', 'A', 'monthly')
  })
})
