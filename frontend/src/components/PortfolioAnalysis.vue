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

    <!-- Tab Navigation -->
    <div class="pa-tabs" role="tablist" aria-label="功能切换">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        :class="['pa-tab', { 'pa-tab--active': activeTab === tab.value }]"
        @click="activeTab = tab.value"
        role="tab"
        :aria-selected="activeTab === tab.value"
      >
        <span class="pa-tab-icon" aria-hidden="true">{{ tab.icon }}</span>
        <span class="pa-tab-label">{{ tab.label }}</span>
      </button>
    </div>

    <!-- Tab: 持仓 -->
    <div v-if="activeTab === 'holdings'" class="tab-panel" role="tabpanel" aria-label="持仓列表">
      <PortfolioManager :selected-symbol="selectedHolding" @select="onSelect" />
    </div>

    <!-- Tab: 技术分析 -->
    <div v-if="activeTab === 'analysis'" class="tab-panel" role="tabpanel" aria-label="技术分析">
      <AnalysisView :selected-symbol="selectedHolding" />
    </div>

    <!-- Tab: AI 工具 -->
    <div v-if="activeTab === 'tools'" class="tab-panel" role="tabpanel" aria-label="AI 智能工具">
      <DashboardAiTools @applied="refreshData" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import DashboardAiTools from '../views/DashboardAiTools.vue'
import PortfolioManager from './PortfolioManager.vue'
import AnalysisView from './AnalysisView.vue'
import CapitalInputBar from './dashboard/CapitalInputBar.vue'
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

/* Tab Navigation */
.pa-tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-5);
  flex-shrink: 0;
}

.pa-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-family: inherit;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all var(--transition-fast);
  margin-bottom: -1px;
  white-space: nowrap;
}

.pa-tab:hover {
  color: var(--color-text-primary);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}

.pa-tab--active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  font-weight: var(--font-weight-medium);
}

.pa-tab-icon {
  font-size: var(--font-size-base);
  line-height: 1;
}

.pa-tab-label {
  line-height: 1;
}

/* Tab Panels */
.tab-panel {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}
</style>
