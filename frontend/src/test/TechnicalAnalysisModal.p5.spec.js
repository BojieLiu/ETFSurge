/**
 * round19 P5-① (2026-08-12): TechnicalAnalysisModal 三选一指标副图。
 *
 * 对照 §十四 阶段 1 T1/T2：
 * - 默认渲染 MACD 副图（grid 数=3）；切换 KDJ → MACD grid 消失、KDJ grid 出现
 *   （负向：切换后 MACD 仍渲染 → FAIL）
 * - 无 rsi 序列时 RSI 项禁用/提示，不渲染空副图（负向：渲染空 RSI grid → FAIL）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import TechnicalAnalysisModal from '../components/market/TechnicalAnalysisModal.vue'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option'], template: '<div class="mock-chart" />' },
}))
vi.mock('echarts/core', () => ({ use: vi.fn() }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('echarts/charts', () => ({ CandlestickChart: {}, BarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, GridComponent: {},
  LegendComponent: {}, DataZoomComponent: {},
}))
vi.mock('../api', () => ({
  marketApi: {
    indicators: vi.fn(),
    signal: vi.fn(),
    chart: vi.fn(),
    fundFlow: vi.fn(),
  },
}))
import { marketApi } from '../api'

function chartData(overrides = {}) {
  const n = 30
  const dates = Array.from({ length: n }, (_, i) => `2026-07-${String(i + 1).padStart(2, '0')}`)
  const base = {
    dates,
    opens: Array(n).fill(4.0), closes: Array(n).fill(4.05),
    highs: Array(n).fill(4.1), lows: Array(n).fill(3.95),
    volumes: Array(n).fill(1000), amount: Array(n).fill(5e6),
    ma5: Array(n).fill(4.02), ma10: Array(n).fill(4.0), ma20: Array(n).fill(3.98),
    macd: {
      dif: Array.from({ length: n }, (_, i) => 0.01 + i * 0.001),
      dea: Array.from({ length: n }, (_, i) => 0.008 + i * 0.001),
      histogram: Array.from({ length: n }, (_, i) => (i % 2 ? 0.02 : -0.02)),
    },
    kdj: { k: Array(n).fill(55), d: Array(n).fill(50), j: Array(n).fill(60) },
    rsi: Array.from({ length: n }, (_, i) => 40 + (i % 20)),
  }
  return { ...base, ...overrides }
}

async function mountModal(data) {
  marketApi.indicators.mockResolvedValue({ data: { rsi: 55, macd: { dif: 0.01, dea: 0.008 }, kdj: { k: 55, d: 50, j: 60 } } })
  marketApi.signal.mockResolvedValue({ data: { signal: 'hold', score: 0.5, reasons: [] } })
  marketApi.chart.mockResolvedValue({ data })
  marketApi.fundFlow.mockResolvedValue({ data: { available: false } })
  const wrapper = mount(TechnicalAnalysisModal, {
    props: { symbol: '510300', name: '沪深300ETF', visible: true },
    global: { stubs: { teleport: true, transition: false } },
  })
  await wrapper.vm.$nextTick()
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('TechnicalAnalysisModal 三选一指标副图（round19 P5-①）', () => {
  it('默认渲染 MACD 副图（grid=3）；切换 KDJ → MACD 消失、KDJ 出现（互斥）', async () => {
    const wrapper = await mountModal(chartData())
    const opt1 = wrapper.vm.klineOption
    expect(opt1.grid.length).toBe(3)
    expect(opt1.series.some((s) => s.name === 'MACD')).toBe(true)

    // 切换 KDJ（弹窗按钮无 testid，用 class + 文本定位）
    await wrapper.findAll('.ta-ind-btn').find((b) => b.text() === 'KDJ').trigger('click')
    await wrapper.vm.$nextTick()
    const opt2 = wrapper.vm.klineOption
    expect(opt2.series.some((s) => s.name === 'KDJ-K')).toBe(true)
    expect(opt2.series.some((s) => s.name === 'MACD')).toBe(false) // 负向：切换后 MACD 仍渲染 → FAIL
    expect(opt2.series.some((s) => s.name === '成交量')).toBe(true) // 成交量固定
    expect(opt2.grid.length).toBe(3)
  })

  it('切换 RSI → RSI 副图渲染 + 70/30 超买超卖 markLine', async () => {
    const wrapper = await mountModal(chartData())
    await wrapper.findAll('.ta-ind-btn').find((b) => b.text() === 'RSI').trigger('click')
    await wrapper.vm.$nextTick()
    const opt = wrapper.vm.klineOption
    const rsiSeries = opt.series.find((s) => s.name === 'RSI(14)')
    expect(rsiSeries).toBeTruthy()
    expect(rsiSeries.markLine.data.some((m) => m.yAxis === 70)).toBe(true)
  })

  it('无 rsi 序列 → RSI 项禁用 + 不渲染空 RSI 副图（负向：渲染空 RSI grid → FAIL）', async () => {
    const wrapper = await mountModal(chartData({ rsi: [] }))
    const rsiBtn = wrapper.findAll('.ta-ind-btn').find((b) => b.text() === 'RSI')
    expect(rsiBtn.attributes('disabled')).toBeDefined() // 数据不足禁用
    // 尝试选中无效项不改变副图
    await wrapper.vm.$nextTick()
    const opt = wrapper.vm.klineOption
    expect(opt.series.some((s) => s.name === 'RSI(14)')).toBe(false)
    // 无 RSI 副图时 MACD 仍正常（grid 数保持 3）
    expect(opt.grid.length).toBe(3)
  })

  it('切换器按钮渲染 MACD/KDJ/RSI 三个选项', async () => {
    const wrapper = await mountModal(chartData())
    const btns = wrapper.findAll('.ta-ind-btn')
    expect(btns.map((b) => b.text())).toEqual(['MACD', 'KDJ', 'RSI'])
    expect(btns[0].classes()).toContain('active') // 默认 MACD
  })
})
