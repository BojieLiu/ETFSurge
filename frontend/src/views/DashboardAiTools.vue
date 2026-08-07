<template>
  <div class="ai-tools-page">
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
        :key="historyKey"
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
        :task-stage="designTaskStage"
        :selected-label="designSelectedLabel"
        :elapsed-sec="designElapsedSec"
        @cancel="exitCoreFeature"
        @retry="retryDesign"
      />

      <!-- Design Result -->
      <DesignResult
        v-else-if="activeCoreFeature === 'design' && designStep === 'result' && designResult?.plans?.length"
        :plans="designResult.plans"
        :design-text="designResult.design_text"
        :is-history="designResult.is_history"
        :created-at="designResult.created_at"
        :report-quality="designResult.report_quality || 'none'"
        :report-error="reportError"
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

      <!-- Error Detail Modal (standalone, not in the v-if chain) -->
      <AppModal v-model="showErrorModal" title="❌ 设计任务失败" :closable="true" size="sm">
        <div class="error-detail-content">{{ errorDetail }}</div>
        <template #footer>
          <button class="app-btn app-btn--primary" @click="showErrorModal = false">关闭</button>
        </template>
      </AppModal>
    </div>
  </section>

  <!-- F3 (round6 §13.3): 仅工具列表/初始态显示因子模型概览；具体工具打开后隐藏 -->
  <FactorModelView v-if="!activeCoreFeature" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
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
import AppModal from '../components/ui/AppModal.vue'
import FactorModelView from '../components/FactorModelView.vue'

const props = defineProps({
  // O15 (round7 §7 P17): 父级（PortfolioAnalysis）告知本组件是否处于激活 tab——
  // 重新进入「AI工具」时复位到工具列表（activeCoreFeature=null），
  // 消除 AppTabs :hidden 常驻导致的状态残留（历史方案/上次界面）。
  active: { type: Boolean, default: false },
})
const emit = defineEmits(['applied'])

// O15: DesignHistory 强制重挂载 key（复位其内部 statusFilter='all'）
const historyKey = ref(0)

function resetToTools() {
  // O15: 重新进入 AI 工具 → 默认展示工具列表（智能设计/策略检查/任务列表三入口）
  activeCoreFeature.value = null
  designStep.value = 'wizard'
  designTab.value = 'cards'
  expandedPlan.value = null
  showHistory.value = false
  historyKey.value += 1
  // O11 (round8 §7 + interaction-redesign): 复位失败态——失败不入 localStorage、
  // 再次进入回到 idle（不残留失败卡）。
  designFailed.value = ''
}

watch(
  () => props.active,
  (now, prev) => {
    if (now && !prev) {
      // 运行中 design 任务例外：有 running 任务保留现有恢复 loading 逻辑（任务不丢）
      const runningTask = taskStore.tasks.find((t) => t.type === 'design' && t.status === 'running')
      if (runningTask) return
      resetToTools()
    }
  },
)

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
// F20 (round6 §16.8): design 任务 stage / 已选标的 / 等待秒数（DesignLoading 展示）
const designTaskStage = ref('')
const designSelectedLabel = ref('')
const designElapsedSec = ref(0)
const checkingStrategy = ref(false)
const strategyResult = ref(null)
const strategyProgress = ref(0)
const strategyStage = ref('')
const strategyError = ref('')
const strategyTaskStatus = ref('')
const strategyPortfolioType = ref('')
const reportError = ref('')
const showErrorModal = ref(false)
const errorDetail = ref('')
const showStrategyModal = ref(false)

// Timer refs for cleanup (prevent resource leaks on navigation)
let designPollTimer = null
let designTimeoutTimer = null
let strategyPollTimer = null
let strategyTimeoutTimer = null

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
  // O11 (round8 §7 + interaction-redesign §2 不变量2): 失败是终态、不入 localStorage——
  // 进入设计工具时复位失败态（同 tab 失败后再次进入回到 idle，不残留失败卡）。
  designFailed.value = ''
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
  // O11 (round8 §7 + interaction-redesign D3/P4): 只持久化可恢复的终态——
  // running（续 loading）与 result；failed 是终态、不持久化（刷新后回到 idle，
  // 不再出现「失败卡刷新后变加载中」的假象）。
  const isFailed = !!designFailed.value
  if (!isFailed && (designStep.value === 'loading' || designStep.value === 'result')) {
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

// O11 (round8 §7 + interaction-redesign D1): 失败卡「重试一次」——复用参数重提交。
// 失败是终态，点击后重新走 running（新 taskId），可停留查看原因也可直接重试。
async function retryDesign() {
  const capital = designCapital.value || 500000
  designFailed.value = ''
  await startDesign(capital)
}

// O11 (round8 §7 + interaction-redesign P3): WS 完成回调与轮询收敛到单一
// 「derive 完成」——finalizedDesignIds 防重复 finalize（fetchDesignDetail 只调一次）。
const finalizedDesignIds = new Set()

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
    const plans = data.plans || []

    designResult.value = {
      plans,
      design_text: data.design_text || '',
      market_context: data.market_context || {},
      created_at: data.created_at,
      report_quality: data.report_quality || 'none',
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
    // F20: 已选标的/维度高亮（发起时记录资本规模）
    designSelectedLabel.value = `${(capital / 10000).toFixed(0)} 万元`
    designTaskStage.value = ''
    designElapsedSec.value = 0
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
        // O11: 幂等——WS 完成与轮询同时到达时只 finalize 一次
        if (finalizedDesignIds.has(did)) return
        finalizedDesignIds.add(did)
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
      // F20: 已等待秒数 → 超时预估文案
      designElapsedSec.value = pollCount * 5
      try {
        const taskRes = await portfolioApi.getTask(taskData.task_id)
        const task = taskRes.data
        consecutiveErrors = 0  // Reset on success
        // F20: 对齐任务 stage（数据采集→策略计算→LLM 报告→完成）
        if (task?.stage) designTaskStage.value = task.stage
        if (task.status === 'completed') {
          clearInterval(designPollTimer); designPollTimer = null
          const did = task?.result?.design_id || taskData.design_id
          if (did) {
            // O11: 幂等——WS 已 finalize 则轮询跳过（fetchDesignDetail 只调一次）
            if (finalizedDesignIds.has(did)) return
            finalizedDesignIds.add(did)
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
    // O11 (interaction-redesign §5): 180s 推不到 result 转 failed(canRetry)，
    // 不再「把用户踢回列表」（移除 180s 后 exitCoreFeature 行为）。
    if (designTimeoutTimer) clearTimeout(designTimeoutTimer)
    designTimeoutTimer = setTimeout(() => {
      if (designPollTimer) { clearInterval(designPollTimer); designPollTimer = null }
      if (designStep.value === 'loading' && !designFailed.value) {
        designFailed.value = '方案生成时间过长，请重试一次或稍后查看任务列表'
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

    // factor-and-strategy-check-review 问题2 R1/R3: 注册 WS 完成回调（与 design 流程对称）。
    // 旧实现只轮询——WS completed 先到只触发全局 toast，组件 checkingStrategy 仍 true，
    // 停留在 loading 直到 3s 后轮询 → 用户看到「先提示已完成再停留加载」。
    taskStore.registerTaskCompletion(taskData.task_id, async () => {
      try {
        const detailRes = await portfolioApi.getStrategyCheckResult(taskData.task_id)
        strategyResult.value = detailRes.data
        strategyTaskStatus.value = 'completed'
        strategyProgress.value = 100
        strategyStage.value = '分析完成'
        checkingStrategy.value = false
        toast('策略检查完成', 'success')
      } catch {
        strategyError.value = '加载策略检查结果失败'
        strategyTaskStatus.value = 'failed'
        checkingStrategy.value = false
      }
      clearStrategyTimers()
    })

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
    const res = await portfolioApi.getTimeline(20, 0)
    const data = res.data || {}
    // Z27: /portfolio/timeline 已合并 design+check，直接使用 items（移除未定义的 checks 引用）
    const items = (data.items || [])

    // 合并运行中的设计任务（追加到列表前）
    const runningTasks = taskStore.tasks
        .filter(t => t.type === 'design' && t.status === 'running')
        .map(t => ({
            id: null, _type: 'design', status: 'running',
            created_at: t.createdAt || new Date().toISOString(),
            capital: '-',
        }))

    designHistoryList.value = [...runningTasks, ...items].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
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
  // 失败：展示错误详情弹窗
  if (item?.status === 'failed') {
    showErrorModal.value = true
    if (item.error_message) {
      errorDetail.value = item.error_message
    } else {
      // 列表无 error_message 时尝试从详情接口获取
      try {
        const res = await portfolioApi.getDesign(id)
        errorDetail.value = res.data?.error_message || '未知错误'
      } catch {
        errorDetail.value = '未知错误'
      }
    }
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
    const plans = data.plans || []
    designResult.value = { plans, design_text: data.design_text || '', market_context: data.market_context || {}, created_at: data.created_at, is_history: true, report_quality: data.report_quality || 'none' }
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

/* Page layout */
.ai-tools-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
</style>
