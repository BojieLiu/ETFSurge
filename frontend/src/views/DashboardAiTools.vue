<template>
  <section class="card core-actions">
    <div class="card-header">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">⚡</span>
        AI 智能工具
      </h2>
    </div>

    <div class="core-actions-body">
      <!-- Feature Entrances -->
      <div v-if="!activeCoreFeature" class="core-actions-grid">
        <button class="core-action-btn" @click="enterDesignMode" aria-label="智能设计 ETF 组合方案">
          <span class="action-icon" aria-hidden="true">✨</span>
          <div class="action-content">
            <span class="action-title">智能设计ETF组合方案</span>
            <span class="action-desc">输入资金，一键生成进攻/平衡/防御三种风格组合</span>
          </div>
        </button>

        <button class="core-action-btn" @click="enterStrategyMode" :disabled="checkingStrategy">
          <span class="action-icon" aria-hidden="true">🎯</span>
          <div class="action-content">
            <span class="action-title">策略检查分析</span>
            <span class="action-desc">分析当前组合，优化权重与持仓</span>
          </div>
        </button>

        <button class="core-action-btn" @click="enterHistoryMode">
          <span class="action-icon" aria-hidden="true">📖</span>
          <div class="action-content">
            <span class="action-title">任务列表</span>
            <span class="action-desc">查看历史组合设计与策略检查记录</span>
          </div>
        </button>
      </div>

      <!-- Strategy Type Selection Modal -->
      <StrategyCheckModal
        :visible="showStrategyModal"
        @select-type="selectStrategyType"
        @close="showStrategyModal = false"
      />

      <!-- History Panel -->
      <DesignHistory
        v-if="activeCoreFeature === 'history'"
        :items="designHistoryList"
        :loading="historyLoading"
        :loaded="historyLoaded"
        @select="onHistorySelect"
        @close="exitCoreFeature"
      />

      <!-- Design Wizard -->
      <DesignWizard
        v-else-if="activeCoreFeature === 'design' && designStep === 'wizard'"
        :capital="designCapital"
        @start-design="startDesign"
        @cancel="exitCoreFeature"
      />

      <!-- Design Loading -->
      <DesignLoading
        v-else-if="activeCoreFeature === 'design' && designStep === 'loading'"
        :progress="loadingProgress"
        :step-label="loadingText"
        :failed="designFailed"
        @cancel="exitCoreFeature"
      />

      <!-- Design Result -->
      <DesignResult
        v-else-if="activeCoreFeature === 'design' && designStep === 'result' && designResult?.plans?.length"
        :plans="designResult.plans"
        :design-text="designResult.design_text"
        :is-history="designResult.is_history"
        :created-at="designResult.created_at"
        :report-error="reportError"
        :report-stale="designReportStale"
        @apply="applyPlan"
        @regenerate="regenerateDesign"
        @close="exitCoreFeature"
        @retry-report="retryReport"
      />

      <!-- Strategy Check Result -->
      <StrategyCheckResult
        v-if="activeCoreFeature === 'strategy'"
        :result="strategyResult"
        :loading="checkingStrategy"
        :error="strategyError"
        :task-status="strategyTaskStatus"
        :task-progress="strategyProgress"
        :task-stage="strategyStage"
        @close="exitCoreFeature"
      />
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { portfolioApi } from '../api'
import { usePortfolioStore } from '../stores/portfolio'
import { useTaskStore } from '../stores/task'
import { useToastStore } from '../stores/toast'
import { formatDate } from '../utils/formatDate'
import DesignWizard from '../components/design/DesignWizard.vue'
import DesignLoading from '../components/design/DesignLoading.vue'
import DesignResult from '../components/design/DesignResult.vue'
import DesignHistory from '../components/design/DesignHistory.vue'
import StrategyCheckModal from '../components/design/StrategyCheckModal.vue'
import StrategyCheckResult from '../components/design/StrategyCheckResult.vue'

const emit = defineEmits(['applied'])

const store = usePortfolioStore()
const toast = useToastStore()
const taskStore = useTaskStore()

// State
const activeCoreFeature = ref(null)
const designStep = ref('wizard')
const designFailed = ref('')
const designCapital = ref(500000)
const designResult = ref(null)
const designTab = ref('cards')
const expandedPlan = ref(null)
const applyingPlan = ref(null)
const loadingProgress = ref(0)
const loadingText = ref('正在采集数据...')
const checkingStrategy = ref(false)
const strategyResult = ref(null)
const strategyProgress = ref(0)
const strategyStage = ref('')
const strategyError = ref('')
const strategyTaskStatus = ref('')
const strategyPortfolioType = ref('')
const reportError = ref('')
const showStrategyModal = ref(false)

// Timer refs for cleanup (prevent resource leaks on navigation)
let designPollTimer = null
let designTimeoutTimer = null
let strategyPollTimer = null
let strategyTimeoutTimer = null

const designReportStale = computed(() => {
  if (!designResult.value?.created_at) return false
  const created = new Date(designResult.value.created_at).getTime()
  if (!created || isNaN(created)) return false
  return Date.now() - created > 60_000
})

// History
const showHistory = ref(false)
const designHistoryList = ref([])
const historyLoaded = ref(false)
const historyLoading = ref(false)

// Clean up all timers when component is destroyed
onBeforeUnmount(() => {
  if (designPollTimer) { clearInterval(designPollTimer); designPollTimer = null }
  if (designTimeoutTimer) { clearTimeout(designTimeoutTimer); designTimeoutTimer = null }
  clearStrategyTimers()
})

// Restore persisted state
onMounted(() => {
  const saved = taskStore.getDesignState()
  if (saved) {
    const task = taskStore.tasks.find((t) => t.type === 'design' && t.status === 'running')
    if (task) {
      designStep.value = 'loading'
      designCapital.value = saved.designCapital || 500000
      loadingProgress.value = task.progress || saved.loadingProgress || 0
      activeCoreFeature.value = 'design'
    } else if (saved.designStep === 'result' && saved.designResult) {
      designStep.value = 'result'
      designCapital.value = saved.designCapital || 500000
      designResult.value = saved.designResult
      designTab.value = saved.designTab || 'cards'
      expandedPlan.value = saved.expandedPlan || null
      activeCoreFeature.value = 'design'
    }
    taskStore.clearDesignState()
  }
})

// Actions
async function enterDesignMode() {
  // C: Clean up stale running tasks — if the backend restarted, in-memory tasks are dead
  const runningTask = taskStore.tasks.find(t => t.type === 'design' && t.status === 'running')
  if (runningTask) {
    const age = Date.now() - (runningTask.createdAt || 0)
    // If task is > 120s old, check if backend still knows about it
    if (age > 120000) {
      try {
        const taskRes = await portfolioApi.getTask(runningTask.taskId)
        const backendTask = taskRes.data
        if (backendTask.status === 'completed') {
          taskStore.updateTask(runningTask.taskId, { status: 'completed' })
          if (runningTask.designId) {
            activeCoreFeature.value = 'design'
            designStep.value = 'loading'
            await fetchDesignDetail(runningTask.designId)
            return
          }
        } else if (backendTask.status === 'failed') {
          taskStore.updateTask(runningTask.taskId, { status: 'failed' })
          taskStore.removeTask(runningTask.taskId)
          designStep.value = 'wizard'
          activeCoreFeature.value = 'design'
          return
        }
      } catch {
        // Backend doesn't know about this task (404/restart) → clean up
        if (age > 300000) {
          taskStore.removeTask(runningTask.taskId)
        } else {
          taskStore.updateTask(runningTask.taskId, { status: 'failed', errorMessage: '后端已重启，任务丢失' })
        }
        designStep.value = 'wizard'
        activeCoreFeature.value = 'design'
        return
      }
    }
  }
  if (runningTask && runningTask.designId) {
    activeCoreFeature.value = 'design'
    designStep.value = 'loading'
    try {
      const res = await portfolioApi.getDesign(runningTask.designId)
      const data = res.data
      if (data.status === 'completed') {
        taskStore.updateTask(runningTask.taskId, { status: 'completed' })
        designResult.value = data
        designStep.value = 'result'
        return
      }
      if (data.status !== 'running') {
        taskStore.removeTask(runningTask.taskId)
        designStep.value = 'wizard'
        return
      }
      return
    } catch {
      if (Date.now() - (runningTask.createdAt || 0) > 300000) {
        taskStore.removeTask(runningTask.taskId)
        designStep.value = 'wizard'
      }
    }
    return
  }
  activeCoreFeature.value = 'design'
  designStep.value = 'wizard'
  designCapital.value = 500000
}

function enterStrategyMode() {
  strategyResult.value = null
  checkingStrategy.value = false
  strategyTaskStatus.value = ''
  strategyError.value = ''
  strategyPortfolioType.value = ''
  showStrategyModal.value = true
}

function selectStrategyType(type) {
  strategyPortfolioType.value = type
  showStrategyModal.value = false
  activeCoreFeature.value = 'strategy'
  checkStrategy()
}

function enterHistoryMode() {
  activeCoreFeature.value = 'history'
  if (!historyLoaded.value) loadHistoryList()
}

function clearStrategyTimers() {
  if (strategyPollTimer) { clearInterval(strategyPollTimer); strategyPollTimer = null }
  if (strategyTimeoutTimer) { clearTimeout(strategyTimeoutTimer); strategyTimeoutTimer = null }
}

function exitCoreFeature() {
  if (designStep.value === 'loading' || designStep.value === 'result') {
    taskStore.persistDesignState({
      designStep: designStep.value,
      designResult: designResult.value,
      designCapital: designCapital.value,
      loadingProgress: loadingProgress.value,
      designTab: designTab.value,
      expandedPlan: expandedPlan.value,
    })
  }
  clearStrategyTimers()
  activeCoreFeature.value = null
}

async function startDesign(capital) {
  designCapital.value = capital
  designStep.value = 'loading'
  designResult.value = null
  loadingProgress.value = 0
  loadingText.value = '正在提交任务...'

  async function fetchDesignDetail(designId) {
    if (!designId) return
    loadingText.value = '方案已生成，正在加载...'
    loadingProgress.value = 95
    const detailRes = await portfolioApi.getDesign(designId)
    const data = detailRes.data
    const plans = Array.isArray(data.strategies)
      ? data.strategies.map(s => ({
          style: s.label,
          style_label: s.label,
          portfolio_name: s.portfolio_name,
          positioning: s.positioning,
          expected_return: s.expected_return,
          max_drawdown: s.max_drawdown,
          sharpe_ratio: s.sharpe_ratio,
          risk_factors: [],
          rebalance_rules: '月度检视',
          allocations: Array.isArray(s.etfs)
            ? s.etfs.map(e => ({
                symbol: e.symbol,
                name: e.name,
                layer: e.layer,
                target_weight: e.weight,
                selection_rationale: e.selection_rationale || '',
              }))
            : [],
        }))
      : []

    designResult.value = {
      plans,
      design_text: data.design_text || '',
      market_context: data.market_context || {},
      created_at: data.created_at,
    }
    designStep.value = 'result'
    loadingProgress.value = 100
    loadingText.value = '完成！'
    return data
  }

  try {
    loadingProgress.value = 10
    loadingText.value = '正在请求 AI 设计方案...'
    const res = await portfolioApi.designAsync({ capital: capital })
    const taskData = res.data
    taskStore.addTask(taskData.task_id, '智能组合设计', 'design')
    const storedTask = taskStore.getTask(taskData.task_id)
    if (storedTask) storedTask.designId = taskData.design_id

    loadingProgress.value = 30
    loadingText.value = 'AI 正在分析全市场数据...'

    // Register WS listener for completion
    const wsToken = taskStore.registerTaskCompletion(taskData.task_id, async () => {
      loadingText.value = '方案已生成，正在加载...'
      loadingProgress.value = 95
      let did = taskStore.getTask(taskData.task_id)?.designId
      if (!did) {
        try {
          const taskRes = await portfolioApi.getTask(taskData.task_id)
          did = taskRes?.data?.result?.design_id
        } catch {}
      }
      if (did) {
        try {
          await fetchDesignDetail(did)
          toast('组合方案生成完成！', 'success')
        } catch {
          toast('加载设计方案详情失败', 'error')
          designFailed.value = '加载方案详情失败，请稍后再试'
        }
      }
    })

    // Poll as fallback
    let pollCount = 0
    let consecutiveErrors = 0
    if (designPollTimer) clearInterval(designPollTimer)
    designPollTimer = setInterval(async () => {
      pollCount++
      loadingProgress.value = Math.min(30 + pollCount * 5, 90)
      loadingText.value = `AI 正在优化组合... (${pollCount * 5}s)`
      try {
        const taskRes = await portfolioApi.getTask(taskData.task_id)
        const task = taskRes.data
        consecutiveErrors = 0  // Reset on success
        if (task.status === 'completed') {
          clearInterval(designPollTimer); designPollTimer = null
          const did = task?.result?.design_id || taskData.design_id
          if (did) {
            await fetchDesignDetail(did)
            toast('组合方案生成完成！', 'success')
          }
        } else if (task.status === 'failed') {
          clearInterval(designPollTimer); designPollTimer = null
          designFailed.value = task.error_message || task.error || '方案生成失败，请稍后重试'
        }
      } catch {
        // Detect backend restart: consecutive errors mean the task is gone
        consecutiveErrors++
        if (consecutiveErrors >= 5) {
          clearInterval(designPollTimer); designPollTimer = null
          designFailed.value = '后端服务异常，任务可能已丢失'
        }
      }
    }, 5000)

    // Cleanup poll on 180s timeout
    if (designTimeoutTimer) clearTimeout(designTimeoutTimer)
    designTimeoutTimer = setTimeout(() => {
      if (designPollTimer) { clearInterval(designPollTimer); designPollTimer = null }
      if (designStep.value === 'loading' && !designFailed.value) {
        loadingText.value = '方案生成中，您可稍后查看任务列表'
        setTimeout(() => {
          if (designStep.value === 'loading') {
            exitCoreFeature()
          }
        }, 3000)
      }
    }, 180000)
  } catch (e) {
    designFailed.value = '提交失败：' + (e?.message || '网络错误')
  }
}

async function checkStrategy() {
  // Clean up any previous strategy timers before starting new one
  clearStrategyTimers()

  checkingStrategy.value = true
  strategyTaskStatus.value = 'running'
  strategyError.value = ''
  strategyResult.value = null
  try {
    const res = await portfolioApi.strategyCheck({ portfolio_type: strategyPortfolioType.value || undefined })
    const taskData = res.data
    taskStore.addTask(taskData.task_id, '策略检查与分析', 'check')

    // Poll for completion
    let pollCount = 0
    let consecutiveErrors = 0
    strategyPollTimer = setInterval(async () => {
      pollCount++
      try {
        const taskRes = await portfolioApi.getTask(taskData.task_id)
        const task = taskRes.data
        consecutiveErrors = 0  // Reset on success
        // 从后端读取真实进度和阶段
        strategyProgress.value = task.progress || Math.min(pollCount * 10, 80)
        strategyStage.value = task.stage || ''
        if (task.status === 'completed') {
          clearStrategyTimers()
          const detailRes = await portfolioApi.getStrategyCheckResult(taskData.task_id)
          strategyResult.value = detailRes.data
          strategyTaskStatus.value = 'completed'
          strategyProgress.value = 100
          strategyStage.value = '分析完成'
          checkingStrategy.value = false
          toast('策略检查完成', 'success')
        } else if (task.status === 'failed') {
          clearStrategyTimers()
          strategyError.value = task.error_message || task.error || '策略检查失败'
          strategyTaskStatus.value = 'failed'
          checkingStrategy.value = false
        }
      } catch {
        // Detect backend restart: consecutive errors mean the task is gone
        consecutiveErrors++
        if (consecutiveErrors >= 5) {
          clearStrategyTimers()
          strategyError.value = '后端服务异常，任务可能已丢失'
          strategyTaskStatus.value = 'failed'
          checkingStrategy.value = false
        }
      }
    }, 3000)

    strategyTimeoutTimer = setTimeout(() => {
      clearStrategyTimers()
      if (checkingStrategy.value) {
        strategyError.value = '策略检查超时，请稍后查看历史记录'
        strategyTaskStatus.value = 'failed'
        checkingStrategy.value = false
      }
    }, 120000)
  } catch (e) {
    strategyError.value = '提交失败：' + (e?.message || '网络错误')
    strategyTaskStatus.value = 'failed'
    checkingStrategy.value = false
  }
}

async function loadHistoryList() {
  historyLoading.value = true
  try {
    const [designRes, checkRes] = await Promise.all([
      portfolioApi.listDesigns(20, 0, 8000).catch(() => ({ data: [] })),
      portfolioApi.listStrategyChecks(20, 0, 8000).catch(() => ({ data: [] })),
    ])
    const designs = (designRes.data || []).map(d => ({ ...d, _type: 'design' }))
    const checks = (checkRes.data || []).map(c => ({ ...c, _type: 'check' }))

    // 合并运行中的设计任务（追加到列表前）
    const runningTasks = taskStore.tasks
        .filter(t => t.type === 'design' && t.status === 'running')
        .map(t => ({
            id: null, _type: 'design', status: 'running',
            created_at: t.createdAt || new Date().toISOString(),
            capital: '-',
        }))

    designHistoryList.value = [...runningTasks, ...designs, ...checks].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    historyLoaded.value = true
  } catch (e) {
    toast('加载历史记录失败，请检查后端连接', 'error')
  } finally {
    historyLoading.value = false
  }
}

async function onHistorySelect(id, item) {
  // 运行中：不请求后端
  if (item?.status === 'running') {
    toast('该方案仍在生成中，请稍后再试', 'info')
    return
  }
  // 失败：提示错误
  if (item?.status === 'failed') {
    toast('该方案生成失败，无法查看详情', 'warning')
    return
  }
  // check 类型：加载策略检查详情并显示
  if (item?._type === 'check') {
    try {
      const res = await portfolioApi.getStrategyCheckDetail(id)
      const data = res.data
      if (!data) {
        toast('策略检查记录不存在', 'warning')
        return
      }
      strategyResult.value = data
      strategyTaskStatus.value = 'completed'
      strategyProgress.value = 100
      strategyStage.value = '分析完成'
      activeCoreFeature.value = 'strategy'
      return
    } catch (e) {
      toast('加载策略检查详情失败: ' + (e?.message || '网络错误'), 'error')
      return
    }
  }
  try {
    const res = await portfolioApi.getDesign(id)
    const data = res.data
    if (!data || !data.strategies || data.strategies.length === 0) {
      toast('该历史方案数据不完整', 'warning')
      return
    }
    const plans = data.strategies.map(s => ({
      style: s.label,
      style_label: s.label,
      portfolio_name: s.portfolio_name,
      positioning: s.positioning,
      expected_return: s.expected_return,
      max_drawdown: s.max_drawdown,
      sharpe_ratio: s.sharpe_ratio,
      risk_factors: s.risk_factors || [],
      allocations: Array.isArray(s.etfs)
        ? s.etfs.map(e => ({ symbol: e.symbol, name: e.name, layer: e.layer, target_weight: e.weight, selection_rationale: e.selection_rationale || '' }))
        : [],
    }))
    designResult.value = { plans, design_text: data.design_text || '', market_context: data.market_context || {}, created_at: data.created_at, is_history: true }
    designStep.value = 'result'
    designTab.value = 'cards'
    activeCoreFeature.value = 'design'
  } catch (e) {
    toast('加载方案详情失败', 'error')
  }
}

function regenerateDesign() {
  designResult.value = null
  startDesign(designCapital.value)
}

function retryReport() {
  reportError.value = ''
  if (designResult.value) {
    designResult.value = { ...designResult.value, design_text: '' }
  }
}

async function applyPlan(plan) {
  if (applyingPlan.value) return
  applyingPlan.value = plan.style
  try {
    await portfolioApi.applyPortfolioDesign(plan)
    toast(`已应用 ${plan.style} 方案`, 'success')
    emit('applied')
  } catch (e) {
    toast('应用方案失败', 'error')
  } finally {
    applyingPlan.value = null
  }
}
</script>

<style scoped>
.core-actions { overflow: visible; }
.core-actions-body { padding: var(--space-5); }
.core-actions-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4); }
.core-action-btn { display: flex; align-items: flex-start; gap: var(--space-4); padding: var(--space-5); border: 2px solid var(--color-border-light); border-radius: var(--radius-xl); background: var(--color-surface-primary); cursor: pointer; transition: var(--transition-fast); text-align: left; }
.core-action-btn:hover { border-color: var(--color-brand-300); box-shadow: var(--shadow-md); transform: translateY(-2px); }
.core-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-icon { font-size: var(--font-size-3xl); line-height: 1; flex-shrink: 0; }
.action-content { display: flex; flex-direction: column; gap: var(--space-1); }
.action-title { font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.action-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); line-height: var(--line-height-normal); }
</style>
