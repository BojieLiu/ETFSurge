<template>
  <div class="analysis">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">技术分析</h1>
      <p class="page-description">多周期 K 线、分时图、技术指标与综合买卖信号</p>
    </header>

    <!-- Control Panel -->
    <section class="card control-panel">
      <div class="control-row">
        <div class="control-group control-group--primary">
          <label class="control-label" for="etf-select">分析标的</label>
          <div class="control-field">
            <AppSelect
              id="etf-select"
              v-model="selected"
              :options="etfOptions"
              placeholder="选择 ETF 或指数..."
              size="md"
              @change="onSelectEtf"
            />
            <span v-if="analyzingIndex" class="index-badge">
              <span class="badge-icon" aria-hidden="true">📊</span>
              分析标的: {{ analyzingIndex }} (跟踪指数)
            </span>
          </div>
        </div>

        <div class="control-group">
          <label class="control-label" for="period-select">周期</label>
          <div class="control-field">
            <AppSelect
              id="period-select"
              v-model="period"
              :options="periodOptions"
              size="md"
              @change="fetchChart"
            />
          </div>
        </div>

        <div class="control-group">
          <label class="control-label">图表类型</label>
          <div class="control-field">
            <div class="chart-mode-toggle" role="radiogroup" aria-label="图表类型">
              <button
                type="button"
                role="radio"
                :aria-pressed="chartMode === 'kline'"
                :class="['mode-btn', { 'mode-btn--active': chartMode === 'kline' }]"
                @click="chartMode = 'kline'"
              >
                <span class="mode-icon" aria-hidden="true">📊</span> K 线
              </button>
              <button
                type="button"
                role="radio"
                :aria-pressed="chartMode === 'intraday'"
                :class="['mode-btn', { 'mode-btn--active': chartMode === 'intraday' }]"
                @click="chartMode = 'intraday'"
              >
                <span class="mode-icon" aria-hidden="true">📈</span> 分时
              </button>
            </div>
          </div>
        </div>

        <div class="control-group control-group--action">
          <div class="control-field">
            <AppButton variant="primary" @click="fetchChart" :loading="loading">
              <span class="btn-icon" aria-hidden="true" v-if="!loading">🔄</span>
              <span class="animate-spin" v-else aria-hidden="true">⏳</span>
              {{ loading ? '加载中...' : '刷新' }}
            </AppButton>
          </div>
        </div>

        <div class="control-group control-group--info" v-if="chartData">
          <div class="control-field">
            <span class="data-count">{{ chartData.dates.length }} 条数据</span>
          </div>
        </div>
      </div>

      <!-- Indicator Toggles -->
      <div class="indicator-toggles" v-if="chartData" role="group" aria-label="技术指标叠加">
        <span class="toggles-label">叠加指标:</span>
        <div class="toggles-grid">
          <label class="toggle-item" v-for="ind in indicatorToggles" :key="ind.key">
            <input type="checkbox" v-model="ind.model" @change="fetchChart" />
            <span class="toggle-name">{{ ind.label }}</span>
          </label>
        </div>
      </div>
    </section>

    <!-- Loading State -->
    <div v-if="loading" class="loading-state" role="status" aria-busy="true">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p>正在获取行情数据...</p>
    </div>

    <!-- Chart -->
    <section class="card chart-section" v-if="chartData && !loading">
      <v-chart :option="chartOption" :style="{ height: chartHeight + 'px' }" autoresize />
    </section>

    <!-- Empty State -->
    <section class="card empty-state" v-if="!chartData && !loading && selected">
      <div class="empty-icon" aria-hidden="true">📊</div>
      <h3 class="empty-title">暂无图表数据</h3>
      <p class="empty-description">请尝试切换周期或稍后刷新</p>
      <AppButton variant="secondary" @click="fetchChart">重试</AppButton>
    </section>

    <!-- Indicators Grid -->
    <section class="card indicators-section" v-if="indicatorData && !loading">
      <div class="card-header">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">📋</span>
          最新指标值
        </h2>
      </div>
      <div class="indicators-grid">
        <div class="indicator-item" v-for="ind in indicatorItems" :key="ind.key">
          <span class="indicator-label">{{ ind.label }}</span>
          <span class="indicator-value" :class="ind.class">{{ ind.value }}</span>
        </div>
      </div>
    </section>

    <!-- Signal Card -->
    <section class="card signal-section" v-if="signal && !loading">
      <div class="card-header">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">🎯</span>
          综合信号
        </h2>
      </div>
      <div class="signal-content">
        <div class="signal-badge" :class="signal.signal" role="status" aria-live="polite">
          <span class="signal-icon" aria-hidden="true">{{ signalIcon }}</span>
          <span class="signal-text">{{ signalText }}</span>
        </div>
        <div class="signal-score">评分: <strong>{{ signal.score }}</strong></div>
        <ul class="signal-reasons" v-if="signal.reasons?.length">
          <li v-for="(r, i) in signal.reasons" :key="i">{{ r }}</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { usePortfolioStore } from '../stores/portfolio'
import { marketApi } from '../api'
import AppButton from './ui/AppButton.vue'
import AppSelect from './ui/AppSelect.vue'

use([CanvasRenderer, CandlestickChart, BarChart, LineChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent])

const store = usePortfolioStore()

// Allow a parent (e.g. the merged PortfolioAnalysis view) to drive the
// analyzed symbol. When selectedSymbol changes, the chart/indicators/signal
// for that holding are auto-loaded.
const props = defineProps({
  selectedSymbol: { type: String, default: '' },
})

// State
const selected = ref('')
const period = ref('daily')
const indicatorData = ref(null)
const signal = ref(null)
const loading = ref(false)
const etfs = ref([])
const etfInfoMap = ref({})
const chartMode = ref('kline')
const chartData = ref(null)
const chartHeight = ref(560)

const showMA5 = ref(true)
const showMA10 = ref(true)
const showMA20 = ref(true)
const showMA60 = ref(false)
const showBoll = ref(false)
const showMACD = ref(true)

// Period Options
const periodOptions = [
  { value: '15m', label: '15 分钟' },
  { value: '30m', label: '30 分钟' },
  { value: '1h', label: '1 小时' },
  { value: '4h', label: '4 小时' },
  { value: 'daily', label: '日线' },
  { value: 'weekly', label: '周线' },
  { value: 'monthly', label: '月线' }
]

// Indicator Toggles
const indicatorToggles = [
  { key: 'ma5', label: 'MA5', model: showMA5 },
  { key: 'ma10', label: 'MA10', model: showMA10 },
  { key: 'ma20', label: 'MA20', model: showMA20 },
  { key: 'ma60', label: 'MA60', model: showMA60 },
  { key: 'boll', label: '布林带', model: showBoll },
  { key: 'macd', label: 'MACD', model: showMACD }
]

// Computed
const etfOptions = computed(() => etfs.value.map(etf => ({
  value: etf.symbol,
  label: `${etf.name} (${etf.symbol})`
})))

const analyzingIndex = computed(() => {
  if (!selected.value) return null
  const info = etfInfoMap.value[selected.value]
  if (info && info.portfolio_type === 'off_exchange' && info.tracked_index) {
    return info.tracked_index + ' ' + info.name
  }
  return null
})

const signalText = computed(() => {
  const map = { buy: '买入', sell: '卖出', hold: '持有' }
  return map[signal.value?.signal] || ''
})

const signalIcon = computed(() => {
  const map = { buy: '⬆️', sell: '⬇️', hold: '➡️' }
  return map[signal.value?.signal] || ''
})

const indicatorItems = computed(() => {
  if (!indicatorData.value) return []
  const d = indicatorData.value
  return [
    { key: 'ma5', label: 'MA5', value: d.ma5?.toFixed(2) ?? '--', class: '' },
    { key: 'ma10', label: 'MA10', value: d.ma10?.toFixed(2) ?? '--', class: '' },
    { key: 'ma20', label: 'MA20', value: d.ma20?.toFixed(2) ?? '--', class: '' },
    { key: 'ma60', label: 'MA60', value: d.ma60?.toFixed(2) ?? '--', class: '' },
    { key: 'rsi', label: 'RSI(14)', value: d.rsi?.toFixed(2) ?? '--', class: getRSIClass(d.rsi) },
    { key: 'macd', label: 'MACD', value: d.macd?.macd?.toFixed(4) ?? '--', class: getMACDClass(d.macd?.macd) },
    { key: 'kdj', label: 'KDJ-K', value: d.kdj?.k?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-upper', label: 'BOLL上轨', value: d.bollinger?.upper?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-lower', label: 'BOLL下轨', value: d.bollinger?.lower?.toFixed(2) ?? '--', class: '' }
  ]
})

function getRSIClass(rsi) {
  if (rsi == null) return ''
  if (rsi >= 70) return 'text-danger'
  if (rsi <= 30) return 'text-success'
  return ''
}

function getMACDClass(macd) {
  if (macd == null) return ''
  return macd >= 0 ? 'text-success' : 'text-danger'
}

// Helpers
function getActiveSymbol() {
  const info = etfInfoMap.value[selected.value]
  if (info && info.portfolio_type === 'off_exchange' && info.tracked_index) {
    return info.tracked_index
  }
  return selected.value
}

function getActiveAssetType() {
  const info = etfInfoMap.value[selected.value]
  if (info && info.portfolio_type === 'off_exchange' && info.tracked_index) {
    return 'index'
  }
  return 'A'
}

function formatDate(d) {
  if (!d) return ''
  const s = String(d)
  if (s.length === 8) return s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8)
  return s
}

// Chart Option
const chartOption = computed(() => {
  const d = chartData.value
  if (!d || !d.dates.length) return {}

  // Guard: verify OHLC arrays exist before processing
  if (!d.opens || !d.closes || !d.lows || !d.highs) return {}

  const dates = d.dates.map(formatDate)

  // ── Intraday line chart ──
  if (chartMode.value === 'intraday') {
    const closePrices = d.closes
    const volumes = d.volumes || []
    const volumeColors = d.closes.map((c, i) => (i === 0 ? '#22c55e' : c >= d.closes[i - 1] ? '#22c55e' : '#ef4444'))
    const minP = Math.min(...d.lows)
    const maxP = Math.max(...d.highs)
    const basePrice = d.closes[0]

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params) => {
          const p = params[0]
          if (!p) return ''
          const idx = p.dataIndex
          const date = dates[idx] || ''
          const close = d.closes[idx]
          const change = ((close - basePrice) / basePrice * 100).toFixed(2)
          const vol = d.volumes[idx]
          return `<b>${date}</b><br/>收盘: ${close.toFixed(3)}<br/>涨跌幅: ${change >= 0 ? '+' : ''}${change}%<br/>成交量: ${vol || 0}`
        }
      },
      grid: [
        { left: '6%', right: '3%', top: 8, height: '60%' },
        { left: '6%', right: '3%', top: '72%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: true, rotate: 30, fontSize: 10 } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { gridIndex: 0, scale: true, splitNumber: 4 },
        { gridIndex: 1, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } }
      ],
      series: [
        {
          type: 'line', data: closePrices, xAxisIndex: 0, yAxisIndex: 0,
          name: selected.value,
          smooth: true, symbol: 'none',
          lineStyle: { width: 2, color: '#ef4444' },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239,68,68,0.3)' },
                { offset: 1, color: 'rgba(239,68,68,0.02)' },
              ],
            },
          },
          markLine: {
            silent: true,
            data: [{ yAxis: basePrice, label: { formatter: `开: ${basePrice.toFixed(3)}`, fontSize: 11 } }],
            lineStyle: { color: '#888', type: 'dashed', width: 1 },
          },
        },
        {
          type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
          name: '成交量', itemStyle: { color: (p) => volumeColors[p.dataIndex] },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      ],
    }
  }

  // ── K-line chart ──
  const candlesticks = d.opens.map((_, i) => [d.opens[i], d.closes[i], d.lows[i], d.highs[i]])
  const volumes = d.volumes || []
  const volumeColors = d.closes.map((c, i) => (i === 0 ? '#22c55e' : c >= d.closes[i - 1] ? '#22c55e' : '#ef4444'))

  const gridHeights = { main: 50, volume: 22, macd: 20 }
  let mainPct = gridHeights.main
  let volPct = showMACD.value ? gridHeights.volume : 0
  let macdPct = showMACD.value ? gridHeights.macd : 0
  const totalPct = mainPct + volPct + macdPct + 10

  const grids = [
    { left: '6%', right: '3%', top: 8, height: `${mainPct / totalPct * 100}%` },
  ]
  const xAxes = [{ type: 'category', data: dates, gridIndex: 0, axisLabel: { show: true, rotate: 30, fontSize: 10 } }]
  const yAxes = [{ gridIndex: 0, scale: true, splitNumber: 4 }]
  const series = []

  // Main candlestick
  series.push({
    type: 'candlestick', name: selected.value, data: candlesticks,
    xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: '#22c55e', color0: '#ef4444', borderColor: '#22c55e', borderColor0: '#ef4444' },
  })

  // MA lines
  const maConfig = [
    { key: 'ma5', show: showMA5.value, color: '#f59e0b', name: 'MA5' },
    { key: 'ma10', show: showMA10.value, color: '#3b82f6', name: 'MA10' },
    { key: 'ma20', show: showMA20.value, color: '#a855f7', name: 'MA20' },
    { key: 'ma60', show: showMA60.value, color: '#22c55e', name: 'MA60' },
  ]
  for (const cfg of maConfig) {
    if (!cfg.show) continue
    const arr = d[cfg.key] || []
    if (!arr.length) continue
    series.push({
      type: 'line', data: arr, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: cfg.name, symbol: 'none', lineStyle: { width: 1.2, color: cfg.color },
    })
  }

  // Bollinger bands
  if (showBoll.value && d.bollinger && d.bollinger.upper && d.bollinger.middle && d.bollinger.lower) {
    const boll = d.bollinger
    series.push({
      type: 'line', data: boll.upper, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: 'BOLL上轨', symbol: 'none', lineStyle: { width: 1, color: '#94a3b8' },
    })
    series.push({
      type: 'line', data: boll.middle, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: 'BOLL中轨', symbol: 'none', lineStyle: { width: 1.2, color: '#1e293b' },
    })
    series.push({
      type: 'line', data: boll.lower, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: 'BOLL下轨', symbol: 'none', lineStyle: { width: 1, color: '#94a3b8' },
    })
  }

  // Volume sub-chart
  if (showMACD.value) {
    volPct = gridHeights.volume
    const volOffset = mainPct
    grids.push({ left: '6%', right: '3%', top: `${volOffset / totalPct * 100}%`, height: `${volPct / totalPct * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } })
    yAxes.push({ gridIndex: 1, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    series.push({
      type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
      name: '成交量', itemStyle: { color: (p) => volumeColors[p.dataIndex] },
    })
  }

  // MACD sub-chart
  if (showMACD.value && d.macd && d.macd.histogram && d.macd.dif && d.macd.dea) {
    macdPct = gridHeights.macd
    const macdOffset = mainPct + volPct + 2
    grids.push({ left: '6%', right: '3%', top: `${macdOffset / totalPct * 100}%`, height: `${macdPct / totalPct * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: 2, axisLabel: { rotate: 30, fontSize: 10 } })
    yAxes.push({ gridIndex: 2, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    const histColors = d.macd.histogram.map(v => (v || 0) >= 0 ? '#22c55e' : '#ef4444')
    series.push({
      type: 'bar', data: d.macd.histogram, xAxisIndex: 2, yAxisIndex: 2,
      name: 'MACD', itemStyle: { color: (p) => histColors[p.dataIndex] },
    })
    series.push({
      type: 'line', data: d.macd.dif, smooth: true,
      xAxisIndex: 2, yAxisIndex: 2,
      name: 'DIF', symbol: 'none', lineStyle: { width: 1.2, color: '#3b82f6' },
    })
    series.push({
      type: 'line', data: d.macd.dea, smooth: true,
      xAxisIndex: 2, yAxisIndex: 2,
      name: 'DEA', symbol: 'none', lineStyle: { width: 1.2, color: '#f59e0b' },
    })
  }

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { show: true, top: 0, left: 'center', icon: 'roundRect', itemWidth: 12, itemHeight: 8 },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: xAxes.map((_, i) => i),
        start: 60,
        end: 100,
        zoomOnMouseWheel: false,
        moveOnMouseWheel: true,
        moveOnMouseMove: true,
      },
      {
        type: 'slider',
        xAxisIndex: xAxes.map((_, i) => i),
        bottom: 4,
        height: 18,
        start: 60,
        end: 100,
      },
    ],
    series,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
  }
})

// Methods
function onSelectEtf() {
  const info = etfInfoMap.value[selected.value]
  if (info && info.portfolio_type === 'off_exchange') {
    period.value = 'daily'
  }
  fetchChart()
}

async function fetchChart() {
  if (!selected.value) return
  loading.value = true
  const sym = getActiveSymbol()
  const assetType = getActiveAssetType()
  try {
    const [chartRes, indRes, sigRes] = await Promise.all([
      marketApi.chart(sym, assetType, period.value),
      marketApi.indicators(sym, assetType),
      marketApi.signal(sym, assetType),
    ])
    chartData.value = chartRes.data
    indicatorData.value = indRes.data
    signal.value = sigRes.data
  } catch {
    chartData.value = null
    indicatorData.value = null
    signal.value = null
  }
  loading.value = false
}

// Parent-driven selection (merged view)
watch(
  () => props.selectedSymbol,
  (sym) => {
    if (sym && etfInfoMap.value[sym]) {
      selected.value = sym
      fetchChart()
    }
  },
)

// Lifecycle
onMounted(async () => {
  try {
    await Promise.all([
      store.fetchEtfs('on_exchange'),
      store.fetchEtfs('off_exchange'),
    ])
    const allEtfs = [...store.onExchange, ...store.offExchange]
    etfs.value = allEtfs
    const map = {}
    for (const etf of allEtfs) {
      map[etf.symbol] = { portfolio_type: etf.portfolio_type, tracked_index: etf.tracked_index, name: etf.name }
    }
    etfInfoMap.value = map
  } catch {
    etfs.value = []
  }
  // Honor a parent-provided selection; otherwise default to the first ETF.
  const initial = props.selectedSymbol && etfInfoMap.value[props.selectedSymbol]
    ? props.selectedSymbol
    : (etfs.value[0]?.symbol || '')
  if (initial) { selected.value = initial; fetchChart() }
})
</script>

<style scoped>
/* ==========================================
   Analysis View Styles
   ========================================== */
.analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* Page Header */
.page-header { margin-bottom: var(--space-2); }
.page-title { font-size: var(--font-size-2xl); font-weight: var(--font-weight-bold); line-height: var(--line-height-tight); color: var(--color-text-primary); letter-spacing: var(--letter-spacing-tight); }
.page-description { margin-top: var(--space-1); font-size: var(--font-size-base); color: var(--color-text-secondary); line-height: var(--line-height-relaxed); }

/* Card */
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: hidden; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); flex-wrap: wrap; }
.card-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-title-icon { font-size: var(--font-size-xl); line-height: 1; }

/* Control Panel */
.control-panel { padding: var(--space-5); }
.control-row { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: flex-end; margin-bottom: var(--space-4); }
.control-group { display: flex; flex-direction: column; gap: var(--space-1.5); min-width: 0; }
.control-group--primary { flex: 1; min-width: 280px; }
.control-group--action { flex-shrink: 0; }
.control-group--info { flex: 1; min-width: 120px; margin-left: auto; }

.control-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.control-field { width: 100%; }

/* Index Badge */
.index-badge { display: inline-flex; align-items: center; gap: var(--space-1); padding: var(--space-1) var(--space-2); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-brand-700); background: var(--color-bg-brand-subtle); border-radius: var(--radius-full); }
.badge-icon { font-size: 10px; }

/* Chart Mode Toggle */
.chart-mode-toggle { display: inline-flex; background: var(--color-surface-tertiary); border-radius: var(--radius-md); padding: var(--space-1); gap: var(--space-1); }
.mode-btn { display: inline-flex; align-items: center; gap: var(--space-1.5); padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); border-radius: var(--radius-sm); background: transparent; border: none; cursor: pointer; transition: var(--transition-fast); }
.mode-btn:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.mode-btn--active { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.mode-btn:focus-visible { outline: none; box-shadow: var(--shadow-focus); }
.mode-icon { font-size: 12px; }

/* Indicator Toggles */
.indicator-toggles { padding-top: var(--space-4); border-top: 1px solid var(--color-border-light); margin-top: var(--space-4); }
.toggles-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); margin-right: var(--space-3); }
.toggles-grid { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.toggle-item { display: inline-flex; align-items: center; gap: var(--space-1.5); padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); color: var(--color-text-secondary); background: var(--color-surface-tertiary); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); user-select: none; }
.toggle-item:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.toggle-item:has(input:checked) { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.toggle-item input { width: 16px; height: 16px; accent-color: var(--color-brand-600); cursor: pointer; }
.toggle-name { font-weight: var(--font-weight-medium); }

/* Loading State */
.loading-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-12); gap: var(--space-4); color: var(--color-text-secondary); }
.loading-spinner { width: 40px; height: 40px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Chart Section */
.chart-section { padding: 0; min-height: 560px; }

/* Empty State */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-12) var(--space-6); text-align: center; }
.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); }

/* Indicators Section */
.indicators-section { padding: var(--space-5); }
.indicators-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-3); }
.indicator-item { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-3); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg); transition: var(--transition-fast); }
.indicator-item:hover { border-color: var(--color-brand-300); box-shadow: var(--shadow-md); transform: translateY(-1px); }
.indicator-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.indicator-value { font-family: var(--font-family-mono); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.indicator-value.text-success { color: var(--color-text-success); }
.indicator-value.text-danger { color: var(--color-text-danger); }

/* Signal Section */
.signal-section { padding: var(--space-5); }
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

/* Data Count */
.data-count { font-size: var(--font-size-sm); color: var(--color-text-tertiary); font-family: var(--font-family-mono); }

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .loading-spinner { animation: none; }
  * { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

/* Responsive */
@media (max-width: 768px) {
  .control-row { flex-direction: column; align-items: stretch; }
  .control-group--primary { min-width: 0; }
  .control-group--info { margin-left: 0; }
  .chart-mode-toggle { width: 100%; justify-content: center; }
  .toggles-grid { justify-content: center; }
  .indicators-grid { grid-template-columns: repeat(2, 1fr); }
  .signal-badge { font-size: var(--font-size-lg); padding: var(--space-2) var(--space-4); }
}

@media (max-width: 480px) {
  .indicators-grid { grid-template-columns: 1fr; }
  .control-group--action { width: 100%; }
  .control-group--action .btn { width: 100%; justify-content: center; }
}
</style>