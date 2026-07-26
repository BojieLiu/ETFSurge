<template>
  <div class="dashboard">
    <ErrorOverlay :hasError="renderError" @retry="onRetry" />

    <template v-if="!renderError">
      <GlobalIndicesStrip :globalIndices="globalIndices" />

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
          <template v-if="!loading">
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
          <template v-if="!loading">
            <div v-if="allocationOn?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOn.allocations" title="场内分配" />
              <AllocationTable :items="allocationOn.allocations" :cashPct="cashPctOn" :cashAmount="cashOn" title="场内 ETF 目标分配" />
            </div>
          </template>
        </template>
        <template #off_exchange>
          <template v-if="!loading">
            <div v-if="allocationOff?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOff.allocations" title="场外分配" />
              <AllocationTable :items="allocationOff.allocations" :cashPct="cashPctOff" :cashAmount="cashOff" title="场外 ETF 目标分配" />
            </div>
          </template>
        </template>
      </AppTabs>

      <!-- Loading Skeletons -->
      <div v-if="loading" class="loading-grid" aria-busy="true" aria-label="加载中">
        <div class="card skeleton-card">
          <Skeleton type="chart" height="260" />
        </div>
        <div class="card skeleton-card">
          <Skeleton type="table" rows="6" />
        </div>
      </div>

      <!-- Empty State & P&L Sections (visible when not loading) -->
      <template v-if="!loading">
        <!-- Empty State -->
        <div v-if="!allocationOn?.allocations?.length && !allocationOff?.allocations?.length" class="empty-state">
          <div class="empty-icon" aria-hidden="true">📊</div>
          <h3 class="empty-title">暂无组合数据</h3>
          <p class="empty-description">请前往「组合与分析」添加 ETF</p>
          <AppButton variant="primary" @click="$router.push('/portfolio-analysis')">
            前往组合与分析
          </AppButton>
        </div>

        <!-- Daily P&L Details -->
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
  pnlHistory, pnlHistoryLoading, loading,
  totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
  cashPctOn, cashOn, cashPctOff, cashOff,
  fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
} = useDashboardData(capitalOn, capitalOff, activeTab)

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
  await Promise.allSettled([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])
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
@media (max-width: 480px) {
  .tabs { flex-wrap: wrap; gap: var(--space-2); }
}
</style>
