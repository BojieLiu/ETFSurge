<template>
  <div class="portfolio-analysis">
    <!-- Capital Input -->
    <CapitalInputBar
      :activeTab="'combined'"
      :capitalOn="store.capitalOn"
      :capitalOff="store.capitalOff"
      @update:capitalOn="store.capitalOn = $event"
      @update:capitalOff="store.capitalOff = $event"
      @refresh="refreshData"
      @refresh-on="refreshOn"
      @refresh-off="refreshOff"
    />

    <!-- Tab Navigation + Content -->
    <AppTabs :tabs="tabs" v-model="activeTab" variant="line" ariaLabel="功能切换" class="pa-apptabs">
      <template #holdings>
        <PortfolioManager :selected-symbol="selectedHolding" @select="onSelect" />
      </template>
      <!-- round34-B7 批复①②：Dashboard 持仓分配/盈亏明细/累计盈亏迁入本页「盈亏」tab -->
      <template #pnl>
        <div class="pa-pnl">
          <AppTabs :tabs="scopeTabs" v-model="scope" variant="soft" full-width ariaLabel="组合范围" class="pa-scopetabs" />
          <div v-if="!pnlFetchAttempted || dashLoading" class="content-grid" aria-busy="true">
            <div class="pa-card skeleton-card"><Skeleton type="chart" height="280" /></div>
            <div class="pa-card skeleton-card"><Skeleton type="table" rows="6" /><!-- TODO(R114): rows 硬编码，应绑定 props 或动态值 --></div>
          </div>
          <template v-else>
            <SummaryCards
              :activeTab="scope"
              :totalAll="totalAll"
              :pnlOn="pnlOn"
              :pnlOff="pnlOff"
              :pnlTotal="pnlTotal"
              :pnlHistory="pnlHistory"
              :pnlHistoryLoading="pnlHistoryLoading"
              :loading="dashLoading"
              :lastUpdated="null"
            />
            <div v-if="allocationOn?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOn.allocations" title="场内分配" />
              <AllocationTable :items="allocationOn.allocations" :cashPct="cashPctOn" :cashAmount="cashOn" title="场内 ETF 目标分配" />
            </div>
            <div v-if="allocationOff?.allocations?.length" class="content-grid">
              <AllocationPieChart :items="allocationOff.allocations" title="场外分配" />
              <AllocationTable :items="allocationOff.allocations" :cashPct="cashPctOff" :cashAmount="cashOff" title="场外 ETF 目标分配" />
            </div>
            <PnLDetailTable
              :items="pnlItems"
              :activeTab="scope"
              :pnlTotal="pnlTotal"
              :pnlTotalAmount="pnlTotalAmount"
              :pnlWeightedChange="pnlWeightedChange"
            />
            <PnLBarChart :items="pnlItems" :loading="dashLoading" />
          </template>
        </div>
      </template>
      <template #analysis>
        <AnalysisView :selected-symbol="selectedHolding" />
      </template>
    </AppTabs>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
// ECharts 组件注册（盈亏 tab 的图表在本页挂载，须先注册）
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { storeToRefs } from 'pinia'
import PortfolioManager from '../components/portfolio/PortfolioManager.vue'
import AnalysisView from '../components/portfolio/AnalysisView.vue'
import CapitalInputBar from '../components/dashboard/CapitalInputBar.vue'
import SummaryCards from '../components/dashboard/SummaryCards.vue'
import AllocationPieChart from '../components/dashboard/AllocationPieChart.vue'
import AllocationTable from '../components/dashboard/AllocationTable.vue'
import PnLBarChart from '../components/dashboard/PnLBarChart.vue'
import PnLDetailTable from '../components/dashboard/PnLDetailTable.vue'
import Skeleton from '../components/ui/Skeleton.vue'
import AppTabs from '../components/ui/AppTabs.vue'
import { usePortfolioStore } from '../stores/portfolio'
import { useDashboardData } from '../composables/useDashboardData'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const store = usePortfolioStore()
const selectedHolding = ref('')
const activeTab = ref('holdings')

const tabs = [
  { value: 'holdings', label: '持仓', icon: '📋' },
  { value: 'pnl', label: '盈亏', icon: '💰' },
  { value: 'analysis', label: '技术分析', icon: '📊' },
]

function onSelect(etf) {
  selectedHolding.value = etf.symbol
}

function refreshData() {
  store.fetchEtfs()
  store.fetchEtfs('on_exchange')
  store.fetchEtfs('off_exchange')
}

function refreshOn() {
  store.fetchEtfs('on_exchange')
}

function refreshOff() {
  store.fetchEtfs('off_exchange')
}

// ── 盈亏 tab 数据（round34-B7）：自有 useDashboardData 实例，首次进入时拉取 ──
const scope = ref('combined')
const scopeTabs = [
  { value: 'combined', label: '综合' },
  { value: 'on_exchange', label: '场内' },
  { value: 'off_exchange', label: '场外' },
]
const { capitalOn, capitalOff } = storeToRefs(store)
const {
  allocationOn, allocationOff,
  pnlHistory, pnlHistoryLoading, loading: dashLoading, fetchAttempted: pnlFetchAttempted,
  totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
  cashPctOn, cashOn, cashPctOff, cashOff,
  refreshAll: refreshDash, fetchPnlHistory,
} = useDashboardData(capitalOn, capitalOff, scope)

const pnlInited = ref(false)
async function initPnl() {
  if (pnlInited.value) return
  pnlInited.value = true
  await refreshDash()
  fetchPnlHistory(scope.value)
}
watch(activeTab, (t) => {
  if (t === 'pnl') initPnl()
})
watch(scope, () => {
  if (pnlInited.value) fetchPnlHistory(scope.value)
})

// Auto-select the first on-exchange holding so the analysis panel is populated
// when the user switches to the analysis tab.
onMounted(async () => {
  try {
    await store.fetchEtfs('on_exchange')
  } catch { /* ignore */ }
  if (!selectedHolding.value && store.onExchange.length) {
    selectedHolding.value = store.onExchange[0].symbol
  }
})
</script>

<style scoped>
.portfolio-analysis {
  display: flex;
  flex-direction: column;
  gap: 0;
  height: calc(100vh - 60px - 2 * var(--space-6));
  min-height: 0;
}

/* AppTabs panel: fill remaining height */
.pa-apptabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.pa-apptabs :deep(.tabs__panel) {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

/* 盈亏 tab 布局 */
.pa-pnl {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding-top: var(--space-2);
}
.pa-scopetabs {
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
.pa-card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.skeleton-card {
  padding: var(--space-5);
}
</style>
