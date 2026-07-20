<template>
  <div class="market-analysis">
    <!-- Market Tabs (page-level filter for all sections) -->
    <div class="market-tabs" role="tablist">
      <button v-for="mt in marketTabs" :key="mt.value" :class="['market-tab', { active: marketTab === mt.value }]" @click="marketTab = mt.value" role="tab" :aria-selected="marketTab === mt.value">
        <span class="market-tab-indicator" aria-hidden="true"></span>
        {{ mt.label }}
      </button>
    </div>

    <!-- Section 1: Market Report -->
    <MarketReport :marketTab="marketTab" />

    <!-- Section 1.5: Watchlist -->
    <WatchlistPanel :marketTab="marketTab" @select-symbol="onSelectSymbol" />

    <!-- Section 1.7: AI Advisor -->
    <AiAdvisor :marketTab="marketTab" />

    <!-- Section 2: Sector Analysis -->
    <SectorAnalysis :marketTab="marketTab" />

    <!-- Section 3: Symbol Analysis -->
    <SymbolAnalysis :marketTab="marketTab" :selectedSymbol="selectedSymbol" />

    <!-- Section 4: Index Analysis -->
    <IndexAnalysis :marketTab="marketTab" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MarketReport from '../components/market/MarketReport.vue'
import WatchlistPanel from '../components/market/WatchlistPanel.vue'
import AiAdvisor from '../components/market/AiAdvisor.vue'
import SectorAnalysis from '../components/market/SectorAnalysis.vue'
import SymbolAnalysis from '../components/market/SymbolAnalysis.vue'
import IndexAnalysis from '../components/market/IndexAnalysis.vue'

const marketTab = ref('A')
const selectedSymbol = ref(null)

const marketTabs = [
  { value: 'A', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
  { value: 'global', label: '全球' },
]

function onSelectSymbol(symbol) {
  selectedSymbol.value = symbol
}
</script>

<style scoped>
.market-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

.market-tabs {
  display: flex;
  gap: 0;
  margin-bottom: var(--space-8);
  border-bottom: 2px solid var(--color-border-light);
  padding: 0;
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.market-tab {
  position: relative;
  padding: var(--space-3) var(--space-6);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  border: none;
  background: none;
  cursor: pointer;
  transition: var(--transition-fast);
  letter-spacing: var(--letter-spacing-wide);
}

.market-tab:hover {
  color: var(--color-text-primary);
  background: var(--color-bg-secondary);
}

.market-tab.active {
  color: var(--color-brand-600);
  font-weight: var(--font-weight-semibold);
  background: var(--color-bg-brand-subtle);
}

.market-tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--color-brand-600);
  border-radius: var(--radius-full) var(--radius-full) 0 0;
}

.market-tab-indicator {
  display: none;
}
</style>
