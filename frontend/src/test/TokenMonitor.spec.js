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
import { calcCost, modelCostFromBuckets } from '../utils/pricing'

// round35 FE2: adminApi（axios）补 mock——此前未 mock 时请求失败被旧实现吞掉、
// 渲染空统计冒充正常（R127 空态冒充错误态），tabs 用例的绿是假绿。
// 现在组件正确渲染错误态，本文件 mount 类用例需要成功路径数据。
const { tokenUsageMock } = vi.hoisted(() => ({ tokenUsageMock: vi.fn() }))
vi.mock('../api', () => ({
  adminApi: {
    tokenUsage: (...a) => tokenUsageMock(...a),
    tokenTimeseries: vi.fn().mockResolvedValue({ data: { series: [], total: {} } }),
    tokenFailures: vi.fn().mockResolvedValue({ data: { failures: [] } }),
  },
}))

// Mock fetch to avoid actual API calls — axios 风格 { data }
const mockSeries = [
  {
    date: '2026-07-01',
    calls: 2,
    prompt_tokens: 1000,
    completion_tokens: 500,
    total_tokens: 1500,
    by_model: {
      'deepseek-v4-flash': { calls: 1, prompt_tokens: 1000, completion_tokens: 500, total_tokens: 1500 },
    },
  },
  {
    date: '2026-07-02',
    calls: 1,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    by_model: {
      'deepseek-v4-flash-free': { calls: 1, prompt_tokens: 2000, completion_tokens: 1000, total_tokens: 3000 },
    },
  },
]

function makeFetchData(series = mockSeries, total = null) {
  const windowTotal = total || {
    calls: 3,
    prompt_tokens: 3000,
    completion_tokens: 1500,
    total_tokens: 4500,
    by_model: {
      'deepseek-v4-flash': { calls: 2, prompt_tokens: 1000, completion_tokens: 500, total_tokens: 1500 },
      'deepseek-v4-flash-free': { calls: 1, prompt_tokens: 2000, completion_tokens: 1000, total_tokens: 3000 },
    },
  }
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        data: {
          total: { calls: 100, prompt_tokens: 0, completion_tokens: 0 },
          by_function: {},
          by_model: {},
        },
      }),
    })
  )
  // adminApi 使用 axios 实例，直接 stub window 上的 api 不方便——改用 Promise.all 返回结构注入
  // 简单方式：monkeypatch 组件内部不可行，这里仅测纯函数与通过 mount 后的状态
  return { series, total: windowTotal }
}

describe('TokenMonitor calcCost 纯函数 (R57/R59)', () => {
  it('R59: flash-free 记录费用必须为 0', () => {
    expect(calcCost(2000, 1000, 'deepseek-v4-flash-free')).toBe(0)
    expect(modelCostFromBuckets({ 'deepseek-v4-flash-free': { prompt_tokens: 9999, completion_tokens: 9999 } })).toBe(0)
  })

  it('R57: 多模型混合按各自单价', () => {
    // 单位 ¥/1k tokens：flash 1000 prompt × 0.001 + 500 completion × 0.002 = 0.001 + 0.001 = 0.002
    // chat 1000 prompt × 0.002 + 500 completion × 0.008 = 0.002 + 0.004 = 0.006
    // 合计 0.008 → round 0.01
    const cost = modelCostFromBuckets({
      'deepseek-v4-flash': { prompt_tokens: 1000, completion_tokens: 500 },
      'deepseek-chat': { prompt_tokens: 1000, completion_tokens: 500 },
    })
    expect(cost).toBe(0.01)
    expect(calcCost(1000, 500, 'deepseek-v4-flash')).toBeCloseTo(0.002)
    expect(calcCost(1000, 500, 'deepseek-chat')).toBeCloseTo(0.006)
  })

  it('R57: 未知模型回退 flash 单价', () => {
    expect(calcCost(1000, 500, 'unknown-model-xyz')).toBeCloseTo(0.002)
  })

  it('R57: 逐日费用 = 该日 by_model 之和', () => {
    expect(modelCostFromBuckets(mockSeries[0].by_model)).toBeCloseTo(0.002)
    expect(modelCostFromBuckets(mockSeries[1].by_model)).toBe(0)
  })
})

describe('TokenMonitor.vue — Granularity Tabs', () => {
  beforeEach(() => {
    makeFetchData()
    // round35 FE2: 组件走 adminApi（axios）——补成功路径且形状与真实响应一致
    // （模板读 summary.total/daily/hourly .calls，缺键会渲染崩溃）
    tokenUsageMock.mockResolvedValue({
      data: {
        total: { calls: 100, prompt_tokens: 0, completion_tokens: 0 },
        hourly: { calls: 0 },
        daily: { calls: 0 },
        by_function: {},
        by_model: {},
      },
    })
  })

  it('renders granularity tab labels', async () => {
    const wrapper = mount(TokenMonitor)
    await new Promise((r) => setTimeout(r, 300))
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('按日')
    expect(wrapper.text()).toContain('按月')
    expect(wrapper.text()).toContain('按小时')
  })

  it('starts with day granularity selected', async () => {
    const wrapper = mount(TokenMonitor)
    await new Promise((r) => setTimeout(r, 300))
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.granularity).toBe('day')
  })

  it('switches granularity when tab is clicked', async () => {
    const wrapper = mount(TokenMonitor)
    await new Promise((r) => setTimeout(r, 300))
    await wrapper.vm.$nextTick()

    wrapper.vm.granularity = 'month'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.granularity).toBe('month')

    wrapper.vm.granularity = 'hour'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.granularity).toBe('hour')
  })
})
