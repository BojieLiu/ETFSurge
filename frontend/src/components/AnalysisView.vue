<template>
  <div class="analysis">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">技术分析</h1>
      <p class="page-description">多周期 K 线、分时图、技术指标与综合买卖信号</p>
    </header>

    <!-- Control Panel -->
    <ControlPanel
      :selected="selected"
      :period="period"
      :chart-mode="chartMode"
      :chart-data="chartData"
      :etf-options="etfOptions"
      :period-options="periodOptions"
      :indicator-toggles="indicatorToggles"
      @update:selected="onSelectEtf"
      @update:period="period = $event"
      @update:chart-mode="chartMode = $event"
      @refresh="fetchChart"
    />

    <!-- Chart -->
    <ChartPanel :chart-option="chartOption" :loading="loading" />

    <!-- Empty State -->
    <section class="card empty-state" v-if="!chartData && !loading && selected">
      <div class="empty-icon" aria-hidden="true">📊</div>
      <h3 class="empty-title">暂无图表数据</h3>
      <p class="empty-description">请尝试切换周期或稍后刷新</p>
      <AppButton variant="secondary" @click="fetchChart">重试</AppButton>
    </section>

    <!-- Signal Panel (indicators + signal) -->
    <SignalPanel :indicator-data="indicatorData" :signal="signal" :loading="loading" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { usePortfolioStore } from '../stores/portfolio'
import { marketApi } from '../api'
import AppButton from './ui/AppButton.vue'
import { chartColor, CHART_COLORS, CANDLE_UP, CANDLE_DOWN, histogramColor } from '../utils/chartColors'

import ControlPanel from './analysis/ControlPanel.vue'
import ChartPanel from './analysis/ChartPanel.vue'
import SignalPanel from './analysis/SignalPanel.vue'

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

const showMA5 = ref(true)
const showMA10 = ref(true)
const showMA20 = ref(true)
const showMA60 = ref(false)
const showBoll = ref(false)
const showMACD = ref(true)
const showKDJ = ref(false)
const showRSI = ref(false)

// Period Options
const periodOptions = [
  { value: '1m', label: '1 分钟' },
  { value: '5m', label: '5 分钟' },
  { value: '15m', label: '15 分钟' },
  { value: '30m', label: '30 分钟' },
  { value: '1h', label: '1 小时' },
  { value: '4h', label: '4 小时' },
  { value: 'daily', label: '日线' },
  { value: 'weekly', label: '周线' },
  { value: 'monthly', label: '月线' },
]

// Indicator Toggles
const indicatorToggles = [
  { key: 'ma5', label: 'MA5', model: showMA5 },
  { key: 'ma10', label: 'MA10', model: showMA10 },
  { key: 'ma20', label: 'MA20', model: showMA20 },
  { key: 'ma60', label: 'MA60', model: showMA60 },
  { key: 'boll', label: '布林带', model: showBoll },
  { key: 'macd', label: 'MACD', model: showMACD },
  { key: 'kdj', label: 'KDJ', model: showKDJ },
  { key: 'rsi', label: 'RSI', model: showRSI },
]

// Computed
const etfOptions = computed(() =>
  etfs.value.map((etf) => ({
    value: etf.symbol,
    label: `${etf.name} (${etf.symbol})`,
  }))
)

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

  const etfInfo = etfInfoMap.value[selected.value]
  const seriesName = etfInfo?.name ? `${etfInfo.name} (${selected.value})` : selected.value

  // ── Intraday line chart ──
  if (chartMode.value === 'intraday') {
    const closePrices = d.closes
    const volumes = d.volumes || []
    const volumeColors = d.closes.map((c, i) =>
      i === 0 ? CANDLE_DOWN : c >= d.closes[i - 1] ? CANDLE_DOWN : CANDLE_UP
    )
    const minP = Math.min(...d.lows)
    const maxP = Math.max(...d.highs)
    const basePrice = d.closes[0]

    return {
      title: { text: seriesName, left: 'center', textStyle: { fontSize: 14, fontWeight: 'bold' } },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params) => {
          const p = params[0]
          if (!p) return ''
          const idx = p.dataIndex
          const date = dates[idx] || ''
          const close = d.closes[idx]
          const vol = d.volumes ? d.volumes[idx] : 0
          const open = d.opens ? d.opens[idx] : 0
          const high = d.highs ? d.highs[idx] : 0
          const low = d.lows ? d.lows[idx] : 0
          const volFormatted = vol >= 100000000 ? (vol / 100000000).toFixed(2) + '亿' : vol >= 10000 ? (vol / 10000).toFixed(2) + '万' : vol.toLocaleString()
          const change = ((close - basePrice) / basePrice * 100).toFixed(2)
          return `<b>${date}</b><br/>开: ${open.toFixed(3)} 高: ${high.toFixed(3)} 低: ${low.toFixed(3)} 收: ${close.toFixed(3)}<br/>涨跌幅: ${change >= 0 ? '+' : ''}${change}%<br/>成交量: ${volFormatted}`
        },
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
        { gridIndex: 1, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } },
      ],
      series: [
        {
          type: 'line', data: closePrices, xAxisIndex: 0, yAxisIndex: 0,
          name: seriesName,
          smooth: true, symbol: 'none',
          lineStyle: { width: 2, color: CANDLE_UP },
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
  const volumeColors = d.closes.map((c, i) =>
    i === 0 ? CANDLE_DOWN : c >= d.closes[i - 1] ? CANDLE_DOWN : CANDLE_UP
  )

  const gridHeights = { main: 50, volume: 22, macd: 20, kdj: 18, rsi: 18 }
  const mainPct = gridHeights.main
  let volPct = showMACD.value ? gridHeights.volume : 0
  let macdPct = showMACD.value ? gridHeights.macd : 0
  let kdjPct = showKDJ.value && d.kdj ? gridHeights.kdj : 0
  let rsiPct = showRSI.value && d.rsi ? gridHeights.rsi : 0
  const totalPct = mainPct + volPct + macdPct + kdjPct + rsiPct + 10

  const grids = [
    { left: '6%', right: '3%', top: 8, height: `${(mainPct / totalPct) * 100}%` },
  ]
  const xAxes = [{ type: 'category', data: dates, gridIndex: 0, axisLabel: { show: true, rotate: 30, fontSize: 10 } }]
  const yAxes = [{ gridIndex: 0, scale: true, splitNumber: 4 }]
  const series = []

  // Main candlestick
  series.push({
    type: 'candlestick', name: seriesName, data: candlesticks,
    xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: CANDLE_DOWN, color0: CANDLE_UP, borderColor: CANDLE_DOWN, borderColor0: CANDLE_UP },
  })

  // MA lines
  const maConfig = [
    { key: 'ma5', show: showMA5.value, color: chartColor('ma5'), name: 'MA5' },
    { key: 'ma10', show: showMA10.value, color: chartColor('ma10'), name: 'MA10' },
    { key: 'ma20', show: showMA20.value, color: chartColor('ma20'), name: 'MA20' },
    { key: 'ma60', show: showMA60.value, color: chartColor('ma60'), name: 'MA60' },
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
      name: 'BOLL上轨', symbol: 'none', lineStyle: { width: 1, color: chartColor('bollUpper') },
    })
    series.push({
      type: 'line', data: boll.middle, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: 'BOLL中轨', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('bollMiddle') },
    })
    series.push({
      type: 'line', data: boll.lower, smooth: true,
      xAxisIndex: 0, yAxisIndex: 0,
      name: 'BOLL下轨', symbol: 'none', lineStyle: { width: 1, color: chartColor('bollLower') },
    })
  }

  // Volume sub-chart
  if (showMACD.value) {
    volPct = gridHeights.volume
    const volOffset = mainPct
    grids.push({ left: '6%', right: '3%', top: `${(volOffset / totalPct) * 100}%`, height: `${(volPct / totalPct) * 100}%` })
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
    grids.push({ left: '6%', right: '3%', top: `${(macdOffset / totalPct) * 100}%`, height: `${(macdPct / totalPct) * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: 2, axisLabel: { rotate: 30, fontSize: 10 } })
    yAxes.push({ gridIndex: 2, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    const histColors = d.macd.histogram.map((v) => histogramColor(v))
    series.push({
      type: 'bar', data: d.macd.histogram, xAxisIndex: 2, yAxisIndex: 2,
      name: 'MACD', itemStyle: { color: (p) => histColors[p.dataIndex] },
    })
    series.push({
      type: 'line', data: d.macd.dif, smooth: true,
      xAxisIndex: 2, yAxisIndex: 2,
      name: 'DIF', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('macdDif') },
    })
    series.push({
      type: 'line', data: d.macd.dea, smooth: true,
      xAxisIndex: 2, yAxisIndex: 2,
      name: 'DEA', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('macdDea') },
    })
  }

  // KDJ sub-chart
  if (showKDJ.value && d.kdj && d.kdj.k && d.kdj.d && d.kdj.j) {
    kdjPct = gridHeights.kdj
    const kdjOffset = mainPct + volPct + (showMACD.value ? macdPct : 0) + 2
    const kdjGridIdx = grids.length
    grids.push({ left: '6%', right: '3%', top: `${(kdjOffset / totalPct) * 100}%`, height: `${(kdjPct / totalPct) * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: kdjGridIdx, axisLabel: { show: false } })
    yAxes.push({ gridIndex: kdjGridIdx, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 } })
    series.push({
      type: 'line', data: d.kdj.k, smooth: true,
      xAxisIndex: kdjGridIdx, yAxisIndex: kdjGridIdx,
      name: 'KDJ-K', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('kdjK') },
    })
    series.push({
      type: 'line', data: d.kdj.d, smooth: true,
      xAxisIndex: kdjGridIdx, yAxisIndex: kdjGridIdx,
      name: 'KDJ-D', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('kdjD') },
    })
    series.push({
      type: 'line', data: d.kdj.j, smooth: true,
      xAxisIndex: kdjGridIdx, yAxisIndex: kdjGridIdx,
      name: 'KDJ-J', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('kdjJ') },
    })
  }

  // RSI sub-chart
  if (showRSI.value && d.rsi) {
    rsiPct = gridHeights.rsi
    const rsiOffset = mainPct + volPct + (showMACD.value ? macdPct : 0) + (showKDJ.value && d.kdj ? kdjPct : 0) + 2
    const rsiGridIdx = grids.length
    grids.push({ left: '6%', right: '3%', top: `${(rsiOffset / totalPct) * 100}%`, height: `${(rsiPct / totalPct) * 100}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: rsiGridIdx, axisLabel: { show: false } })
    yAxes.push({ gridIndex: rsiGridIdx, scale: true, splitNumber: 3, axisLabel: { show: true, fontSize: 10 }, min: 0, max: 100 })
    series.push({
      type: 'line', data: d.rsi, smooth: true,
      xAxisIndex: rsiGridIdx, yAxisIndex: rsiGridIdx,
      name: 'RSI(14)', symbol: 'none', lineStyle: { width: 1.2, color: chartColor('rsi') },
      markLine: {
        silent: true,
        data: [
          { yAxis: 70, label: { formatter: '70 超买', fontSize: 10, color: CANDLE_UP }, lineStyle: { color: CANDLE_UP, type: 'dashed', width: 1 } },
          { yAxis: 30, label: { formatter: '30 超卖', fontSize: 10, color: CANDLE_DOWN }, lineStyle: { color: CANDLE_DOWN, type: 'dashed', width: 1 } },
        ],
      },
    })
  }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const p = params[0]
        if (!p) return ''
        const idx = p.dataIndex
        const date = dates[idx] || ''
        const open = d.opens[idx]
        const close = d.closes[idx]
        const high = d.highs[idx]
        const low = d.lows[idx]
        return `<b>${date}</b><br/>开: ${open != null ? open.toFixed(3) : '—'}<br/>收: ${close != null ? close.toFixed(3) : '—'}<br/>高: ${high != null ? high.toFixed(3) : '—'}<br/>低: ${low != null ? low.toFixed(3) : '—'}`
      },
    },
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
  }
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
  const initial =
    props.selectedSymbol && etfInfoMap.value[props.selectedSymbol]
      ? props.selectedSymbol
      : etfs.value[0]?.symbol || ''
  if (initial) {
    selected.value = initial
    fetchChart()
  }
})
</script>

<style scoped>
/* ==========================================
   Analysis View Container Styles
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

/* Card (empty state) */
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: hidden; }

/* Empty State */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-12) var(--space-6); text-align: center; }
.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); }
</style>
