<template>
  <div class="market-analysis">
    <PageHeader
      title="行情分析"
      description="市场宏观研判、板块轮动分析与标的深度解读"
    >
      <template #action>
        <AppTabs v-model="marketTab" :tabs="marketTabs" variant="enclosed" full-width />
      </template>
    </PageHeader>

    <Section title="市场研报" :divided="true">
      <MarketReport :marketTab="marketTab" />
    </Section>

    <Section title="自选监控" :divided="true">
      <WatchlistPanel :marketTab="marketTab" @select-symbol="onSelectSymbol" />
    </Section>

    <Section title="AI 智能顾问" :divided="true">
      <AiAdvisor :marketTab="marketTab" />
    </Section>

    <Section title="板块轮动" :divided="true">
      <SectorAnalysis :marketTab="marketTab" />
    </Section>

    <Section title="标的深度" :divided="true">
      <SymbolAnalysis :marketTab="marketTab" :selectedSymbol="selectedSymbol" />
    </Section>

    <Section title="指数分析">
      <IndexAnalysis :marketTab="marketTab" />
    </Section>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import MarketReport from '@/components/market/MarketReport.vue'
import WatchlistPanel from '@/components/market/WatchlistPanel.vue'
import AiAdvisor from '@/components/market/AiAdvisor.vue'
import SectorAnalysis from '@/components/market/SectorAnalysis.vue'
import SymbolAnalysis from '@/components/market/SymbolAnalysis.vue'
import IndexAnalysis from '@/components/market/IndexAnalysis.vue'
import { PageHeader, Section, AppTabs } from '@/components'

const marketTab = ref('A')
const selectedSymbol = ref(null)

const marketTabs = [
  { value: 'A', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
  { value: 'global', label: '全球' }
]

function onSelectSymbol(symbol) {
  selectedSymbol.value = symbol
}
</script>

<style scoped>
.market-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-section-md);
}
</style>