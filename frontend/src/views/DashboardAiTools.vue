<template>
  <section class="ai-tools">
    <PageHeader
      title="AI 智能工具"
      description="智能组合设计、策略检查与历史记录"
    >
      <template #action>
        <div v-if="!activeCoreFeature" class="feature-grid">
          <AppCard
            variant="outlined"
            hoverable
            clickable
            @click="enterDesignMode"
            class="feature-card"
          >
            <template #header-icon>
              <span aria-hidden="true">✨</span>
            </template>
            <template #header-title>智能设计 ETF 组合方案</template>
            <template #header-description>输入资金，一键生成进攻/平衡/防御三种风格组合</template>
          </AppCard>

          <AppCard
            variant="outlined"
            hoverable
            clickable
            @click="enterStrategyMode"
            :disabled="checkingStrategy"
            class="feature-card"
          >
            <template #header-icon>
              <span aria-hidden="true">🎯</span>
            </template>
            <template #header-title>策略检查分析</template>
            <template #header-description>分析当前组合，优化权重与持仓</template>
          </AppCard>

          <AppCard
            variant="outlined"
            hoverable
            clickable
            @click="enterHistoryMode"
            class="feature-card"
          >
            <template #header-icon>
              <span aria-hidden="true">📖</span>
            </template>
            <template #header-title>历史记录</template>
            <template #header-description>查看之前生成的组合设计方案</template>
          </AppCard>
        </div>
      </template>
    </PageHeader>

    <!-- Strategy Type Selection Modal -->
    <StrategyCheckModal
      :visible="showStrategyModal"
      @select-type="selectStrategyType"
      @close="showStrategyModal = false"
    />

    <!-- Content Panels -->
    <div v-if="activeCoreFeature" class="ai-tools__content">
      <!-- History Panel -->
      <AppCard v-if="activeCoreFeature === 'history'" variant="default" :padding="false">
        <template #header>
          <h2 class="card__title"><span aria-hidden="true">📖</span> 历史记录</h2>
          <AppButton variant="ghost" size="sm" @click="exitCoreFeature">关闭</AppButton>
        </template>
        <DesignHistory
          :items="designHistoryList"
          :loading="historyLoading"
          :loaded="historyLoaded"
          @select="onHistorySelect"
          @close="exitCoreFeature"
        />
      </AppCard>

      <!-- Design Wizard -->
      <AppCard v-else-if="activeCoreFeature === 'design' && designStep === 'wizard'" variant="default" :padding="false">
        <DesignWizard
          :capital="designCapital"
          @start-design="startDesign"
          @cancel="exitCoreFeature"
        />
      </AppCard>

      <!-- Design Loading -->
      <AppCard v-else-if="activeCoreFeature === 'design' && designStep === 'loading'" variant="default" :padding="false">
        <DesignLoading
          :progress="loadingProgress"
          :step-label="loadingText"
          :failed="designFailed"
          @cancel="exitCoreFeature"
        />
      </AppCard>

      <!-- Design Result -->
      <AppCard v-else-if="activeCoreFeature === 'design' && designStep === 'result' && designResult?.plans?.length" variant="default" :padding="false">
        <DesignResult
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
      </AppCard>

      <!-- Strategy Check Result -->
      <AppCard v-else-if="activeCoreFeature === 'strategy'" variant="default" :padding="false">
        <StrategyCheckResult
          :result="strategyResult"
          :loading="checkingStrategy"
          :error="strategyError"
          @close="exitCoreFeature"
        />
      </AppCard>

      <!-- Empty State -->
      <AppCard v-else variant="filled" class="empty-state">
        <div class="empty-state__content">
          <div class="empty-state__icon" aria-hidden="true">⚡</div>
          <h3 class="empty-state__title">暂无内容</h3>
          <p class="empty-state__desc">请从上方选择一项功能开始</p>
        </div>
      </AppCard>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { portfolioApi } from '@/api'
import { usePortfolioStore } from '@/stores/portfolio'
import { useTaskStore } from '@/stores/task'
import { useToastStore } from '@/stores/toast'
import { formatDate } from '@/utils/formatDate'
import DesignWizard from '@/components/design/DesignWizard.vue'
import DesignLoading from '@/components/design/DesignLoading.vue'
import DesignResult from '@/components/design/DesignResult.vue'
import DesignHistory from '@/components/design/DesignHistory.vue'
import StrategyCheckModal from '@/components/design/StrategyCheckModal.vue'
import StrategyCheckResult from '@/components/design/StrategyCheckResult.vue'
import { PageHeader, AppCard, AppButton } from '@/components'

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

// History
const showHistory = ref(false)
const designHistoryList = ref([])
const historyLoaded = ref(false)
const historyLoading = ref(false)

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
  const runningTask = taskStore.tasks.find(t => t.status === 'running')
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
    loadingText.value = '完成'
  }

  try {
    const res = await portfolioApi.designAsync({ capital, portfolio_type: 'on_exchange' })
    const taskId = res.data.task_id
    if (!taskId) throw new Error('未返回 task_id')

    taskStore.addTask({ taskId, type: 'design', status: 'running', progress: 0 })

    const poll = async () => {
      let attempts = 0
      while (attempts < 180) {
        await new Promise(r => setTimeout(r, 5000))
        attempts++
        try {
          const task = taskStore.tasks.find(t => t.taskId === taskId)
          if (!task || task.status !== 'running') break

          const statusRes = await portfolioApi.getTask(taskId)
          const status = statusRes.data.status
          const progress = Math.min(attempts * 0.5, 90)
          loadingProgress.value = progress
          taskStore.updateTask(taskId, { progress })

          if (status === 'completed') {
            loadingProgress.value = 100
            loadingText.value = '生成完成，正在获取详情...'
            taskStore.updateTask(taskId, { status: 'completed' })
            await fetchDesignDetail(statusRes.data.design_id)
            break
          } else if (status === 'failed') {
            designFailed.value = statusRes.data.error || '生成失败，请重试'
            designStep.value = 'wizard'
            taskStore.removeTask(taskId)
            break
          }
        } catch (e) {
          console.warn('[DashboardAiTools] poll error', e)
        }
      }
      if (attempts >= 180) {
        designFailed.value = '生成超时，请重试'
        designStep.value = 'wizard'
        taskStore.removeTask(taskId)
      }
    }

    poll()
  } catch (e) {
    console.error('[DashboardAiTools] startDesign error', e)
    designFailed.value = e.message || '启动失败，请重试'
    designStep.value = 'wizard'
  }
}

async function checkStrategy() {
  checkingStrategy.value = true
  strategyError.value = ''
  strategyStage.value = '提交任务...'
  strategyProgress.value = 0
  try {
    const res = await portfolioApi.strategyCheck({ portfolio_type: strategyPortfolioType.value })
    const taskId = res.data.task_id
    if (!taskId) throw new Error('未返回 task_id')

    taskStore.addTask({ taskId, type: 'check', status: 'running', progress: 0 })

    const poll = async () => {
      let attempts = 0
      while (attempts < 180) {
        await new Promise(r => setTimeout(r, 5000))
        attempts++
        try {
          const task = taskStore.tasks.find(t => t.taskId === taskId)
          if (!task || task.status !== 'running') break

          const statusRes = await portfolioApi.getTask(taskId)
          const status = statusRes.data.status
          const progress = Math.min(attempts * 0.5, 90)
          strategyProgress.value = progress
          strategyStage.value = statusRes.data.stage || '处理中...'
          taskStore.updateTask(taskId, { progress })

          if (status === 'completed') {
            strategyProgress.value = 100
            strategyStage.value = '完成'
            taskStore.updateTask(taskId, { status: 'completed' })
            strategyResult.value = statusRes.data
            break
          } else if (status === 'failed') {
            strategyError.value = statusRes.data.error || '检查失败，请重试'
            taskStore.removeTask(taskId)
            break
          }
        } catch (e) {
          console.warn('[DashboardAiTools] checkStrategy poll error', e)
        }
      }
      if (attempts >= 180) {
        strategyError.value = '检查超时，请重试'
        taskStore.removeTask(taskId)
      }
    }

    poll()
  } catch (e) {
    console.error('[DashboardAiTools] checkStrategy error', e)
    strategyError.value = e.message || '启动失败，请重试'
    checkingStrategy.value = false
  }
}

async function loadHistoryList() {
  if (historyLoaded.value) return
  historyLoading.value = true
  try {
    const res = await portfolioApi.listDesigns()
    designHistoryList.value = res.data || []
    historyLoaded.value = true
  } catch (e) {
    console.error('[DashboardAiTools] loadHistoryList error', e)
  } finally {
    historyLoading.value = false
  }
}

function onHistorySelect(item) {
  designResult.value = {
    plans: item.strategies || [],
    design_text: item.design_text || '',
    market_context: item.market_context || {},
    created_at: item.created_at,
    is_history: true,
  }
  designStep.value = 'result'
  designCapital.value = item.capital || 500000
  activeCoreFeature.value = 'design'
}

async function applyPlan(plan) {
  applyingPlan.value = plan.style
  try {
    await portfolioApi.applyPortfolioDesign({ design_id: plan.design_id || designResult.value.id, plan: plan })
    toast.show({ type: 'success', message: '方案已应用到组合' })
    emit('applied')
  } catch (e) {
    console.error('[DashboardAiTools] applyPlan error', e)
    toast.show({ type: 'error', message: '应用失败，请重试' })
  } finally {
    applyingPlan.value = null
  }
}

function regenerateDesign() {
  designResult.value = null
  designStep.value = 'wizard'
}

async function retryReport() {
  if (!designResult.value?.plans?.length) return
  reportError.value = ''
  try {
    const res = await portfolioApi.generateDesignReport({
      strategies: designResult.value.plans,
      market_context: designResult.value.market_context,
    })
    designResult.value.design_text = res.data.design_text
  } catch (e) {
    console.error('[DashboardAiTools] retryReport error', e)
    reportError.value = '报告生成失败，请重试'
  }
}
</script>

<style scoped>
.ai-tools {
  display: flex;
  flex-direction: column;
  gap: var(--space-section-md);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-gap-md);
}

.feature-card {
  height: 100%;
  min-height: 160px;
}

.feature-card .card__header {
  text-align: center;
}

.feature-card .card__header-content {
  justify-content: center;
}

.feature-card .card__icon {
  font-size: 32px;
  margin-bottom: var(--space-3);
}

.ai-tools__content {
  width: 100%;
  animation: ai-tools-content-in var(--duration-normal) var(--ease-out);
}

@keyframes ai-tools-content-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  text-align: center;
}

.empty-state__content {
  max-width: 320px;
}

.empty-state__icon {
  font-size: 48px;
  opacity: 0.4;
  margin-bottom: var(--space-4);
}

.empty-state__title {
  margin: 0 0 var(--space-2);
  font: var(--text-h3);
  color: var(--color-text-primary);
}

.empty-state__desc {
  margin: 0;
  font: var(--text-body);
  color: var(--color-text-secondary);
}

@media (max-width: 1023px) {
  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>