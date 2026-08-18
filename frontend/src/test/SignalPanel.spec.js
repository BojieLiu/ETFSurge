/**
 * SignalPanel 信号口径测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - P2-6：标题「技术信号」+ 副标题口径注明（基于 K 线技术指标，不含因子与基本面）
 * - R25：中性区 info reason + compositeDecision 降级/健康/缺省三态
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SignalPanel from '../components/analysis/SignalPanel.vue'

function mountPanel(overrides = {}) {
  return mount(SignalPanel, {
    props: {
      indicatorData: { rsi: 43.4, ma5: 4.2, ma20: 4.14 },
      signal: { signal: 'buy', score: 1.5, reasons: ['MACD偏多', 'MA5>MA20 多头排列'] },
      loading: false,
      ...overrides,
    },
  })
}

function mountPanelR25(overrides = {}) {
  return mount(SignalPanel, {
    props: {
      indicatorData: { rsi: 52.4, kdj: { k: 50.1, d: 49.8 }, ma5: 4.2, ma20: 4.14 },
      signal: { signal: 'hold', score: 0, reasons: [] },
      loading: false,
      ...overrides,
    },
  })
}

describe('SignalPanel P2-6 信号口径', () => {
  it('标题为「技术信号」（负向：含「综合信号」 → FAIL）', () => {
    const wrapper = mountPanel()
    const title = wrapper.find('.signal-section .card-title').text()
    expect(title).toContain('技术信号')
    expect(title).not.toContain('综合信号')
  })

  it('副标题注明口径：基于 K 线技术指标，不含因子与基本面', () => {
    const wrapper = mountPanel()
    const caption = wrapper.find('.signal-caption').text()
    expect(caption).toContain('基于 K 线技术指标')
    expect(caption).toContain('RSI')
    expect(caption).toContain('不含因子与基本面')
  })

  it('信号内容仍正常渲染（buy 买入 + 技术依据）', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.signal-badge').text()).toContain('买入')
    expect(wrapper.text()).toContain('MACD偏多')
  })

  it('loading 时不渲染信号卡', () => {
    const wrapper = mountPanel({ loading: true, signal: null })
    expect(wrapper.find('.signal-section').exists()).toBe(false)
  })
})

describe('SignalPanel R25 中性区 info + 综合信号卡', () => {
  it('calm 市 reasons 空 → 显示「RSI 中性」info（Q1 误导消除）', () => {
    const wrapper = mountPanelR25()
    const info = wrapper.find('.signal-neutral-info')
    expect(info.exists()).toBe(true)
    expect(info.text()).toContain('RSI=52.4 中性')
    expect(info.text()).toContain('KDJ 中段')
    expect(info.text()).toContain('无极端信号')
  })

  it('有极端 reason（超买）→ 不显示中性 info', () => {
    const wrapper = mountPanelR25({
      signal: { signal: 'sell', score: -2, reasons: ['RSI=75.0 超买'] },
    })
    expect(wrapper.find('.signal-neutral-info').exists()).toBe(false)
  })

  it('compositeDecision.degraded → 显示「因子缺失」降级徽标，无合成结论', () => {
    const wrapper = mountPanelR25({
      compositeDecision: {
        signal: null, score: null, degraded: true,
        reason: '因子数据缺失 100%：综合信号不可用（退化为纯技术信号）',
      },
    })
    const degraded = wrapper.find('.composite-degraded')
    expect(degraded.exists()).toBe(true)
    // round27 R52: 组件渲染「因子缺失，综合信号不可用」（signal=null → compositeUnavailable），
    // 断言公共子串「因子缺失」覆盖两种文案（含兜底 reason「因子数据缺失，综合信号不可用」）
    expect(degraded.text()).toContain('因子缺失')
    // 负向：降级态不得出现「买入/卖出/持有」合成结论
    expect(degraded.text()).not.toMatch(/买入|卖出|持有/)
  })

  it('compositeDecision 健康 → 显示「综合信号」卡 + 合成结论', () => {
    const wrapper = mountPanelR25({
      compositeDecision: { signal: 'buy', score: 0.72, degraded: false, reason: 'ok' },
    })
    expect(wrapper.find('.composite-section').exists()).toBe(true)
    expect(wrapper.find('.composite-section').text()).toContain('综合信号')
    expect(wrapper.find('.composite-section').text()).toContain('买入')
  })

  it('无 compositeDecision → 不渲染综合信号卡', () => {
    const wrapper = mountPanelR25()
    expect(wrapper.find('.composite-section').exists()).toBe(false)
  })

  it('原技术信号卡标题不含「综合信号」（P2-6 负向保持）', () => {
    const wrapper = mountPanelR25()
    const title = wrapper.find('.signal-section .card-title').text()
    expect(title).toContain('技术信号')
    expect(title).not.toContain('综合信号')
  })
})
