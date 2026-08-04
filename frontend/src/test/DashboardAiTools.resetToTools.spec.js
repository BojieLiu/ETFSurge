/**
 * O15 (round7 §7 P17): 重新进入「AI工具」tab → 复位到工具列表。
 *
 * P17 根因: AppTabs 用 :hidden 常驻面板，DashboardAiTools 跨 tab 切换从不销毁，
 * 内部 activeCoreFeature/designStep/designTab/expandedPlan 残留 + onMounted
 * getDesignState 恢复 → 进入 AI 工具默认停在上次界面（历史方案/旧结果）。
 *
 * 修复: 父级传 :active prop；false→true 且无 running 任务时 resetToTools()
 * （activeCoreFeature=null 等），有 running 任务则保留恢复 loading。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('../api', () => ({
  portfolioApi: {
    strategyCheck: vi.fn(),
    designAsync: vi.fn(),
    getTask: vi.fn(),
    getStrategyCheckResult: vi.fn().mockRejectedValue(new Error('no result yet')),
    getDesign: vi.fn().mockRejectedValue(new Error('not found')),
    listDesigns: vi.fn().mockResolvedValue({ data: [] }),
    listStrategyChecks: vi.fn().mockResolvedValue({ data: [] }),
    applyPortfolioDesign: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ fetchEtfs: vi.fn(), etfs: [], capitalOn: 500000, capitalOff: 0 }),
}))
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn() }),
}))
vi.mock('../stores/task', () => ({
  useTaskStore: () => ({
    tasks: [],
    getTask: vi.fn(() => null),
    addTask: vi.fn(),
    updateTask: vi.fn(),
    removeTask: vi.fn(),
    hasRunningTask: false,
    activeTaskId: null,
    getDesignState: vi.fn(() => null),
    clearDesignState: vi.fn(),
    persistDesignState: vi.fn(),
    clearCompleted: vi.fn(),
    registerTaskCompletion: vi.fn(),
  }),
}))

vi.mock('../components/FactorModelView.vue', () => ({
  default: { name: 'FactorModelView', template: '<div data-testid="factor-model-view" />' },
}))
vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div data-testid="design-wizard" />' } }))
vi.mock('../components/design/DesignLoading.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div data-testid="design-result" />' } }))
vi.mock('../components/design/DesignHistory.vue', () => ({ default: { template: '<div data-testid="design-history" />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/ui/AppModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

import DashboardAiTools from '../views/DashboardAiTools.vue'

describe('DashboardAiTools — 重新进入复位 (O15)', () => {
  function toolsListVisible(wrapper) {
    // 工具列表态 = activeCoreFeature=null → FactorModelView 可见 + 无 wizard/result/history
    return (
      wrapper.find('[data-testid="factor-model-view"]').exists() &&
      !wrapper.find('[data-testid="design-wizard"]').exists() &&
      !wrapper.find('[data-testid="design-result"]').exists() &&
      !wrapper.find('[data-testid="design-history"]').exists()
    )
  }

  it('active false→true 且无任务 → 复位到工具列表', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()

    // 进入 design wizard（模拟用户操作）
    await wrapper.vm.enterDesignMode()
    await flushPromises()
    expect(wrapper.find('[data-testid="design-wizard"]').exists()).toBe(true)

    // 切走再切回 → active true
    await wrapper.setProps({ active: true })
    await flushPromises()
    expect(toolsListVisible(wrapper)).toBe(true)
  })

  it('active 初始为 true（默认落工具列表）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: true } })
    await flushPromises()
    expect(toolsListVisible(wrapper)).toBe(true)
  })
})
