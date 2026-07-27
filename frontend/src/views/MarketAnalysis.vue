<template>
  <div class="market-analysis">
    <!-- Top Bar: Market Tabs + Quick Actions -->
    <div class="ma-top-bar">
      <div class="market-tabs" role="tablist">
        <button
          v-for="mt in marketTabs" :key="mt.value"
          :class="['market-tab', { active: marketTab === mt.value }]"
          @click="marketTab = mt.value"
          role="tab" :aria-selected="marketTab === mt.value"
        >
          {{ mt.label }}
        </button>
      </div>

      <div class="quick-bar" role="toolbar" aria-label="快速操作">
        <button class="qb-btn" @click="scrollTo('report')" title="市场综合研判">
          <span class="qb-icon" aria-hidden="true">📊</span>
          <span class="qb-label">市场研判</span>
        </button>
        <button class="qb-btn" @click="scrollTo('watch')" title="自选列表">
          <span class="qb-icon" aria-hidden="true">⭐</span>
          <span class="qb-label">自选</span>
        </button>
        <button class="qb-btn" @click="scrollTo('sector')" title="热点板块">
          <span class="qb-icon" aria-hidden="true">🔥</span>
          <span class="qb-label">板块</span>
        </button>
        <button class="qb-btn" @click="scrollTo('advisor')" title="AI 投资顾问">
          <span class="qb-icon" aria-hidden="true">💬</span>
          <span class="qb-label">AI顾问</span>
        </button>
        <button class="qb-btn" @click="scrollTo('symbol')" title="标的深度分析">
          <span class="qb-icon" aria-hidden="true">🔍</span>
          <span class="qb-label">标的分析</span>
        </button>
      </div>
    </div>

    <!-- Sections — 直接渲染，无折叠 -->
    <div ref="anchorReport" class="section-anchor"></div>
    <MarketReport :marketTab="marketTab" />

    <div ref="anchorWatch" class="section-anchor"></div>
    <WatchlistPanel :marketTab="marketTab" @select-symbol="onSelectSymbol" />

    <div ref="anchorSector" class="section-anchor"></div>
    <SectorHeatMap />

    <div ref="anchorAdvisor" class="section-anchor"></div>
    <AiAdvisor :marketTab="marketTab" />

    <div ref="anchorSymbol" class="section-anchor"></div>
    <UnifiedAnalysis :marketTab="marketTab" :selectedSymbol="selectedSymbol" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MarketReport from '../components/market/MarketReport.vue'
import WatchlistPanel from '../components/market/WatchlistPanel.vue'
import AiAdvisor from '../components/market/AiAdvisor.vue'
import UnifiedAnalysis from '../components/market/UnifiedAnalysis.vue'
import SectorHeatMap from '../components/market/SectorHeatMap.vue'

const marketTab = ref('A')
const selectedSymbol = ref(null)

const marketTabs = [
  { value: 'A', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
  { value: 'global', label: '全球' },
]

// Scroll anchors for quick bar navigation
const anchorReport = ref(null)
const anchorWatch = ref(null)
const anchorAdvisor = ref(null)
const anchorSymbol = ref(null)
const anchorSector = ref(null)
const anchorMap = {
  report: anchorReport, watch: anchorWatch, sector: anchorSector, advisor: anchorAdvisor,
  symbol: anchorSymbol,
}

function scrollTo(name) {
  anchorMap[name].value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onSelectSymbol(symbol) {
  selectedSymbol.value = symbol
  setTimeout(() => anchorSymbol.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
}
</script>

<style scoped>
.market-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* ── Top bar ── */
.ma-top-bar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.market-tabs {
  display: flex;
  gap: 0;
  background: var(--color-surface-secondary);
  border-bottom: 2px solid var(--color-border-light);
}

.market-tab {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  border: none;
  background: none;
  cursor: pointer;
  transition: var(--transition-fast);
  letter-spacing: var(--letter-spacing-wide);
  text-align: center;
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
  border-radius: var(--radius-full);
}

/* ── Quick Action Bar ── */
.quick-bar {
  display: flex;
  gap: 2px;
  padding: var(--space-1) var(--space-2);
  background: var(--color-surface-primary);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.qb-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1.5) var(--space-2.5);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: var(--transition-fast);
  white-space: nowrap;
}

.qb-btn:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
  border-color: var(--color-border-light);
}

.qb-icon { font-size: var(--font-size-base); line-height: 1; }
.qb-label { line-height: 1; }

/* ── Scroll anchor ── */
.section-anchor {
  scroll-margin-top: 130px;
}
</style>
