/**
 * round17 P2-6: 两套信号口径 UI 区分。
 *
 * - 标题「技术信号」（非「综合信号」——负向：误称"综合" → FAIL）
 * - 副标题注明口径：基于 K 线技术指标（RSI/KDJ/MACD/MA），不含因子与基本面
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
