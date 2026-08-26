<template>
  <div class="dashboard">
    <ErrorOverlay :hasError="renderError" @retry="onRetry" />

    <template v-if="!renderError">
      <GlobalIndicesStrip :globalIndices="globalIndices" :loading="!fetchAttempted" />

      <!-- P0-4: warmup 占位槽——banner 消失时保留高度，避免下方内容上移（CLS） -->
      <div class="warmup-slot">
        <div v-if="isWarmingUp" class="warmup-banner">
          <div class="warmup-spinner" aria-hidden="true"></div>
          <div class="warmup-text">
            <p class="warmup-title">{{ phaseTitle }}</p>
            <p class="warmup-desc">{{ phaseDesc }}</p>
          </div>
        </div>
      </div>

      <!-- round34-B7 批复①：一行式组合摘要条（总资产/当日盈亏聚合，点击跳组合页）。
           持仓分配/盈亏明细/累计盈亏已迁至组合页「盈亏」tab。 -->
      <PortfolioSummaryStrip
        :totalAll="totalAll"
        :pnlOn="pnlOn"
        :pnlOff="pnlOff"
        :pnlTotal="pnlTotal"
        :weightedChange="pnlWeightedChange"
        :attempted="fetchAttempted"
        :error="pnlError"
        :lastUpdated="lastUpdated"
        @retry="onStripRetry"
      />

      <p v-if="!fetchAttempted" class="loading-hint" aria-busy="true">正在加载组合数据…</p>
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'
import { useMarketStore } from '../stores/market'
import { usePortfolioStore } from '../stores/portfolio'
import { storeToRefs } from 'pinia'
import logger from '../utils/logger'
import { useDashboardData } from '../composables/useDashboardData'
import { useWarmupStatus } from '../composables/useWarmupStatus'
import GlobalIndicesStrip from '../components/GlobalIndicesStrip.vue'
import PortfolioSummaryStrip from '../components/dashboard/PortfolioSummaryStrip.vue'
import ErrorOverlay from '../components/dashboard/ErrorOverlay.vue'

// UI state
const renderError = ref(false)

// Shared capital from store (set in Portfolio Analysis page)
const { capitalOn, capitalOff } = storeToRefs(usePortfolioStore())

const route = useRoute()

// 摘要条恒展示综合聚合（B7 批复①）——scope 固定 combined
const scope = ref('combined')

// Composable – all data logic
const {
  globalIndices,
  fetchAttempted, pnlError,
  totalAll, pnlOn, pnlOff, pnlTotal, pnlWeightedChange,
  fetchGlobalIndices, refreshAll
} = useDashboardData(capitalOn, capitalOff, scope)

const {
  isWarmingUp, phaseTitle, phaseDesc, startPolling, stopPolling,
} = useWarmupStatus()

const marketTimer = ref(null)
const marketStore = useMarketStore()

// round19 P6-①: WS 行情消息消费——更新 globalIndices 内对应指数的实时价
// （连接生命周期在 App.vue 全站常驻，本页面仅注册/注销消费回调）
function updateGlobalIndicesFromWS(data) {
  if (!data || !data.symbol) return
  const indices = globalIndices.value
  for (const region of Object.keys(indices)) {
    const list = indices[region]
    const i = list.findIndex(m => m.symbol === data.symbol)
    if (i >= 0) {
      list[i] = { ...list[i], price: data.price, change_pct: data.change_pct, available: true }
    }
  }
}

// 数据刷新指示器：refreshAll 完成后记录时间戳（摘要条右侧展示）
const lastUpdated = ref(null)
function markUpdated() {
  lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

onErrorCaptured((err) => {
  logger.error('[Dashboard] Uncaught error:', err)
  renderError.value = true
  return false
})

onMounted(async () => {
  // Start warmup polling (stops automatically when all_done or times out)
  startPolling()
  // R52: 初始加载必须走 refreshAll（统一 fetchAttempted 置位）
  await refreshAll()
  markUpdated()
  // round19 P6-①: 连接职责移交 App.vue（全站常驻）——此处只注册指数更新消费回调
  marketStore.onWSMessage(updateGlobalIndicesFromWS)
  marketTimer.value = setInterval(fetchGlobalIndices, 30000)
})

onUnmounted(() => {
  marketStore.offWSMessage(updateGlobalIndicesFromWS)
  if (marketTimer.value) clearInterval(marketTimer.value)
})

watch(() => route.path, () => {
  refreshAll().then(markUpdated)
})

function onRetry() {
  renderError.value = false
  refreshAll().then(markUpdated)
}

// 摘要条错误态重试：仅补拉盈亏（不重复拉指数/分配）
function onStripRetry() {
  refreshAll().then(markUpdated)
}
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.loading-hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
/* P0-4: warmup 占位槽固定高度——banner 隐藏/显示不产生布局偏移 */
.warmup-slot {
  min-height: 0;
}
.warmup-slot:has(.warmup-banner) {
  min-height: 64px;
}
.warmup-banner {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-info-subtle);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
}
.warmup-spinner {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-brand-600);
  border-radius: 50%;
  animation: warmup-spin 0.8s linear infinite;
}
@keyframes warmup-spin {
  to { transform: rotate(360deg); }
}
.warmup-text { flex: 1; min-width: 0; }
.warmup-title { margin: 0; font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-brand-700); }
.warmup-desc { margin: var(--space-1) 0 0; font-size: var(--font-size-xs); color: var(--color-text-tertiary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
