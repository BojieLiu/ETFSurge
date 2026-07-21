<template>
  <div class="portfolio-analysis">
    <PageHeader
      title="组合分析"
      description="持仓管理、技术分析与 AI 智能工具"
    >
      <template #action>
        <AppTabs
          v-model="activeTab"
          :tabs="tabs"
          variant="line"
          full-width
        />
      </template>
    </PageHeader>

    <div class="portfolio-analysis__content" role="tabpanel" :aria-label="activeTabLabel">
      <Section v-if="activeTab === 'holdings'" :divided="false" :padded="false">
        <PortfolioManager :selected-symbol="selectedHolding" @select="onSelect" />
      </Section>

      <Section v-else-if="activeTab === 'analysis'" :divided="false" :padded="false">
        <AnalysisView :selected-symbol="selectedHolding" />
      </Section>

      <Section v-else-if="activeTab === 'tools'" :divided="false" :padded="false">
        <DashboardAiTools @applied="refreshData" />
      </Section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import DashboardAiTools from '@/views/DashboardAiTools.vue'
import PortfolioManager from '@/components/PortfolioManager.vue'
import AnalysisView from '@/components/AnalysisView.vue'
import { usePortfolioStore } from '@/stores/portfolio'
import { PageHeader, Section, AppTabs } from '@/components'

const store = usePortfolioStore()
const selectedHolding = ref('')
const activeTab = ref('tools')

const tabs = [
  { value: 'tools', label: 'AI工具', icon: '⚡' },
  { value: 'holdings', label: '持仓', icon: '📋' },
  { value: 'analysis', label: '技术分析', icon: '📊' }
]

const activeTabLabel = computed(() => {
  const tab = tabs.find(t => t.value === activeTab.value)
  return tab ? tab.label : ''
})

function onSelect(etf) {
  selectedHolding.value = etf.symbol
}

function refreshData() {
  store.fetchEtfs()
  store.fetchEtfs('on_exchange')
  store.fetchEtfs('off_exchange')
}

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
  height: 100%;
  min-height: 0;
}

.portfolio-analysis__content {
  flex: 1;
  overflow: auto;
  min-height: 0;
}
</style>