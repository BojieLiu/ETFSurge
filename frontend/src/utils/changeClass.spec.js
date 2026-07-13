import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
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

// --- Issue 2: core-actions button text (concise title + helper desc) ---
vi.mock('../api', () => ({
  portfolioApi: {
    getAllocation: vi.fn(() => Promise.resolve({ data: { allocations: [] } })),
    getDailyPnl: vi.fn(() => Promise.resolve({ data: { items: [] } })),
  },
  analysisApi: { designPortfolio: vi.fn(), checkStrategy: vi.fn() },
  marketApi: { indicesGlobal: vi.fn(() => Promise.resolve({ data: { indices: {} } })) },
}))

vi.mock('../composables/useMarketWS', () => ({
  useMarketWS: () => ({ connect: vi.fn(), disconnect: vi.fn(), onMarketData: vi.fn() }),
}))

vi.mock('../stores/toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('../stores/portfolio', () => ({ usePortfolioStore: () => ({ etfs: [] }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({}), useRouter: () => ({ push: vi.fn() }) }))

const Dashboard = (await import('../components/Dashboard.vue')).default

describe('core-actions buttons', () => {
  it('renders a concise title plus a separate helper description for each action', () => {
    const wrapper = mount(Dashboard, {
      global: {
        stubs: { VChart: true, AppButton: true, AppInput: true, Skeleton: true },
      },
    })

    const buttons = wrapper.findAll('button.core-action-btn')
    expect(buttons.length).toBe(2)

    const designBtn = buttons[0]
    const strategyBtn = buttons[1]

    const designTitle = designBtn.find('.action-title').text()
    const designDesc = designBtn.find('.action-desc').text()
    const strategyTitle = strategyBtn.find('.action-title').text()
    const strategyDesc = strategyBtn.find('.action-desc').text()

    // Concise titles (no long explanatory sentence inside the title)
    expect(designTitle).toBe('AI 组合设计')
    expect(strategyTitle).toBe('策略检查')

    // Helper descriptions remain present and clearly separated
    expect(designDesc.length).toBeGreaterThan(0)
    expect(strategyDesc.length).toBeGreaterThan(0)

    // Title must not contain the explanatory sentence (separation enforced)
    expect(designTitle).not.toContain('ETF')
    expect(strategyTitle).not.toContain('权重')
  })
})
