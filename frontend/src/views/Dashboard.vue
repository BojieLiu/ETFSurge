<template>
  <div class="dashboard">
    <ErrorOverlay :hasError="renderError" @retry="onRetry" />

    <template v-if="!renderError">
      <GlobalIndicesStrip :globalIndices="globalIndices" :loading="!fetchAttempted" />

      <SummaryCards
        :activeTab="activeTab"
        :totalAll="totalAll"
        :pnlOn="pnlOn"
        :pnlOff="pnlOff"
        :pnlTotal="pnlTotal"
        :pnlHistory="pnlHistory"
        :pnlHistoryLoading="pnlHistoryLoading"
        :loading="loading"
      />

      <!-- Portfolio Type Tabs -->
      <AppTabs :tabs="tabs" v-model="activeTab" variant="soft" full-width ariaLabel="组合类型" class="dashboard-tabs">
        <template #combined>
          <div v-if="loading" class="content-grid" aria-busy="true">
            <div class="card skeleton-card"><Skeleton type="chart" height="260" /></div>
            <div class="card skeleton-card"><Skeleton type="table" rows="6" /></div>
          </div>
          <template v-else>
            <div v-if="allocationOn?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOn.allocations" title="场内分配" />
              <AllocationTable :items="allocationOn.allocations" :cashPct="cashPctOn" :cashAmount="cashOn" title="场内 ETF 目标分配" />
            </div>
            <div v-if="allocationOff?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOff.allocations" title="场外分配" />
              <AllocationTable :items="allocationOff.allocations" :cashPct="cashPctOff" :cashAmount="cashOff" title="场外 ETF 目标分配" />
            </div>
          </template>
        </template>
        <template #on_exchange>
          <div v-if="loading" class="content-grid" aria-busy="true">
            <div class="card skeleton-card"><Skeleton type="chart" height="260" /></div>
            <div class="card skeleton-card"><Skeleton type="table" rows="6" /></div>
          </div>
          <template v-else>
            <div v-if="allocationOn?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOn.allocations" title="场内分配" />
              <AllocationTable :items="allocationOn.allocations" :cashPct="cashPctOn" :cashAmount="cashOn" title="场内 ETF 目标分配" />
            </div>
          </template>
        </template>
        <template #off_exchange>
          <div v-if="loading" class="content-grid" aria-busy="true">
            <div class="card skeleton-card"><Skeleton type="chart" height="260" /></div>
            <div class="card skeleton-card"><Skeleton type="table" rows="6" /></div>
          </div>
          <template v-else>
            <div v-if="allocationOff?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOff.allocations" title="场外分配" />
              <AllocationTable :items="allocationOff.allocations" :cashPct="cashPctOff" :cashAmount="cashOff" title="场外 ETF 目标分配" />
            </div>
          </template>
        </template>
      </AppTabs>

      <!-- Loading Skeletons (initial fetch not yet attempted) -->
      <div v-if="!fetchAttempted" class="loading-grid" aria-busy="true" aria-label="加载中">
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
        <!-- R54: 加载文案明确化，避免用户误以为卡死 -->
        <p class="loading-hint">正在加载组合数据…</p>
        <div class="card skeleton-card">
          <Skeleton type="chart" height="260" />
        </div>
        <div class="card skeleton-card">
          <Skeleton type="table" rows="6" />
        </div>
      </div>

      <!-- Empty State (fetch attempted, no allocations anywhere)
           R53: 加 !loading 双保险——allocations 全空且仍在加载的中间态继续显示骨架而非空态 -->
      <div v-if="fetchAttempted && !loading && !allocationOn?.allocations?.length && !allocationOff?.allocations?.length" class="empty-state">
        <div class="empty-icon" aria-hidden="true">📊</div>
        <h3 class="empty-title">暂无组合数据</h3>
        <p class="empty-description">请前往「组合与分析」添加 ETF</p>
        <AppButton variant="primary" @click="$router.push('/portfolio-analysis')">
          前往组合与分析
        </AppButton>
      </div>

      <!-- Content + P&L (visible when fetch attempted AND has allocations) -->
      <template v-if="fetchAttempted && (allocationOn?.allocations?.length || allocationOff?.allocations?.length)">
        <!-- Daily P&L Details（F2-2: 刷新时保持骨架防 CLS） -->
        <div v-if="loading" class="card skeleton-card" aria-busy="true">
          <Skeleton type="table" rows="4" />
        </div>
        <template v-else>
          <PnLDetailTable
            :items="pnlItems"
            :activeTab="activeTab"
            :pnlTotal="pnlTotal"
            :pnlTotalAmount="pnlTotalAmount"
            :pnlWeightedChange="pnlWeightedChange"
          />

          <!-- P&L Bar Chart -->
          <PnLBarChart
            :items="pnlItems"
            :loading="loading"
          />
        </template>
      </template>
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useMarketStore } from '../stores/market'
import { usePortfolioStore } from '../stores/portfolio'
import { storeToRefs } from 'pinia'
import logger from '../utils/logger'
import { useDashboardData } from '../composables/useDashboardData'
import { useWarmupStatus } from '../composables/useWarmupStatus'
import GlobalIndicesStrip from '../components/GlobalIndicesStrip.vue'
import AppButton from '../components/ui/AppButton.vue'
import AppTabs from '../components/ui/AppTabs.vue'
import Skeleton from '../components/ui/Skeleton.vue'
import SummaryCards from '../components/dashboard/SummaryCards.vue'
import AllocationPieChart from '../components/dashboard/AllocationPieChart.vue'
import AllocationTable from '../components/dashboard/AllocationTable.vue'
import PnLBarChart from '../components/dashboard/PnLBarChart.vue'
import PnLDetailTable from '../components/dashboard/PnLDetailTable.vue'
import ErrorOverlay from '../components/dashboard/ErrorOverlay.vue'

// Register echarts components (must happen before any chart component mounts)
use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

// UI state
const activeTab = ref('combined')
const renderError = ref(false)

// Shared capital from store (set in Portfolio Analysis page)
const { capitalOn, capitalOff } = storeToRefs(usePortfolioStore())

const route = useRoute()

// Composable – all data logic
const {
  allocationOn, allocationOff, globalIndices,
  pnlHistory, pnlHistoryLoading, loading, fetchAttempted,
  totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
  cashPctOn, cashOn, cashPctOff, cashOff,
  fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
} = useDashboardData(capitalOn, capitalOff, activeTab)

const {
  isWarmingUp, phaseTitle, phaseDesc, startPolling, stopPolling,
} = useWarmupStatus()

const tabs = [
  { value: 'combined', label: '综合' },
  { value: 'on_exchange', label: '场内' },
  { value: 'off_exchange', label: '场外' }
]

const marketTimer = ref(null)
const marketStore = useMarketStore()

onErrorCaptured((err) => {
  logger.error('[Dashboard] Uncaught error:', err)
  renderError.value = true
  return false
})

onMounted(async () => {
  // Start warmup polling (stops automatically when all_done or times out)
  startPolling()
  // R52: 初始加载必须走 refreshAll（统一 fetchAttempted 置位），
  // 旧 Promise.allSettled 路径永远不置位 → 骨架永久显示、空态无法出现
  await refreshAll()
  fetchPnlHistory(activeTab.value)
  marketStore.connectWS((data) => {
    const indices = globalIndices.value
    for (const region of Object.keys(indices)) {
      const list = indices[region]
      const i = list.findIndex(m => m.symbol === data.symbol)
      if (i >= 0) {
        list[i] = { ...list[i], price: data.price, change_pct: data.change_pct, available: true }
      }
    }
  })
  marketTimer.value = setInterval(fetchGlobalIndices, 30000)
})

onUnmounted(() => {
  marketStore.disconnectWS()
  if (marketTimer.value) clearInterval(marketTimer.value)
})

watch(() => route.path, () => {
  refreshAll()
})

watch(activeTab, (tab) => {
  fetchPnlHistory(tab)
})

function onRetry() {
  renderError.value = false
  refreshAll()
}
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.dashboard-tabs {
  margin-bottom: 0;
}
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}
@media (max-width: 1024px) {
  .content-grid { grid-template-columns: 1fr; }
}
.loading-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}
@media (max-width: 1024px) {
  .loading-grid { grid-template-columns: 1fr; }
}
.loading-hint {
  grid-column: 1 / -1;
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.skeleton-card {
  padding: var(--space-5);
}
.card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
/* P0-4: warmup 占位槽固定高度——banner 隐藏/显示不产生布局偏移 */
.warmup-slot {
  grid-column: 1 / -1;
  min-height: 64px;
}
/* Warmup Banner */
.warmup-banner {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-info-subtle);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-2);
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
/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  text-align: center;
  background: var(--color-surface-secondary);
  border: 2px dashed var(--color-border-medium);
  border-radius: var(--radius-xl);
}
.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); max-width: 300px; }
@media (max-width: 640px) {
  .tabs { flex-wrap: wrap; gap: var(--space-2); }
}
</style>
