<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">📈</span>
        个股/ETF 分析
      </h2>
      <p class="section-desc">技术图表、指标叠加与 AI 标的研报</p>
    </div>

    <div class="card analysis-controls">
      <div class="card-body">
        <!-- Search Input -->
        <div class="form-group form-group--search">
          <label class="form-label" for="symbol-search">搜索标的</label>
          <div class="search-combo" ref="searchRef">
            <AppInput
              id="symbol-search"
              v-model="searchQuery"
              placeholder="搜索 ETF 或股票代码/名称..."
              :clearable="true"
              @input="onSearchInput"
              @keydown="onSearchKeydown"
              @focus="onSearchFocus"
              @blur="onSearchBlur"
            />
            <Transition name="dropdown">
              <div v-if="showDropdown && searchResults.length" class="search-dropdown">
                <div v-if="completionFull" class="search-hint">按 <kbd>Tab</kbd> 补全：{{ completionFull }}</div>
                <div
                  v-for="(r, i) in searchResults"
                  :key="r.symbol"
                  :class="['search-item', { active: i === activeIndex }]"
                  @mousedown.prevent="selectSearchItem(r)"
                  @mouseenter="activeIndex = i"
                >
                  <span class="si-name">{{ r.name }} <code>({{ r.symbol }})</code></span>
                  <span class="si-type" :class="r.type === 'ETF' ? 'type-etf' : 'type-stock'">{{ r.type }}</span>
                </div>
              </div>
            </Transition>
          </div>
          <div class="search-actions">
            <AppButton v-if="selectedSearchItem" variant="ghost" size="xs" @click="clearSearchItem">清除</AppButton>
            <AppButton variant="primary" @click="searchFromQuery" :disabled="!canAnalyzeSymbol">
              <span class="btn-icon" aria-hidden="true">🔍</span> 分析
            </AppButton>
            <AppButton variant="ghost" @click="analyzeSymbol" :loading="symbolLoading" :disabled="symbolLoading || !selectedSearchItem">
              <span class="btn-icon" aria-hidden="true">🤖</span> AI 研报
            </AppButton>
          </div>
        </div>
      </div>
    </div>

    <!-- No Selection State -->
    <div v-if="!selectedSearchItem && !searchQuery" class="empty-prompt">
      <span class="prompt-icon" aria-hidden="true">💡</span>
      <p>搜索并选择一个标的开始分析</p>
    </div>

    <!-- Chart Section -->
    <div v-if="selectedSearchItem" class="card chart-card">
      <div class="card-header">
        <h3 class="card-title">{{ selectedSearchItem.name }} ({{ selectedSearchItem.symbol }})</h3>
        <div class="card-controls">
          <AppSelect v-model="period" :options="periodOptions" size="sm" @change="fetchAll" />
          <div class="chart-mode-toggle" role="radiogroup" aria-label="图表类型">
            <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'kline' }]" @click="chartMode = 'kline'">📊 K线</button>
            <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'intraday' }]" @click="chartMode = 'intraday'">📈 分时</button>
          </div>
          <AppButton variant="secondary" size="sm" @click="fetchAll" :loading="loading">
            <span class="animate-spin" v-if="loading" aria-hidden="true">⏳</span>
            <span v-else>🔄</span>
          </AppButton>
        </div>
      </div>
      <div class="card-body">
        <div v-if="loading" class="loading-state"><div class="loading-spinner"></div><p>加载图表数据...</p></div>
        <div v-else-if="!chartData" class="empty-prompt"><p>暂无数据</p></div>
        <div v-else>
          <!-- ECharts container would go here -->
          <div :style="{ height: faChartHeight + 'px' }" ref="chartContainerRef">图表区域</div>
        </div>
      </div>
    </div>

    <!-- Indicators -->
    <div v-if="indicatorData" class="card">
      <div class="card-header"><h3 class="card-title">技术指标</h3></div>
      <div class="card-body">
        <div class="indicator-toggles">
          <label v-for="tog in indicatorToggles" :key="tog.key" class="toggle-item">
            <input type="checkbox" v-model="tog.model" /> {{ tog.label }}
          </label>
        </div>
        <div class="indicators-grid">
          <div v-for="item in indicatorItems" :key="item.key" class="indicator-item">
            <span class="indicator-label">{{ item.label }}</span>
            <span class="indicator-value" :class="item.class">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Signal -->
    <div v-if="signal" class="card">
      <div class="card-header"><h3 class="card-title">综合买卖信号</h3></div>
      <div class="card-body">
        <div class="signal-content">
          <div :class="['signal-badge', signal?.signal]">
            <span class="signal-icon">{{ signalIcon }}</span>
            <span>{{ signalText }}</span>
          </div>
          <div class="signal-score">综合评分: <strong>{{ signal?.score || '--' }}</strong></div>
          <ul v-if="signal?.reasons?.length" class="signal-reasons">
            <li v-for="(r, i) in signal.reasons" :key="i">{{ r }}</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- AI Report -->
    <div v-if="symbolReport" class="card ai-analysis-card">
      <div class="card-header"><h3 class="card-title">🤖 AI 分析</h3></div>
      <div class="card-body report-container">
        <div class="report-content" v-html="renderMarkdown(symbolReport)"></div>
        <div class="report-disclaimer">
          <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
          <span>本工具仅供个人研究，不构成任何投资建议</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useMarketSearch } from '../../composables/useMarketSearch'
import { useChartView } from '../../composables/useChartView'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({
  marketTab: { type: String, default: 'A' },
  selectedSymbol: { type: String, default: null },
})

const {
  searchQuery, searchResults, showDropdown, activeIndex, completionFull,
  selectedSearchItem, searchRef, onSearchInput, onSearchFocus, onSearchBlur,
  onSearchKeydown, selectSearchItem, clearSearchItem, doSearch
} = useMarketSearch()

const selectedSymbolRef = computed(() => props.selectedSymbol)
const assetType = computed(() => props.marketTab)
const { period, chartMode, chartData: faChartData, indicatorData, signal, loading,
  showMA5, showMA10, showMA20, showMA60, showBoll, showMACD,
  periodOptions, signalText, signalIcon, fetchAll } = useChartView(selectedSymbolRef, assetType)

const symbolReport = ref('')
const symbolLoading = ref(false)
const symbolError = ref('')
const chartContainerRef = ref(null)

const faChartHeight = computed(() => Math.max(480, window.innerHeight - 500))

const indicatorToggles = [
  { key: 'ma5', label: 'MA5', model: showMA5 },
  { key: 'ma10', label: 'MA10', model: showMA10 },
  { key: 'ma20', label: 'MA20', model: showMA20 },
  { key: 'ma60', label: 'MA60', model: showMA60 },
  { key: 'boll', label: '布林带', model: showBoll },
  { key: 'macd', label: 'MACD', model: showMACD },
]

const indicatorItems = computed(() => {
  if (!indicatorData.value) return []
  const d = indicatorData.value
  return [
    { key: 'ma5', label: 'MA5', value: d.ma5?.toFixed(2) ?? '--', class: '' },
    { key: 'ma10', label: 'MA10', value: d.ma10?.toFixed(2) ?? '--', class: '' },
    { key: 'ma20', label: 'MA20', value: d.ma20?.toFixed(2) ?? '--', class: '' },
    { key: 'ma60', label: 'MA60', value: d.ma60?.toFixed(2) ?? '--', class: '' },
    { key: 'rsi', label: 'RSI(14)', value: d.rsi?.toFixed(2) ?? '--', class: d.rsi >= 70 ? 'text-danger' : d.rsi <= 30 ? 'text-success' : '' },
    { key: 'macd', label: 'MACD', value: d.macd?.macd?.toFixed(4) ?? '--', class: (d.macd?.macd || 0) >= 0 ? 'text-success' : 'text-danger' },
    { key: 'kdj', label: 'KDJ-K', value: d.kdj?.k?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-upper', label: 'BOLL上轨', value: d.bollinger?.upper?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-lower', label: 'BOLL下轨', value: d.bollinger?.lower?.toFixed(2) ?? '--', class: '' },
  ]
})

const canAnalyzeSymbol = computed(() => {
  if (selectedSearchItem.value) return true
  const q = searchQuery.value.trim()
  if (!q) return false
  return q.length >= 2
})

function searchFromQuery() {
  if (canAnalyzeSymbol.value && !selectedSearchItem.value) {
    const q = searchQuery.value.trim()
    selectedSearchItem.value = { symbol: q, name: q, type: 'ETF' }
    fetchAll()
  } else if (selectedSearchItem.value) {
    fetchAll()
  }
}

const { streaming: symbolStreaming, fullText: symbolStreamText, start: startSymbolStream, disclaimer: symbolStreamDisclaimer } = useLLMStream()

async function analyzeSymbol() {
  if (!selectedSearchItem.value) {
    const q = searchQuery.value.trim()
    if (!q) return
    selectedSearchItem.value = { symbol: q, name: q, type: 'ETF' }
  }
  symbolLoading.value = true
  symbolReport.value = ''
  symbolError.value = ''
  symbolStreamDisclaimer.value = ''
  try {
    const result = await startSymbolStream('/symbol-analysis/stream', {
      symbol: selectedSearchItem.value.symbol,
      name: selectedSearchItem.value.name,
      asset_type: props.marketTab,
    }, (token) => {
      symbolReport.value += token
    })
  } catch (e) {
    symbolError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    symbolLoading.value = false
  }
}
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-1); }
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: visible; margin-bottom: var(--space-4); }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); flex-wrap: wrap; }
.card-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-body { padding: var(--space-5); }
.card-controls { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.form-group--search { display: flex; flex-direction: column; gap: var(--space-1.5); }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.search-combo { position: relative; }
.search-actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; min-width: 340px; max-width: 480px; max-height: 420px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); padding: var(--space-1); }
.search-dropdown > div { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
.search-dropdown > div:hover, .search-dropdown > div.active { background: var(--color-surface-hover); }
.search-hint { font-size: var(--font-size-xs); color: var(--color-text-tertiary); padding: var(--space-1) var(--space-2); }
.search-hint kbd { font-family: var(--font-family-mono); font-size: var(--font-size-xs); padding: 1px 4px; background: var(--color-surface-tertiary); border-radius: var(--radius-xs); border: 1px solid var(--color-border-light); }
.si-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-primary); }
.si-name code { font-family: var(--font-family-mono); color: var(--color-text-tertiary); }
.si-type { font-size: var(--font-size-xs); padding: 1px 6px; border-radius: var(--radius-full); }
.si-type.type-etf { background: var(--color-bg-brand-subtle); color: var(--color-brand-700); }
.si-type.type-stock { background: var(--color-bg-success-subtle); color: var(--color-success-700); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.loading-spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.prompt-icon { font-size: var(--font-size-3xl); }
.chart-mode-toggle { display: inline-flex; background: var(--color-surface-tertiary); border-radius: var(--radius-md); padding: var(--space-1); gap: var(--space-1); }
.mode-btn { padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); border-radius: var(--radius-sm); background: transparent; border: none; cursor: pointer; transition: var(--transition-fast); }
.mode-btn:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.mode-btn--active { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.indicators-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-3); margin-top: var(--space-3); }
.indicator-item { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-3); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg); }
.indicator-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.indicator-value { font-family: var(--font-family-mono); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.text-success { color: var(--color-text-success); }
.text-danger { color: var(--color-text-danger); }
.indicator-toggles { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.toggle-item { display: inline-flex; align-items: center; gap: var(--space-1); font-size: var(--font-size-sm); cursor: pointer; }
.signal-content { display: flex; flex-direction: column; align-items: center; gap: var(--space-4); text-align: center; }
.signal-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-6); font-size: var(--font-size-xl); font-weight: var(--font-weight-bold); border-radius: var(--radius-full); }
.signal-badge.buy { color: var(--color-success-700); background: var(--color-bg-success-subtle); border: 2px solid var(--color-success-300); }
.signal-badge.sell { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 2px solid var(--color-danger-300); }
.signal-badge.hold { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); border: 2px solid var(--color-warning-300); }
.signal-icon { font-size: var(--font-size-2xl); }
.signal-score { font-size: var(--font-size-base); color: var(--color-text-secondary); }
.signal-score strong { font-family: var(--font-family-mono); font-size: var(--font-size-xl); color: var(--color-text-primary); }
.signal-reasons { list-style: none; padding: 0; margin: var(--space-4) 0 0; display: flex; flex-direction: column; gap: var(--space-2); width: 100%; max-width: 400px; }
.signal-reasons li { padding: var(--space-2) var(--space-3); font-size: var(--font-size-sm); color: var(--color-text-secondary); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-md); text-align: left; }
.report-container { margin-top: var(--space-4); }
.report-content :deep(p) { margin: var(--space-2) 0; }
.report-disclaimer { margin-top: var(--space-4); padding: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-secondary); border-radius: var(--radius-md); }
</style>
