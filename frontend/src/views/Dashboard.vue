<template>
  <div class="dashboard">
    <ErrorOverlay :hasError="renderError" @retry="onRetry" />

    <template v-if="!renderError">
      <GlobalIndicesStrip ref="globalIndicesStripRef" />

      <!-- Portfolio Type Tabs -->
      <AppTabs
        v-model="activeTab"
        :tabs="tabs"
        variant="line"
        full-width
        aria-label="组合类型"
      />

      <CapitalInputBar
        :activeTab="activeTab"
        :capitalOn="capitalOn"
        :capitalOff="capitalOff"
        @update:capitalOn="capitalOn = $event"
        @update:capitalOff="capitalOff = $event"
        @refresh="refreshAll"
      />

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

      <!-- Loading Skeletons -->
      <div v-if="loading" class="loading-grid" aria-busy="true" aria-label="加载中">
        <AppCard variant="default" :padding="false">
          <AppSkeleton type="chart" height="260" />
        </AppCard>
        <AppCard variant="default" :padding="false">
          <AppSkeleton type="table" rows="6" />
        </AppCard>
      </div>

      <!-- Content -->
      <template v-else>
        <!-- On Exchange -->
        <AppCard
          v-if="allocationOn?.allocations?.length && (activeTab === 'on_exchange' || activeTab === 'combined')"
          title="场内 ETF 目标分配"
          :padding="false"
        >
          <template #header-action>
            <AllocationPieChart :items="allocationOn.allocations" title="场内分配" />
          </template>
          <AllocationTable
            :items="allocationOn.allocations"
            :cashPct="cashPctOn"
            :cashAmount="cashOn"
          />
        </AppCard>

        <!-- Off Exchange -->
        <AppCard
          v-if="allocationOff?.allocations?.length && (activeTab === 'off_exchange' || activeTab === 'combined')"
          title="场外 ETF 目标分配"
          :padding="false"
        >
          <template #header-action>
            <AllocationPieChart :items="allocationOff.allocations" title="场外分配" />
          </template>
          <AllocationTable
            :items="allocationOff.allocations"
            :cashPct="cashPctOff"
            :cashAmount="cashOff"
          />
        </AppCard>

        <!-- Empty State -->
        <AppCard v-if="!allocationOn?.allocations?.length && !allocationOff?.allocations?.length" variant="filled" class="empty-state-card">
          <template #default>
            <div class="empty-state">
              <div class="empty-icon" aria-hidden="true">📊</div>
              <h3 class="empty-title">暂无组合数据</h3>
              <p class="empty-description">请前往「组合与分析」添加 ETF</p>
              <AppButton variant="primary" @click="$router.push('/portfolio-analysis')">
                前往组合与分析
              </AppButton>
            </div>
          </template>
        </AppCard>

        <!-- Daily P&L Details -->
        <AppCard title="每日盈亏明细" :padding="false">
          <PnLDetailTable
            :items="pnlItems"
            :activeTab="activeTab"
            :pnlTotal="pnlTotal"
            :pnlTotalAmount="pnlTotalAmount"
            :pnlWeightedChange="pnlWeightedChange"
          />
        </AppCard>

        <!-- P&L Bar Chart -->
        <AppCard title="盈亏分布图" :padding="false">
          <PnLBarChart :items="pnlItems" :loading="loading" />
        </AppCard>
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
import { useMarketStore } from '../stores/market'
import logger from '../utils/logger'
import { useDashboardData } from '../composables/useDashboardData'
import GlobalIndicesStrip from '../components/GlobalIndicesStrip.vue'
import AppButton from '../components/ui/AppButton.vue'
import AppCard from '../components/ui/AppCard.vue'
import AppTabs from '../components/ui/AppTabs.vue'
import AppSkeleton from '../components/ui/Skeleton.vue'
import CapitalInputBar from '../components/dashboard/CapitalInputBar.vue'
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
const capitalOn = ref(500000)
const capitalOff = ref(500000)
const renderError = ref(false)

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

const globalIndicesStripRef = ref(null)
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
  marketTimer.value = setInterval(fetchGlobalIndices, 60000)
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
  gap: var(--space-section-md);
}

.loading-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-gap-md);
}

@media (min-width: 1024px) {
  .loading-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.empty-state-card {
  padding: var(--space-section-xl);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-gap-md);
  color: var(--color-text-secondary);
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.empty-title {
  margin: 0;
  font: var(--text-h3);
  color: var(--color-text-primary);
}

.empty-description {
  margin: 0;
  font: var(--text-body);
  max-width: 300px;
}

/* AppTab integration styles */
.tabs__tab {
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}
</style>