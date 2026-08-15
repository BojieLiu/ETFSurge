/**
 * round24 R25: 信号口径三面一致——中性区 info reason + 综合信号降级卡
 *（docs/round24 §12.1 R25）。
 *
 * 验收：
 * ① calm 市（RSI 40-60、reasons 空）→ 显示「RSI 中性」info（消除 caption 承诺
 *    RSI/KDJ 但 reason 只显 MACD/MA 的 Q1 误导）；
 * ② compositeDecision.degraded=true → 「因子数据缺失，综合信号不可用」降级徽标，
 *    不显示合成信号；
 * ③ compositeDecision 健康 → 显示「综合信号」卡 + 买入/卖出/持有；
 * ④ 原技术信号卡保持（P2-6 负向：标题不得含「综合信号」）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SignalPanel from '../components/analysis/SignalPanel.vue'

function mountPanel(overrides = {}) {
  return mount(SignalPanel, {
    props: {
      indicatorData: { rsi: 52.4, kdj: { k: 50.1, d: 49.8 }, ma5: 4.2, ma20: 4.14 },
      signal: { signal: 'hold', score: 0, reasons: [] },
      loading: false,
      ...overrides,
    },
  })
}

describe('SignalPanel R25 中性区 info + 综合信号卡', () => {
  it('calm 市 reasons 空 → 显示「RSI 中性」info（Q1 误导消除）', () => {
    const wrapper = mountPanel()
    const info = wrapper.find('.signal-neutral-info')
    expect(info.exists()).toBe(true)
    expect(info.text()).toContain('RSI=52.4 中性')
    expect(info.text()).toContain('KDJ 中段')
    expect(info.text()).toContain('无极端信号')
  })

  it('有极端 reason（超买）→ 不显示中性 info', () => {
    const wrapper = mountPanel({
      signal: { signal: 'sell', score: -2, reasons: ['RSI=75.0 超买'] },
    })
    expect(wrapper.find('.signal-neutral-info').exists()).toBe(false)
  })

  it('compositeDecision.degraded → 显示「因子缺失」降级徽标，无合成结论', () => {
    const wrapper = mountPanel({
      compositeDecision: {
        signal: null, score: null, degraded: true,
        reason: '因子数据缺失 100%：综合信号不可用（退化为纯技术信号）',
      },
    })
    const degraded = wrapper.find('.composite-degraded')
    expect(degraded.exists()).toBe(true)
    expect(degraded.text()).toContain('因子数据缺失')
    // 负向：降级态不得出现「买入/卖出/持有」合成结论
    expect(degraded.text()).not.toMatch(/买入|卖出|持有/)
  })

  it('compositeDecision 健康 → 显示「综合信号」卡 + 合成结论', () => {
    const wrapper = mountPanel({
      compositeDecision: { signal: 'buy', score: 0.72, degraded: false, reason: 'ok' },
    })
    expect(wrapper.find('.composite-section').exists()).toBe(true)
    expect(wrapper.find('.composite-section').text()).toContain('综合信号')
    expect(wrapper.find('.composite-section').text()).toContain('买入')
  })

  it('无 compositeDecision → 不渲染综合信号卡', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.composite-section').exists()).toBe(false)
  })

  it('原技术信号卡标题不含「综合信号」（P2-6 负向保持）', () => {
    const wrapper = mountPanel()
    const title = wrapper.find('.signal-section .card-title').text()
    expect(title).toContain('技术信号')
    expect(title).not.toContain('综合信号')
  })
})