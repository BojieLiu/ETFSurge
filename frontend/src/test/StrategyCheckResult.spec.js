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
  })
})
