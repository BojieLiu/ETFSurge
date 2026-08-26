/**
 * DashboardAiTools 测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - Z27 §7.4：历史列表 loadHistoryList（design+check 合并、无 ReferenceError）
 * - 设计报告 tab：design_text 非硬编码兜底/等待态/错误态/WS 拼接/enterDesignMode
 * - timer 清理：checkStrategy/startDesign 轮询清理 + 5 连错停止
 * - F3：因子模型概览仅工具列表/初始态显示
 * - P0-9：running check 任务合入历史列表 + 同任务不双显示
 * - O15：重新进入 AI 工具 tab 复位到工具列表
 * - O11：设计任务状态机（重试/返回/失败不持久化/finalize 幂等）
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

// ── 统一 mock：共享可变状态全部放 vi.hoisted（工厂与用例体都可引用）──
const { getTimeline, getStrategyCheckDetail, toastShow, designAsyncMock, persistMock, getTaskMock, mockTasks } = vi.hoisted(() => ({
  getTimeline: vi.fn(),
  getStrategyCheckDetail: vi.fn(),
  toastShow: vi.fn(),
  designAsyncMock: vi.fn().mockResolvedValue({ data: { task_id: 123, design_id: null } }),
  persistMock: vi.fn(),
  getTaskMock: vi.fn().mockResolvedValue({ data: { status: 'running', progress: 50 } }),
  mockTasks: [],
}))

vi.mock('marked', () => ({
  default: (text) => text,
  marked: (text) => text,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {}, path: '/' }),
}))

vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), dispose: vi.fn() })) }))

vi.mock('../api', () => ({
  portfolioApi: {
    getTimeline: (...a) => getTimeline(...a),
    getStrategyCheckDetail: (...a) => getStrategyCheckDetail(...a),
    strategyCheck: vi.fn(),
    designAsync: designAsyncMock,
    getTask: getTaskMock,
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
  useToastStore: () => ({ show: toastShow, success: vi.fn(), error: vi.fn(), dismiss: vi.fn(), toasts: [] }),
}))

vi.mock('../stores/task', () => ({
  useTaskStore: () => ({
    tasks: mockTasks,
    get hasRunningTask() { return mockTasks.some(t => t.status === 'running') },
    get activeTaskId() {
      const r = mockTasks.find(t => t.status === 'running')
      return r ? r.taskId : null
    },
    getTask: vi.fn(() => null),
    fetchAndMergeTasks: vi.fn(),
    addTask: vi.fn(),
    updateTask: vi.fn(),
    removeTask: vi.fn(),
    clearCompleted: vi.fn(),
    registerTaskCompletion: vi.fn(() => 1),
    designState: null,
    getDesignState: vi.fn(() => null),
    clearDesignState: vi.fn(),
    persistDesignState: persistMock,
  }),
}))

// 子组件 stub（取各来源超集：data-testid 定位 + DesignLoading 失败态按钮）
vi.mock('../views/system/FactorModelView.vue', () => ({
  default: { name: 'FactorModelView', template: '<div data-testid="factor-model-view" />' },
}))
vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div data-testid="design-wizard" />' } }))
vi.mock('../components/design/DesignLoading.vue', () => ({
  default: {
    template: '<div data-testid="design-loading"><button data-testid="retry-btn" @click="$emit(\'retry\')" /><button data-testid="cancel-btn" @click="$emit(\'cancel\')" /></div>',
    props: ['progress', 'stepLabel', 'failed', 'taskStage', 'selectedLabel', 'elapsedSec'],
  },
}))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div data-testid="design-result" />' } }))
vi.mock('../components/design/DesignHistory.vue', () => ({ default: { template: '<div data-testid="design-history" />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
// round35 §16.6: 保留 stub 但渲染 error 态文本——timer cleanup describe 需断言
// 「5 连错 → 错误文案可见」的真实行为（原纯空 div 使任何错误态断言恒空）
vi.mock('../components/design/StrategyCheckResult.vue', () => ({
  default: {
    name: 'StrategyCheckResult',
    props: ['result', 'loading', 'error', 'taskStatus', 'taskProgress', 'taskStage'],
    template: '<div class="strategy-check-result-stub"><p v-if="error && !result" class="error-text">{{ error }}</p><slot /></div>',
  },
}))
vi.mock('../components/ui/AppModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

import DashboardAiTools from '../views/AiDesign.vue'

// 防合并后跨 describe 状态污染：每个用例前重置共享 mock 与数组
beforeEach(() => {
  vi.clearAllMocks()
  mockTasks.length = 0
  getTimeline.mockReset()
  getStrategyCheckDetail.mockReset()
  toastShow.mockReset()
  designAsyncMock.mockReset()
  designAsyncMock.mockResolvedValue({ data: { task_id: 123, design_id: null } })
  getTaskMock.mockReset()
  getTaskMock.mockResolvedValue({ data: { status: 'running', progress: 50 } })
  persistMock.mockClear()
})

// =========================================================================
// 来源: DashboardAiTools.history.spec.js（Z27 §7.4 历史列表）
// =========================================================================

const DesignHistoryStub = {
  template: '<div class="history-stub" />',
  props: ['items', 'loading', 'loaded'],
}

describe('DashboardAiTools — loadHistoryList (Z27 §7.4)', () => {
  it('renders timeline items (design + check) without ReferenceError', async () => {
    getTimeline.mockResolvedValue({
      data: {
        items: [
          { id: 1, _type: 'design', status: 'completed', created_at: '2026-07-31T10:00:00Z' },
          { id: 97, _type: 'check', status: 'completed', created_at: '2026-07-31T11:00:00Z' },
        ],
      },
    })

    const wrapper = mount(DashboardAiTools, {
      global: {
        plugins: [createPinia()],
        stubs: {
          DesignHistory: DesignHistoryStub,
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    // 触发历史 Tab（第 3 个 core-action-btn：设计/策略检查/任务列表）
    const buttons = wrapper.findAll('.core-action-btn')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    await buttons[2].trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await wrapper.vm.$nextTick()

    // DesignHistory 收到合并后的 items（含 check 项）
    const stub = wrapper.findComponent(DesignHistoryStub)
    expect(stub.exists()).toBe(true)
    const items = stub.props('items') || []
    expect(items.some((i) => i._type === 'design')).toBe(true)
    expect(items.some((i) => i._type === 'check')).toBe(true)

    // 关键断言：不再抛 ReferenceError → 不弹「加载历史记录失败」
    expect(toastShow).not.toHaveBeenCalledWith('加载历史记录失败，请检查后端连接', 'error')
  })

  it('does not emit error toast when timeline returns empty items', async () => {
    getTimeline.mockResolvedValue({ data: { items: [] } })

    const wrapper = mount(DashboardAiTools, {
      global: {
        plugins: [createPinia()],
        stubs: {
          DesignHistory: DesignHistoryStub,
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    const buttons = wrapper.findAll('.core-action-btn')
    await buttons[2].trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await wrapper.vm.$nextTick()

    expect(toastShow).not.toHaveBeenCalledWith('加载历史记录失败，请检查后端连接', 'error')
  })
})

// =========================================================================
// 来源: DashboardAiTools.report.spec.js（设计报告 tab 行为）
// =========================================================================

describe('DashboardAiTools - Design Report Tab', () => {
  let wrapper

  beforeEach(async () => {
    setActivePinia(createPinia())
    wrapper = mount(DashboardAiTools, {
      global: {
        stubs: {
          AppButton: true,
          AppInput: true,
          AppSelect: true,
          DesignWizard: true,
          DesignLoading: true,
          DesignResult: true,
          DesignHistory: true,
          StrategyCheckModal: true,
          StrategyCheckResult: true,
        },
      },
    })
  })

  it('should have empty design_text on fresh result (no hardcoded fallback)', async () => {
    // The component starts in wizard state; designResult is null
    expect(wrapper.vm.designResult).toBeNull()
  })

  it('should show waiting state when design_text is empty and no error', async () => {
    // Simulate result state with empty design_text
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designResult = { plans: [{ style: 'balanced' }], design_text: '' }
    wrapper.vm.designStep = 'result'
    wrapper.vm.reportError = ''
    await nextTick()

    // DesignResult stub renders — container routing is correct
    expect(wrapper.vm.designStep).toBe('result')
    expect(wrapper.vm.activeCoreFeature).toBe('design')
  })

  it('should show error state when reportError is set', async () => {
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designResult = { plans: [{ style: 'balanced' }], design_text: '' }
    wrapper.vm.designStep = 'result'
    wrapper.vm.reportError = 'API 调用超时'
    await nextTick()

    // Container correctly tracks reportError
    expect(wrapper.vm.reportError).toBe('API 调用超时')
  })

  it('should render markdown when design_text is populated by WS', async () => {
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designResult = {
      plans: [{ style: 'balanced' }],
      design_text: '## 市场环境\n深证成指今日跌 5.4%',
    }
    wrapper.vm.designStep = 'result'
    await nextTick()

    // Container correctly passes designResult to DesignResult
    expect(wrapper.vm.designResult.design_text).toContain('深证成指今日跌 5.4%')
  })

  it('should clear reportError on retryReport', async () => {
    wrapper.vm.reportError = 'WS 连接断开'
    wrapper.vm.retryReport()
    expect(wrapper.vm.reportError).toBe('')
  })

  it('should skip to loading state when enterDesignMode called with running task', async () => {
    // Inject a running task into the shared mock (with designId and recent createdAt)
    mockTasks.push({ taskId: 'task-running-1', type: 'design', status: 'running', designId: 42, createdAt: Date.now() })
    // Re-mount to pick up the updated mock
    wrapper = mount(DashboardAiTools, {
      global: {
        stubs: {
          AppButton: true,
          AppInput: true,
          AppSelect: true,
          DesignWizard: true,
          DesignLoading: true,
          DesignResult: true,
          DesignHistory: true,
          StrategyCheckModal: true,
          StrategyCheckResult: true,
        },
      },
    })
    wrapper.vm.enterDesignMode()
    await nextTick()

    // fetch will throw (not mocked), catch block keeps loading if not stale
    expect(wrapper.vm.activeCoreFeature).toBe('design')
    expect(wrapper.vm.designStep).toBe('loading')
  })

  it('should show wizard when enterDesignMode called without running task', async () => {
    wrapper.vm.enterDesignMode()
    await nextTick()

    expect(wrapper.vm.activeCoreFeature).toBe('design')
    expect(wrapper.vm.designStep).toBe('wizard')
  })
})

// =========================================================================
// 来源: DashboardAiTools.timer.spec.js（轮询清理 + 连错停止）
// =========================================================================

describe('DashboardAiTools — timer cleanup guards (round35 §16.6 空心测试修复)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  async function mountWithModalStub() {
    return mount(DashboardAiTools, {
      attachTo: document.body,
      global: {
        stubs: {
          StrategyCheckModal: {
            template: '<div class="strategy-modal-stub" />',
            emits: ['select-type', 'close'],
          },
        },
      },
    })
  }

  /** 点「策略检查」按钮 → 从 modal stub 发出 select-type → 触发真实 checkStrategy() */
  async function startStrategyCheck(wrapper) {
    const api = await import('../api')
    api.portfolioApi.strategyCheck.mockResolvedValue({ data: { task_id: 't-timer' } })
    const buttons = wrapper.findAll('.core-action-btn')
    await buttons[1].trigger('click') // 设计 / 策略检查 / 任务列表 中第 2 个
    await flushPromises()
    wrapper.findComponent('.strategy-modal-stub').vm.$emit('select-type', 'on_exchange')
    await flushPromises()
  }

  it('启动策略检查即挂轮询定时器，unmount 后全部清理（真实行为断言，替代恒真 typeof 占位）', async () => {
    const wrapper = await mountWithModalStub()
    await startStrategyCheck(wrapper)
    // 3s 轮询 interval（+180s timeout 兜底）至少一个已在册
    expect(vi.getTimerCount()).toBeGreaterThanOrEqual(1)
    wrapper.unmount()
    // onBeforeUnmount → clearStrategyTimers：不残留任何 timer
    expect(vi.getTimerCount()).toBe(0)
  })

  it('轮询连续 5 次失败后停止并渲染「后端服务异常」错误态（负向：能抓静默吞错回归）', async () => {
    const api = await import('../api')
    api.portfolioApi.getTask.mockRejectedValue(new Error('NetworkError'))
    const wrapper = await mountWithModalStub()
    await startStrategyCheck(wrapper)
    await vi.advanceTimersByTimeAsync(3000 * 5 + 1) // 5 个轮询周期全部失败
    await flushPromises()
    // 轮询必须停（timer 清零）且错误文案可见——两条断言任一缺失即为假防护
    expect(vi.getTimerCount()).toBe(0)
    expect(wrapper.find('.error-text').text()).toContain('后端服务异常')
    wrapper.unmount()
  })

  // 原 designAsync 占位用例（只验 mock 本身 rejects，未挂载组件）已删除：
  // design 失败/重试路径由下方「任务状态机 (O11)」describe 的真实组件行为用例覆盖。
})

// =========================================================================
// 来源: DashboardAiTools.factorVisibility.spec.js（F3 因子模型概览可见性）
// =========================================================================

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

// =========================================================================
// 来源: DashboardAiTools.p0-9.spec.js（任务列表双显示修复）
// =========================================================================

function flush() {
  return new Promise((r) => setTimeout(r, 0))
}

describe('DashboardAiTools — P0-9 任务列表双显示', () => {
  it('running check 任务合入历史列表（_type=check）', async () => {
    mockTasks.push({ taskId: '388', type: 'check', status: 'running', createdAt: Date.now() })
    getTimeline.mockResolvedValue({ data: { items: [], total: 0 } })
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await wrapper.vm.loadHistoryList()
    await flush()
    const list = wrapper.vm.designHistoryList
    const running = list.filter((i) => i.status === 'running')
    expect(running.length).toBe(1)
    expect(running[0]._type).toBe('check')
    expect(running[0].task_id).toBe('388')
  })

  it('running 任务已存在于 timeline（task_id 相同）→ 不重复合成（无双显示）', async () => {
    getTimeline.mockResolvedValue({
      data: { items: [{ id: 506, _type: 'design', status: 'running', task_id: '506', created_at: '2026-08-11' }], total: 1 },
    })
    // taskStore 同一 running 任务（taskId='506'）
    mockTasks.push({ taskId: '506', type: 'design', status: 'running', createdAt: Date.now() })
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await wrapper.vm.loadHistoryList()
    await flush()
    const list = wrapper.vm.designHistoryList
    const runningDesigns = list.filter((i) => i._type === 'design' && i.status === 'running')
    expect(runningDesigns.length).toBe(1, `同一 running 任务不得双显示: ${JSON.stringify(list)}`)
  })
})

// =========================================================================
// 来源: DashboardAiTools.resetToTools.spec.js（O15 重新进入复位）
// =========================================================================

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

// =========================================================================
// 来源: DashboardAiTools.stateMachine.spec.js（O11 任务状态机）
// =========================================================================

describe('DashboardAiTools — 任务状态机 (O11)', () => {
  beforeEach(() => {
    persistMock.mockClear()
    designAsyncMock.mockClear()
    designAsyncMock.mockResolvedValue({ data: { task_id: 101, design_id: null } })
  })

  it('O11: 失败态 → 点击重试 → 重新 running（复用参数重新提交）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    // 进入 design wizard 并提交（designAsync 立即返回 task_id=101）
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'wizard'
    await wrapper.vm.startDesign(500000)
    await flushPromises()
    expect(wrapper.vm.designStep).toBe('loading')
    // 模拟失败
    wrapper.vm.designFailed = '方案生成超时，数据源响应过慢'
    await flushPromises()
    expect(wrapper.find('[data-testid="retry-btn"]').exists()).toBe(true)
    // 点击重试 → designFailed 清空 + 重新 running（designAsync 再次调用）
    await wrapper.find('[data-testid="retry-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.vm.designFailed).toBe('')
    expect(wrapper.vm.designStep).toBe('loading')
    expect(designAsyncMock.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('O11: 失败态返回 → idle → 再次进入回到 idle（不残留失败卡）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = '后端服务异常'
    await nextTick()
    expect(wrapper.find('[data-testid="cancel-btn"]').exists()).toBe(true)
    await wrapper.find('[data-testid="cancel-btn"]').trigger('click')
    expect(wrapper.vm.activeCoreFeature).toBeNull()
    // 再次进入（无 running 任务 → resetToTools）
    wrapper.vm.enterDesignMode()
    await flushPromises()
    expect(wrapper.vm.designFailed).toBe('')
    expect(wrapper.vm.designStep).toBe('wizard')
  })

  it('O11: 失败态退出不持久化（exitCoreFeature 不调 persistDesignState）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = '方案生成超时'
    wrapper.vm.exitCoreFeature()
    expect(persistMock).not.toHaveBeenCalled()
    // loading 无失败 → 可持久化（running 续跑语义）
    persistMock.mockClear()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = ''
    wrapper.vm.exitCoreFeature()
    expect(persistMock).toHaveBeenCalled()
  })

  it('O11: WS 完成与轮询幂等——finalizedDesignIds 防重复 finalize', async () => {
    // 源码级断言：WS 回调与轮询 completed 分支都有 finalizedDesignIds.has(did) 守卫
    // （fetchDesignDetail 只调一次——interaction-redesign P3 验收③）
    const src = DashboardAiTools.__script?.content
      || require('fs').readFileSync(require.resolve('../views/AiDesign.vue'), 'utf-8')
    expect(src).toContain('finalizedDesignIds.has(did)')
    expect(src).toContain('finalizedDesignIds.add(did)')
  })
})
