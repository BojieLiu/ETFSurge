<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">🔍 标的分析</h2>
      <p class="section-desc">搜索股票/ETF/板块/指数，查看 AI 深度解读与行情数据</p>
    </div>

    <!-- Analysis mode tabs -->
    <div class="analysis-tabs" role="tablist">
      <button
        v-for="mode in modes" :key="mode.value"
        :class="['analysis-tab', { active: activeMode === mode.value }]"
        @click="activeMode = mode.value"
        role="tab" :aria-selected="activeMode === mode.value"
      >
        {{ mode.label }}
      </button>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <input
            type="text"
            v-model="query"
            :placeholder="currentPlaceholder"
            class="text-input"
            @keydown.enter="doAnalyze"
          />
          <button class="btn-primary" @click="doAnalyze" :disabled="loading">
            {{ loading ? '分析中...' : '🔍 分析' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Quick examples chips -->
    <div v-if="!query" class="quick-chips">
      <span class="chip-label">快速输入:</span>
      <button
        v-for="ex in visibleExamples" :key="ex.code"
        class="chip" @click="quickSelect(ex)">{{ ex.label }}</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="result" class="result" v-html="renderMarkdown(result)"></div>

    <div v-else-if="symbol && !loading" class="result-area">
      <p>已选择: <strong>{{ symbol }}</strong> ({{ currentModeLabel }})</p>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { marketApi } from '../../api'

const props = defineProps({
  marketTab: { type: String, default: 'A' },
  selectedSymbol: { type: String, default: null },
})

const activeMode = ref('symbol')
const query = ref('')
const symbol = ref('')
const loading = ref(false)
const result = ref('')
const error = ref('')
const lastAnalyzed = ref('')

const modes = [
  { value: 'symbol', label: '个股/ETF' },
  { value: 'sector', label: '板块/概念' },
  { value: 'index', label: '指数' },
]

const currentModeLabel = computed(() => {
  const m = modes.find(m => m.value === activeMode.value)
  return m ? m.label : '标的'
})

const placeholders = {
  symbol: '输入代码，如 510050、000001、贵州茅台...',
  sector: '输入板块代码/名称，如 BK0477、半导体...',
  index: '输入指数代码，如 000001 (上证)、HSI (恒生)、SPX (标普)...',
}

const currentPlaceholder = computed(() => placeholders[activeMode.value] || placeholders.symbol)

const EXAMPLES = {
  A: {
    symbol: [
      { code: '510050', label: '上证50ETF' },
      { code: '159915', label: '创业板ETF' },
      { code: '518880', label: '黄金ETF' },
      { code: '513100', label: '纳指ETF' },
    ],
    sector: [
      { code: 'BK0477', label: '半导体' },
      { code: 'BK0445', label: '人工智能' },
      { code: 'BK0891', label: '新能源车' },
    ],
    index: [
      { code: '000001', label: '上证指数' },
      { code: '399001', label: '深证成指' },
      { code: '399006', label: '创业板指' },
    ],
  },
  HK: {
    symbol: [
      { code: '00700', label: '腾讯控股' },
      { code: '09988', label: '阿里巴巴' },
      { code: '02800', label: '盈富基金' },
    ],
    sector: [],
    index: [
      { code: 'HSI', label: '恒生指数' },
      { code: 'HSCEI', label: '国企指数' },
    ],
  },
  US: {
    symbol: [
      { code: 'SPY', label: '标普500ETF' },
      { code: 'QQQ', label: '纳斯达克ETF' },
      { code: 'AAPL', label: 'Apple' },
    ],
    sector: [],
    index: [
      { code: 'SPX', label: '标普500' },
      { code: 'IXIC', label: '纳斯达克' },
    ],
  },
  global: {
    symbol: [
      { code: '000001', label: '上证指数' },
      { code: 'HSI', label: '恒生指数' },
      { code: 'SPX', label: '标普500' },
    ],
    sector: [],
    index: [
      { code: 'IXIC', label: '纳斯达克' },
      { code: 'GC=F', label: '黄金' },
    ],
  },
}

const visibleExamples = computed(() => {
  const byMarket = EXAMPLES[props.marketTab] || EXAMPLES.A
  return byMarket[activeMode.value] || []
})

// Watch selectedSymbol prop for external trigger (from watchlist)
watch(() => props.selectedSymbol, (val) => {
  if (val && val !== lastAnalyzed.value) {
    query.value = val
    symbol.value = val
    nextTick(() => doAnalyze())
  }
})

function quickSelect(ex) {
  query.value = ex.code
  symbol.value = ex.code
  result.value = ''
  error.value = ''
  doAnalyze()
}

async function doAnalyze() {
  const q = query.value.trim()
  if (!q) return
  symbol.value = q
  loading.value = true
  error.value = ''
  result.value = ''
  lastAnalyzed.value = q

  try {
    const typeMap = { symbol: 'symbol', sector: 'sector', index: 'index' }
    const analysisApi = activeMode.value === 'sector'
      ? marketApi.sectorAnalysis?.({ keyword: q, market: props.marketTab })
      : marketApi.marketAnalysis?.({ keyword: q, symbol: q, type: typeMap[activeMode.value] || 'auto', market: props.marketTab })

    if (analysisApi) {
      const res = await analysisApi
      result.value = res?.data?.analysis || res?.data?.result || `分析完成: ${q}`
    } else {
      // Fallback when API not fully wired
      const res = await fetch(`/api/v1/market/search?keyword=${encodeURIComponent(q)}&market=${props.marketTab}`)
      if (res.ok) {
        result.value = `✅ 查询完成: ${q}`
      } else {
        result.value = `分析: ${q}`
      }
    }
  } catch (e) {
    error.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }

.analysis-tabs {
  display: flex;
  gap: 0;
  margin-bottom: var(--space-3);
  border-bottom: 2px solid var(--color-border-light);
}
.analysis-tab {
  padding: var(--space-2) var(--space-4);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  border: none;
  background: none;
  cursor: pointer;
  transition: var(--transition-fast);
  position: relative;
}
.analysis-tab:hover { color: var(--color-text-primary); background: var(--color-bg-secondary); }
.analysis-tab.active {
  color: var(--color-brand-600);
  font-weight: var(--font-weight-semibold);
}
.analysis-tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--color-brand-500);
}

.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-body { padding: var(--space-5); }
.input-row { display: flex; gap: var(--space-3); }
.text-input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-base);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color var(--transition-fast);
}
.text-input:focus { border-color: var(--color-brand-500); box-shadow: 0 0 0 3px var(--color-brand-100); }
.text-input::placeholder { color: var(--color-text-tertiary); }
.btn-primary {
  padding: var(--space-2) var(--space-5);
  font: var(--text-body);
  color: white;
  background: var(--color-brand-600);
  border: none;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: background var(--transition-fast);
  white-space: nowrap;
}
.btn-primary:hover { background: var(--color-brand-700); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.error { margin: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.result { margin-top: var(--space-4); line-height: 1.8; }
.quick-chips { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-3); padding: 0 var(--space-1); }
.chip-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.chip { padding: var(--space-1) var(--space-3); font-size: var(--font-size-sm); font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); color: var(--color-brand-600); background: var(--color-bg-brand-subtle); border: 1px solid var(--color-brand-200); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); }
.chip:hover { background: var(--color-brand-100); border-color: var(--color-brand-400); }
.result-area { margin-top: var(--space-4); padding: var(--space-4); text-align: center; color: var(--color-text-secondary); }
</style>
