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
      <template #analysis>
        <AnalysisView :selected-symbol="selectedHolding" />
      </template>
      <template #tools>
        <DashboardAiTools @applied="refreshData" />
      </template>
    </AppTabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import DashboardAiTools from '../views/DashboardAiTools.vue'
import PortfolioManager from './PortfolioManager.vue'
import AnalysisView from './AnalysisView.vue'
import CapitalInputBar from './dashboard/CapitalInputBar.vue'
import AppTabs from './ui/AppTabs.vue'
import { usePortfolioStore } from '../stores/portfolio'

const store = usePortfolioStore()
const selectedHolding = ref('')
const activeTab = ref('holdings')

const tabs = [
  { value: 'tools', label: 'AI工具', icon: '⚡' },
  { value: 'holdings', label: '持仓', icon: '📋' },
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
</style>
