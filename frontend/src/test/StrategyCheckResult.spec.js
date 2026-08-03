/**
 * StrategyCheckResult component tests.
 *
 * Guards against regression of:
 *   - Loading state shows back button (+ TaskProgress stub)
 *   - Error state shows error text + return button
 *   - Result state renders strategy suggestions + risk warnings + back
 *   - Emitting 'close' from all three states
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StrategyCheckResult from '../components/design/StrategyCheckResult.vue'

describe('StrategyCheckResult.vue', () => {
  const stubs = {
    AppButton: { template: '<button class="app-btn-stub"><slot /></button>' },
    TaskProgress: { template: '<div class="task-progress-stub" />' },
  }

  describe('loading state', () => {
    it('shows back button and TaskProgress when loading=true', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { loading: true, taskStatus: 'running' },
        global: { stubs },
      })
      expect(wrapper.find('.loading-state').exists()).toBe(true)
      expect(wrapper.find('.sr-back').text()).toContain('返回')
      expect(wrapper.find('.task-progress-stub').exists()).toBe(true)
    })

    it('emits close when back button is clicked in loading state', async () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { loading: true },
        global: { stubs },
      })
      await wrapper.find('.sr-back').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })

  describe('error state', () => {
    it('shows error text and return button when error is set', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { error: '策略检查超时，数据源响应过慢', result: null },
        global: { stubs },
      })
      expect(wrapper.find('.error-state').exists()).toBe(true)
      expect(wrapper.text()).toContain('策略检查超时，数据源响应过慢')
      expect(wrapper.find('.app-btn-stub').exists()).toBe(true)
    })

    it('emits close when return is clicked in error state', async () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { error: '测试错误' },
        global: { stubs },
      })
      await wrapper.find('.app-btn-stub').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('does NOT render error state when result is also present', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { error: '旧错误', result: { market_regime: 'range_bound', summary: 'ok' } },
        global: { stubs },
      })
      // result takes precedence over error
      expect(wrapper.find('.error-state').exists()).toBe(false)
      expect(wrapper.find('.strategy-result').exists()).toBe(true)
    })
  })

  describe('result state', () => {
    const mockResult = {
      market_regime: 'correction',
      summary: '当前市场处于回调阶段，建议防御配置',
      suggestions: [
        { symbol: '510300', name: '沪深300ETF', action: 'decrease', current_weight: 0.3, suggested_weight: 0.2, reason: '减少风险暴露', confidence: 'high' },
      ],
      risk_warnings: [
        { type: 'concentration', severity: 'high', description: '行业集中度过高' },
      ],
      holdings_analysis: [
        { symbol: '510300', name: '沪深300', factor_summary: '动量-0.8', tech_signal: '卖出' },
      ],
    }

    it('renders result header with market regime and summary', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.find('.strategy-result').exists()).toBe(true)
      expect(wrapper.text()).toContain('策略检查结果')
      // regime label
      expect(wrapper.text()).toContain('回调')
      expect(wrapper.text()).toContain('当前市场处于回调阶段')
    })

    it('renders back button in result header and emits close', async () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      const backBtns = wrapper.findAll('.sr-back')
      expect(backBtns.length).toBeGreaterThanOrEqual(1)
      await backBtns[0].trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('renders suggestion cards with correct label', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.text()).toContain('减配')
      expect(wrapper.text()).toContain('沪深300ETF')
      expect(wrapper.text()).toContain('510300')
      expect(wrapper.text()).toContain('高置信度')
    })

    it('renders risk warnings section', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.text()).toContain('风险预警')
      expect(wrapper.text()).toContain('行业集中度过高')
    })

    it('renders holdings analysis table', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.text()).toContain('持仓明细分析')
      expect(wrapper.text()).toContain('沪深300')
      expect(wrapper.text()).toContain('动量-0.8')
    })

    // F10 (round6 §十五): 口径标注——技术信号列标"实时"、建议标"因子分主导"、背离高亮
    it('F10: 技术信号列标注"实时"口径', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.text()).toContain('技术信号（实时）')
    })

    it('F10: 操作建议卡片标注"因子分主导 · 规则引擎"', () => {
      const wrapper = mount(StrategyCheckResult, {
        props: { result: mockResult },
        global: { stubs },
      })
      expect(wrapper.find('.source-tag').exists()).toBe(true)
      expect(wrapper.find('.source-tag').text()).toContain('因子分主导')
    })

    it('F10: action=hold 且实时信号 SELL → 背离高亮提示', () => {
      const divergent = {
        ...mockResult,
        suggestions: [
          { symbol: '159992', name: '创新药ETF', action: 'hold', current_weight: 0.1, suggested_weight: 0.1, reason: '因子分强正', confidence: 'medium' },
        ],
        holdings_analysis: [
          { symbol: '159992', name: '创新药', factor_summary: '3.57', tech_signal: 'SELL' },
        ],
      }
      const wrapper = mount(StrategyCheckResult, {
        props: { result: divergent },
        global: { stubs },
      })
      const card = wrapper.find('.suggestion-card')
      expect(card.classes()).toContain('sc-divergence')
      expect(wrapper.text()).toContain('技术信号与建议背离')
    })

    it('F10: 无背离（hold + 信号也 hold）→ 不高亮', () => {
      const calm = {
        ...mockResult,
        suggestions: [
          { symbol: '510300', name: '沪深300ETF', action: 'hold', current_weight: 0.1, suggested_weight: 0.1, reason: '中性', confidence: 'medium' },
        ],
        holdings_analysis: [
          { symbol: '510300', name: '沪深300', factor_summary: '0.2', tech_signal: 'hold' },
        ],
      }
      const wrapper = mount(StrategyCheckResult, {
        props: { result: calm },
        global: { stubs },
      })
      expect(wrapper.find('.suggestion-card').classes()).not.toContain('sc-divergence')
    })
  })
})
