import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { changeClass } from './changeClass'

// --- Issue 1: P&L color convention (红涨绿跌) ---
// Positive / zero values must map to the UP (red) class.
// Negative values must map to the DOWN (green) class.
describe('changeClass (红涨绿跌)', () => {
  it('maps a positive value to text-up (red)', () => {
    expect(changeClass(1.23)).toBe('text-up')
  })

  it('maps zero to text-up (red)', () => {
    expect(changeClass(0)).toBe('text-up')
  })

  it('maps a negative value to text-down (green)', () => {
    expect(changeClass(-0.5)).toBe('text-down')
  })

  it('maps a large negative value to text-down (green)', () => {
    expect(changeClass(-99.99)).toBe('text-down')
  })
})

// --- Issue 2: AI tool buttons (moved to DashboardAiTools) ---
vi.mock('../api', () => ({
  portfolioApi: {
    list: vi.fn(() => Promise.resolve({ data: [] })),
    strategyCheck: vi.fn(() => Promise.resolve({ data: {} })),
    applyStrategy: vi.fn(() => Promise.resolve({ data: {} })),
    applyPortfolioDesign: vi.fn(() => Promise.resolve({ data: {} })),
  },
  analysisApi: {
    portfolioDesignStream: vi.fn(() => Promise.resolve({ data: {} })),
    portfolioDesign: vi.fn(() => Promise.resolve({ data: {} })),
  },
  marketApi: {},
}))

vi.mock('../stores/toast', () => ({ useToastStore: () => ({ show: vi.fn() }) }))
vi.mock('../stores/portfolio', () => ({ usePortfolioStore: () => ({ etfs: [] }) }))

const DashboardAiTools = (await import('../views/DashboardAiTools.vue')).default

describe('core-actions buttons', () => {
  it('renders a concise title plus a separate helper description for each action', () => {
    const wrapper = mount(DashboardAiTools, {
      global: {
        plugins: [createPinia()],
        stubs: { AppButton: true, AppInput: true, DesignWizard: true, DesignLoading: true, DesignResult: true, DesignHistory: true, StrategyCheckModal: true, StrategyCheckResult: true },
      },
    })

    const buttons = wrapper.findAll('button.core-action-btn')
    expect(buttons.length).toBe(3)

    const designBtn = buttons[0]
    const strategyBtn = buttons[1]

    const designTitle = designBtn.find('.action-title').text()
    const designDesc = designBtn.find('.action-desc').text()
    const strategyTitle = strategyBtn.find('.action-title').text()
    const strategyDesc = strategyBtn.find('.action-desc').text()

    // Concise titles (no long explanatory sentence inside the title)
    expect(designTitle).toBe('智能设计ETF组合方案')
    expect(strategyTitle).toBe('策略检查分析')

    // Helper descriptions remain present and clearly separated
    expect(designDesc.length).toBeGreaterThan(0)
    expect(strategyDesc.length).toBeGreaterThan(0)

    // Title must not contain the explanatory sentence (separation enforced)
    expect(designTitle).not.toContain('输入资金')
    expect(strategyTitle).not.toContain('优化')
  })
})
