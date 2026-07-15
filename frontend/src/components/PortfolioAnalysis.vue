<template>
  <div class="portfolio-analysis">
    <div class="pa-layout">
      <!-- Left: holdings list (reuses PortfolioManager) -->
      <aside class="pa-holdings" aria-label="持仓列表">
        <PortfolioManager :selected-symbol="selectedHolding" @select="onSelect" />
      </aside>

      <!-- Right: technical analysis (reuses AnalysisView, driven by selection) -->
      <section class="pa-analysis" aria-label="技术分析">
        <AnalysisView :selected-symbol="selectedHolding" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import PortfolioManager from './PortfolioManager.vue'
import AnalysisView from './AnalysisView.vue'
import { usePortfolioStore } from '../stores/portfolio'

const store = usePortfolioStore()
const selectedHolding = ref('')

function onSelect(etf) {
  selectedHolding.value = etf.symbol
}

// Auto-select the first on-exchange holding so the analysis panel is populated
// as soon as the user lands on the merged view.
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
  gap: var(--space-6);
  height: calc(100vh - 60px - 2 * var(--space-6));
  min-height: 0;
}
.pa-layout {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(520px, 1.4fr);
  gap: var(--space-6);
  align-items: stretch;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.pa-holdings, .pa-analysis { min-width: 0; min-height: 0; overflow-y: auto; }
/* Keep each column's header (tabs / analysis title) pinned while that column scrolls */
.pa-holdings :deep(.page-header),
.pa-analysis :deep(.page-header) {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-surface-primary);
}
@media (max-width: 1024px) {
  .portfolio-analysis { height: auto; }
  .pa-layout { grid-template-columns: 1fr; overflow: visible; }
  .pa-holdings, .pa-analysis { overflow-y: visible; }
}
</style>
