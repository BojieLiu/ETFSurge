/**
 * F3 (round6 §13.3): 因子模型概览仅在工具列表/初始态显示——
 * 具体工具（strategy/design/history）打开时隐藏，退出后恢复。
 * 旧实现 DashboardAiTools.vue:110 无条件渲染 <FactorModelView />。
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

// FactorModelView 与其余子组件 stub——本测试只关心挂载/卸载
vi.mock('../components/FactorModelView.vue', () => ({
  default: { name: 'FactorModelView', template: '<div data-testid="factor-model-view" />' },
}))
vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignLoading.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignHistory.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/ui/AppModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

import DashboardAiTools from '../views/DashboardAiTools.vue'

describe('DashboardAiTools — FactorModelView 可见性 (F3)', () => {
  async function mountView() {
    const wrapper = mount(DashboardAiTools, { attachTo: document.body })
    await flushPromises()
    return wrapper
  }

  function factorView(wrapper) {
    return wrapper.find('[data-testid="factor-model-view"]')
  }

  it('初始（activeCoreFeature=null）时因子模型概览可见', async () => {
    const wrapper = await mountView()
    expect(factorView(wrapper).exists()).toBe(true)
    wrapper.unmount()
  })

  it('打开具体工具（strategy/design/history）后因子模型概览卸载', async () => {
    const wrapper = await mountView()
    expect(factorView(wrapper).exists()).toBe(true)
    for (const feature of ['strategy', 'design', 'history']) {
      wrapper.vm.activeCoreFeature = feature
      await flushPromises()
      expect(factorView(wrapper).exists()).toBe(false)
    }
    wrapper.unmount()
  })

  it('退出工具后因子模型概览恢复显示', async () => {
    const wrapper = await mountView()
    wrapper.vm.activeCoreFeature = 'strategy'
    await flushPromises()
    expect(factorView(wrapper).exists()).toBe(false)
    wrapper.vm.activeCoreFeature = null
    await flushPromises()
    expect(factorView(wrapper).exists()).toBe(true)
    wrapper.unmount()
  })
})
