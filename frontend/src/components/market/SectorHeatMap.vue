<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">🔥 热点板块排行</h2>
      <p class="section-desc">实时板块热度与资金流向监测</p>
    </div>

    <div class="card">
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="switchTab(tab.key)"
        >{{ tab.label }}</button>
      </div>

      <div class="card-body">
        <!-- Loading -->
        <div v-if="loading" class="loading-skeleton">
          <div class="skeleton-row" v-for="i in 5" :key="i"></div>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="error">{{ error }}</div>

        <!-- Empty -->
        <div v-else-if="!dataList.length" class="empty-state">暂无板块数据</div>

        <!-- Data Table: Hot Plates -->
        <div v-else-if="activeTab === 'hot'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.plate_name || item.name }}</span>
              <span class="row-desc" v-if="item.reason || item.hot_reason">
                {{ item.reason || item.hot_reason }}
              </span>
              <span class="row-stocks" v-if="item.lead_stocks || item.stocks">
                领涨: {{ leadStockNames(item) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Data Table: Sector Heat -->
        <div v-else-if="activeTab === 'heat'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.sector_name || item.name }}</span>
              <span
                v-if="item.change_pct !== undefined"
                :class="['row-change', item.change_pct >= 0 ? 'text-up' : 'text-down']"
              >
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
            </div>
            <span class="row-heat" v-if="item.heat_index !== undefined">
              热度: {{ fmtHeat(item.heat_index) }}
            </span>
            <span v-if="item.rank_change !== undefined && item.rank_change !== null" :class="['row-rank-chg', item.rank_change >= 0 ? 'text-up' : 'text-down']">
              {{ item.rank_change > 0 ? '↑' : (item.rank_change < 0 ? '↓' : '—') }}{{ item.rank_change ? Math.abs(item.rank_change) : '' }}
            </span>
            <button class="row-action" @click="emitAnalyze('sector', item)" title="AI 分析">🤖 AI</button>
          </div>
        </div>

        <!-- Data Table: Stock Hot Rank -->
        <div v-else-if="activeTab === 'stock'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row data-row--stock"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.name }}</span>
              <span class="row-code">{{ item.code || item.symbol }}</span>
              <span class="row-stock-meta">
                <span v-if="item.price" class="row-price">现价 {{ fmtPrice(item.price) }}</span>
                <span v-if="item.sector" class="row-sector">{{ item.sector }}</span>
                <span v-if="item.turnover" class="row-turnover">成交 {{ fmtTurnover(item.turnover) }}</span>
                <span
                  v-for="(c, ci) in (item.concept_tags || []).slice(0, 3)"
                  :key="ci"
                  class="row-chip"
                >{{ c }}</span>
              </span>
            </div>
            <span
              v-if="item.change_pct !== undefined"
              :class="['row-change', item.change_pct >= 0 ? 'text-up' : 'text-down']"
            >
              {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
            </span>
            <div class="row-actions">
              <button class="row-action" @click="openTechnical(item)" title="技术分析">📈 技术</button>
              <button class="row-action" @click="emitAnalyze('symbol', item)" title="AI 分析">🤖 AI</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- F2-7 步骤E: 技术分析弹窗 -->
    <TechnicalAnalysisModal
      v-if="techModal"
      :symbol="techModal.symbol"
      :name="techModal.name"
      asset-type="A"
      @close="techModal = null"
      @ai="(p) => { techModal = null; emitAnalyze('symbol', p) }"
    />
  </section>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { marketApi } from '../../api'
import TechnicalAnalysisModal from './TechnicalAnalysisModal.vue'

// F2-7 步骤E: 行内「AI 分析」事件（联动 MarketAnalysis → UnifiedAnalysis）
const emit = defineEmits(['analyze'])

// Z31: Accept marketTab prop from parent for market-scoped data
const props = defineProps({
  marketTab: { type: String, default: 'A' },
})

const tabs = [
  { key: 'hot', label: '热点板块' },
  { key: 'heat', label: '板块热度' },
  { key: 'stock', label: '热门个股' },
]
const activeTab = ref('hot')
const dataList = ref([])
const loading = ref(false)
const error = ref('')
const techModal = ref(null)

function fmtPrice(v) {
  return Number(v).toFixed(2)
}

function fmtTurnover(v) {
  const n = Number(v)
  if (!n) return '—'
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(0) + '万'
  return String(n)
}

function fmtHeat(v) {
  const n = Number(v)
  if (!n && n !== 0) return '—'
  return n >= 10000 ? (n / 10000).toFixed(2) + '万' : n.toFixed(1)
}

// F2-7 步骤E: 热点行 → UnifiedAnalysis（symbol / sector 模式）
function emitAnalyze(mode, item) {
  if (mode === 'sector') {
    emit('analyze', { mode: 'sector', query: item.plate_code || item.name, name: item.name || item.plate_name })
  } else {
    emit('analyze', { mode: 'symbol', query: item.symbol || item.code, name: item.name })
  }
}

function openTechnical(item) {
  techModal.value = { symbol: item.symbol || item.code, name: item.name }
}

function leadStockNames(item) {
  const stocks = item.lead_stocks || item.stocks || []
  return stocks.slice(0, 3).map(s => s.name || s.secu_name || '').filter(Boolean).join(', ')
}

async function switchTab(tab) {
  activeTab.value = tab
  dataList.value = []
  error.value = ''
  await fetchData()
}

// Z31: Re-fetch when market tab changes
watch(() => props.marketTab, () => {
  dataList.value = []
  error.value = ''
  fetchData()
})

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    let resp
    switch (activeTab.value) {
      case 'hot':
        resp = await marketApi.getHotPlates(15)
        break
      case 'heat':
        resp = await marketApi.getSectorHeat(20)
        break
      case 'stock':
        resp = await marketApi.getStockHotRank(50)
        break
    }
    // F6 R14: 双兼容——兼容数组（旧）与 {items,total}（hot-plates 契约 v2.0）
    const d = resp.data
    dataList.value = Array.isArray(d) ? d : (d?.items ?? [])
  } catch (e) {
    error.value = '加载失败: ' + (e?.message || '网络错误')
    dataList.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => { fetchData() })
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--text-lg); font-weight: 600; color: var(--color-text-primary); margin: 0; }
.section-desc { font-size: var(--text-sm); color: var(--color-text-secondary); margin-top: var(--space-1); }

.tab-bar { display: flex; gap: var(--space-1); margin-bottom: var(--space-3); border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-1); }
.tab-btn { padding: var(--space-1) var(--space-3); border: none; background: none; cursor: pointer; font-size: var(--text-sm); color: var(--color-text-secondary); border-radius: var(--radius-sm); }
.tab-btn.active { color: var(--color-primary); background: var(--color-bg-hover); font-weight: 600; }
.tab-btn:hover { background: var(--color-bg-hover); }

.card-body { min-height: 120px; }
.loading-skeleton { display: flex; flex-direction: column; gap: var(--space-2); }
.skeleton-row { height: 48px; background: var(--color-bg-hover); border-radius: var(--radius-sm); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 0.8; } }
.error { color: var(--color-danger); font-size: var(--text-sm); }
.empty-state { text-align: center; padding: var(--space-6); color: var(--color-text-tertiary); font-size: var(--text-sm); }

.data-list { display: flex; flex-direction: column; gap: var(--space-1); }
.data-row { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2); border-radius: var(--radius-sm); }
.data-row:hover { background: var(--color-bg-hover); }
.row-rank { width: 24px; text-align: center; font-size: var(--text-sm); color: var(--color-text-tertiary); font-weight: 600; }
.row-main { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.row-name { font-size: var(--text-sm); font-weight: 500; color: var(--color-text-primary); }
.row-desc { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-stocks { font-size: var(--text-xs); color: var(--color-text-secondary); }
.row-code { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-change { font-size: var(--text-sm); font-weight: 500; white-space: nowrap; }
.row-heat { font-size: var(--text-xs); color: var(--color-text-secondary); white-space: nowrap; }
.row-rank-chg { font-size: var(--text-xs); white-space: nowrap; }
.row-actions { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.row-action { padding: 2px 8px; font-size: var(--text-xs); border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface-primary); color: var(--color-text-secondary); cursor: pointer; white-space: nowrap; }
.row-action:hover { border-color: var(--color-primary); color: var(--color-primary); }
.row-stock-meta { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-price, .row-sector, .row-turnover { color: var(--color-text-secondary); }
.row-chip { padding: 1px 6px; border-radius: var(--radius-full); background: var(--color-bg-brand-subtle, rgba(59, 130, 246, 0.08)); border: 1px solid var(--color-brand-200, rgba(59, 130, 246, 0.2)); color: var(--color-brand-600); font-size: var(--text-xs); }
.data-row--stock { flex-wrap: wrap; }
</style>
