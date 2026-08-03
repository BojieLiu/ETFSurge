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

describe('AnalysisView 父组件切换标的 (R5 #3 修复)', () => {
  it('selectedSymbol 变化时即使 etfInfoMap 尚未构建完成也触发 fetchChart（修复"所有标的一样"）', async () => {
    // 模拟：onMounted 的 fetchEtfs 慢 → etfInfoMap 构建前用户已点击持仓行
    const wrapper = mount(AnalysisView, {
      props: { selectedSymbol: '510500' },
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
    })
    // 不 await 完成 onMounted（etfInfoMap 仍空），直接改 prop
    wrapper.setProps({ selectedSymbol: '510300' })
    await nextTick()
    await nextTick()
    // 旧实现：etfInfoMap 空 → 守卫失败 → 不 fetchChart → 面板停留第一只标的（"所有标的一样"）
    // 新实现：守卫放宽 → 直接按新 symbol 请求
    expect(chartMock).toHaveBeenCalledWith('510300', 'A', 'daily')
    expect(indicatorsMock).toHaveBeenCalledWith('510300', 'A', 'daily')
    expect(signalMock).toHaveBeenCalledWith('510300', 'A', 'daily')
  })

  it('快速连续切换标的时响应乱序不覆盖（fetchChart 竞态守卫）', async () => {
    // chartMock 第 1 次调用（510300）慢返回，第 2 次调用（510500）快返回
    chartMock
      .mockImplementationOnce(() => new Promise((resolve) => setTimeout(() => resolve({ data: { dates: ['2026-07-30'], closes: [4.6], opens: [4.5], highs: [4.7], lows: [4.4] } }), 50)))
      .mockResolvedValue({ data: { dates: ['2026-07-31'], closes: [5.0], opens: [4.9], highs: [5.1], lows: [4.8] } })
    const wrapper = mount(AnalysisView, {
      props: { selectedSymbol: '510300' },
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
    })
    await nextTick()
    await nextTick()
    wrapper.setProps({ selectedSymbol: '510500' })
    await nextTick()
    // 等慢响应返回后，最终显示的是最后一次请求（510500）的数据
    await new Promise((r) => setTimeout(r, 100))
    await nextTick()
    expect(chartMock).toHaveBeenLastCalledWith('510500', 'A', 'daily')
    // 慢的 510300 响应晚到不应覆盖 510500 的图表数据
    const chartOption = wrapper.findComponent({ name: 'ChartPanel' }).props('chartOption')
    expect(chartOption.series[0].data[0][1]).toBe(5.0)
  })
})

describe('AnalysisView 场外基金技术分析 (R5-2-11)', () => {
  async function mountWithOffExchange(trackedIndex) {
    indicatorsMock.mockClear()
    signalMock.mockClear()
    const wrapper = mount(AnalysisView, {
      global: { stubs: { ChartPanel: true, SignalPanel: true } },
      props: { selectedSymbol: '' },
    })
    // 等 onMounted 完成（fetchEtfs 异步 → 否则其 etfInfoMap = {} 覆盖注入）
    await nextTick()
    await new Promise((r) => setTimeout(r, 50))
    await nextTick()
    // VTU wrapper.vm 对 ref 自动解包 → 直接整体赋值（不要 .value）
    wrapper.vm.etfInfoMap = {
      '021458': { symbol: '021458', name: '联接A', portfolio_type: 'off_exchange', tracked_index: trackedIndex },
    }
    wrapper.setProps({ selectedSymbol: '021458' })
    await nextTick()
    await new Promise((r) => setTimeout(r, 100))
    await nextTick()
    return wrapper
  }

  it('场外标的 tracked_index=场内 ETF 代码 → indicators/signal 以 assetType=A 请求', async () => {
    // 021458 场外联接 → tracked_index=159545（场内 ETF）→ 查 ETF 自身 K 线（assetType="A"）
    await mountWithOffExchange('159545')
    expect(indicatorsMock).toHaveBeenLastCalledWith('159545', 'A', expect.anything())
    expect(signalMock).toHaveBeenLastCalledWith('159545', 'A', expect.anything())
  })

  it('场外标的 tracked_index=真实指数代码 → assetType=index 不回归', async () => {
    await mountWithOffExchange('000300')
    expect(indicatorsMock).toHaveBeenLastCalledWith('000300', 'index', expect.anything())
    expect(signalMock).toHaveBeenLastCalledWith('000300', 'index', expect.anything())
  })
})
