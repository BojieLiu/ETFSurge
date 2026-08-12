/**
 * F2 (round6 §13.2): IC 图负值柱 label 位置——旧实现 label.position 固定 'right'，
 * 负值柱标签压在柱身上（文字与图案重叠）。
 * F22 (round6 §17.1): 政策 static 因子展示——stats-row 静态项、分类行"N 静态"
 * 替代"0 有效"、因子行静态徽标、IC 语义"静态（不参与 IC）"。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const { getActiveMock } = vi.hoisted(() => ({ getActiveMock: vi.fn() }))

vi.mock('../api', () => ({ factorsApi: { getActive: (...a) => getActiveMock(...a) } }))

// echarts mock：捕获 setOption 配置供 F2 断言
const capturedOptions = []
const initMock = vi.fn(() => ({
  setOption: (opt) => capturedOptions.push(opt),
  dispose: vi.fn(),
  resize: vi.fn(),
}))
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: (...a) => initMock(...a),
}))
vi.mock('echarts/charts', () => ({ BarChart: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {} }))
vi.mock('./ui/AppTooltip.vue', () => ({
  default: { name: 'AppTooltip', template: '<span><slot /><slot name="content" /></span>' },
}))

import FactorModelView from '../components/FactorModelView.vue'

function makeData() {
  const mk = (code, name, status, ic = null) => ({
    code, name, status, ic_value: ic, ic_threshold: 0.02,
    description: `${name}描述`, standardization: 'zscore', category: 'china_specific',
  })
  return {
    total: 33,
    categories: [
      {
        name: 'technical', count: 10, valid_count: 10, warn_count: 0, no_data_count: 0,
        static_count: 0, avg_ic: 0.05,
        factors: [
          mk('technical.rsi.rsi_14', 'RSI(14)', 'valid', 0.031),
          mk('technical.macd.macd', 'MACD', 'valid', -0.044),
          mk('technical.atr.atr', 'ATR', 'valid', -0.39),
        ],
      },
      {
        name: 'china_specific', count: 3, valid_count: 0, warn_count: 0, no_data_count: 0,
        static_count: 3, avg_ic: null,
        factors: [
          mk('china.policy.five_year_plan', '五年规划', 'static'),
          mk('china.policy.strategic_emerging', '战略新兴', 'static'),
          mk('china.policy.dual_circulation', '双循环', 'static'),
        ],
      },
    ],
    summary: { valid: 10, warn: 0, no_data: 0, static: 3, avg_ic: 0.05 },
    updated_at: '2026-08-04T00:00:00Z',
  }
}

describe('FactorModelView — F22 政策 static 展示', () => {
  beforeEach(() => {
    capturedOptions.length = 0
    getActiveMock.mockReset().mockResolvedValue({ data: makeData() })
  })

  it('stats-row 显示静态标识项（summary.static），总览数字自洽 10+3', async () => {
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    const stats = wrapper.findAll('.stat-item')
    const labels = stats.map((s) => s.text())
    const staticItem = labels.find((t) => t.includes('静态'))
    expect(staticItem).toBeTruthy()
    expect(staticItem).toContain('3')
    wrapper.unmount()
  })

  it('china_specific 分类行显示"N 静态"而非"0 有效"', async () => {
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    const catHeaders = wrapper.findAll('.cat-header')
    const china = catHeaders.find((h) => h.text().includes('政策因子'))
    expect(china).toBeTruthy()
    const text = china.text()
    expect(text).toContain('3 静态')
    expect(text).not.toContain('0 有效')
    wrapper.unmount()
  })

  it('static 因子行带"静态"徽标', async () => {
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    // 展开 china_specific 分类
    const china = wrapper.findAll('.cat-header').find((h) => h.text().includes('政策因子'))
    china.trigger('click')
    await flushPromises()
    const badges = wrapper.findAll('.factor-static-badge')
    expect(badges.length).toBe(3)
    wrapper.unmount()
  })

  it('IC tooltip 中 static 因子语义为"静态（不参与 IC）"', async () => {
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    const china = wrapper.findAll('.cat-header').find((h) => h.text().includes('政策因子'))
    china.trigger('click')
    await flushPromises()
    const text = wrapper.text()
    // static 因子 tooltip 标注"静态标识…不参与 IC 统计，非数据缺失"
    expect(text).toContain('静态标识')
    expect(text).toContain('不参与 IC 统计')
    wrapper.unmount()
  })
})

describe('FactorModelView — F2 IC 图负值柱 label', () => {
  beforeEach(() => {
    capturedOptions.length = 0
    getActiveMock.mockReset().mockResolvedValue({ data: makeData() })
  })

  it('series label.position 为动态函数（正值 right / 负值 left），负值不再压柱身', async () => {
    mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    expect(capturedOptions.length).toBeGreaterThan(0)
    const opt = capturedOptions[capturedOptions.length - 1]
    const label = opt.series[0].label
    expect(typeof label.position).toBe('function')
    // 正/负值分支：正值 right，负值 left
    expect(label.position({ value: 0.05 })).toBe('right')
    expect(label.position({ value: -0.39 })).toBe('left')
  })

  it('series 配置 labelLayout.moveOverlap=shiftY 防相邻柱标签互叠', async () => {
    mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    const opt = capturedOptions[capturedOptions.length - 1]
    expect(opt.series[0].labelLayout).toEqual({ moveOverlap: 'shiftY' })
  })
})

describe('FactorModelView - P0-7 数据积累期引导', () => {
  it('valid=0 且 no_data>0 显示数据积累中 banner', async () => {
    const data = makeData()
    data.summary = { valid: 0, warn: 0, no_data: 27, static: 3, avg_ic: 0.05 }
    data.categories = data.categories.map((c) => ({
      ...c, valid_count: 0, no_data_count: 27, static_count: 3,
      factors: [{ code: c.code || 'x', name: 'x', status: 'no_data', ic_value: null,
                  ic_threshold: 0.02, description: 'd', standardization: 'zscore', category: c.name }],
    }))
    getActiveMock.mockReset().mockResolvedValue({ data })
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    const banner = wrapper.find('.accumulate-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('数据积累中')
    expect(banner.text()).toContain('27')
    wrapper.unmount()
  })

  it('valid>0 时不显示数据积累中 banner', async () => {
    getActiveMock.mockReset().mockResolvedValue({ data: makeData() })
    const wrapper = mount(FactorModelView, { attachTo: document.body })
    await flushPromises()
    expect(wrapper.find('.accumulate-banner').exists()).toBe(false)
    wrapper.unmount()
  })
})
