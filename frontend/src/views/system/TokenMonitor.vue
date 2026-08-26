<template>
  <div class="token-monitor">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p>加载中...</p>
    </div>

    <!-- round35 FE2 (R127): 错误态——API 失败时不再渲染空统计冒充正常 -->
    <div v-else-if="loadError" class="loading-state" role="alert">
      <p class="error-title">⚠️ Token 用量加载失败</p>
      <p class="error-hint">监控端点不可达，请检查后端服务状态。</p>
      <button class="retry-btn" @click="fetchData">重试</button>
    </div>

    <template v-else>
      <!-- Stats Cards -->
      <section class="stats-grid" aria-label="概览统计">
        <div class="stat-card">
          <span class="stat-label">总调用次数</span>
          <span class="stat-value">{{ summary.total.calls }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">今日调用</span>
          <span class="stat-value">{{ summary.daily.calls }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">本月 Token</span>
          <span class="stat-value">{{ formatNumber(summary.daily.tokens) }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">错误率</span>
          <span class="stat-value" :class="{ 'text-danger': summary.total.error_rate > 5 }">
            {{ summary.total.error_rate }}%
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">预估费用 (¥)</span>
          <span class="stat-value">{{ estimatedCost.toFixed(2) }}</span>
        </div>
      </section>

      <!-- Tab: 日 / 月 -->
      <section class="card chart-section">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📈</span>
            Token 消耗趋势
          </h2>
          <AppTabs :tabs="granularityTabs" v-model="granularity" variant="soft" size="sm" class="granularity-tabs" />
        </div>
        <div class="card-body">
          <v-chart
            v-if="trendOption"
            :option="trendOption"
            :style="{ height: '360px' }"
            autoresize
          />
          <div v-else class="chart-empty">暂无数据</div>
        </div>
      </section>

      <!-- Per-function breakdown -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">🔧</span>
            各功能调用统计
          </h2>
        </div>
        <div class="card-body">
          <div v-if="functionList.length" class="func-table">
            <div class="func-table-header">
              <span class="func-col-name">功能</span>
              <span class="func-col-num">调用次数</span>
              <span class="func-col-num">Prompt</span>
              <span class="func-col-num">Completion</span>
              <span class="func-col-num">总 Token</span>
              <span class="func-col-num">平均耗时</span>
              <span class="func-col-num">错误</span>
            </div>
            <div
              v-for="fn in functionList"
              :key="fn.name"
              class="func-table-row"
            >
              <span class="func-col-name mono">{{ fn.name }}</span>
              <span class="func-col-num">{{ fn.calls }}</span>
              <span class="func-col-num">{{ formatNumber(fn.prompt_tokens) }}</span>
              <span class="func-col-num">{{ formatNumber(fn.completion_tokens) }}</span>
              <span class="func-col-num">{{ formatNumber(fn.total_tokens) }}</span>
              <span class="func-col-num">{{ fn.avg_duration_ms }}ms</span>
              <span class="func-col-num" :class="{ 'text-danger': fn.errors > 0 }">
                {{ fn.errors }}
              </span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无调用记录</div>
        </div>
      </section>

      <!-- Failed calls -->
      <section v-if="failures.length" class="card failure-card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">❌</span>
            最近失败记录
          </h2>
          <span class="failure-badge">{{ failures.length }} 条</span>
        </div>
        <div class="card-body failure-body">
          <div class="failure-table">
            <div class="failure-table-header">
              <span class="fail-col-time">时间</span>
              <span class="fail-col-func">功能</span>
              <span class="fail-col-dur">耗时</span>
              <span class="fail-col-msg">错误信息</span>
            </div>
            <div
              v-for="(f, i) in failures"
              :key="i"
              class="failure-table-row"
            >
              <span class="fail-col-time mono">{{ formatTime(f.timestamp) }}</span>
              <span class="fail-col-func mono">{{ f.function_name }}</span>
              <span class="fail-col-dur">{{ f.duration_ms }}ms</span>
              <div class="fail-col-msg-wrapper">
                <span class="fail-col-msg error-msg" :title="f.error_message">{{ f.error_message }}</span>
                <button
                  class="copy-btn"
                  @click="copyError(f.error_message)"
                  :aria-label="'复制错误信息'"
                  title="复制错误信息"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import AppTabs from '../../components/ui/AppTabs.vue'
import { adminApi } from '../../api'
import { useToastStore } from '../../stores/toast'
import logger from '../../utils/logger'
import { calcCost, modelCostFromBuckets } from '../../utils/pricing'

use([CanvasRenderer, LineChart, BarChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent])

const loading = ref(true)
const loadError = ref(false)  // round35 FE2 (R127)
const summary = ref({ total: {}, hourly: {}, daily: {}, by_function: {} })
const timeseries = ref([])
// R59: timeseries 窗口 total（与图表同一窗口/同一数据源）
const windowTotal = ref({})
const granularity = ref('day')
const granularityTabs = [
  { value: 'day', label: '按日' },
  { value: 'month', label: '按月' },
  { value: 'hour', label: '按小时' },
]
const failures = ref([])

async function fetchData() {
  loading.value = true
  loadError.value = false
  try {
    const tsParams = { granularity: granularity.value, days: 30, months: 12, hours: 48 }
    const [sumRes, tsRes, failRes] = await Promise.all([
      adminApi.tokenUsage(),
      adminApi.tokenTimeseries(tsParams),
      adminApi.tokenFailures(50),
    ])
    summary.value = sumRes.data
    timeseries.value = tsRes.data.series || []
    windowTotal.value = tsRes.data.total || {}
    failures.value = failRes.data.failures || []
  } catch (e) {
    logger.error('Failed to fetch token usage', e)
    loadError.value = true  // round35 FE2: 错误态而非空统计冒充
  } finally {
    loading.value = false
  }
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

watch(granularity, () => { fetchData() })

const functionList = computed(() => {
  const fn = summary.value.by_function || {}
  return Object.entries(fn)
    .map(([name, data]) => ({ name, ...data }))
    .sort((a, b) => b.total_tokens - a.total_tokens)
})

// R57/R59: 顶部预估费用 = timeseries 窗口 total 逐模型计价（同一窗口、同一数据源）
const estimatedCost = computed(() => {
  const bm = windowTotal.value?.by_model
  if (bm && Object.keys(bm).length) {
    return modelCostFromBuckets(bm)
  }
  // 老后端兼容：无 by_model → 总 token × flash 单价
  const total = windowTotal.value || {}
  return calcCost(total.prompt_tokens || 0, total.completion_tokens || 0, 'deepseek-v4-flash')
})

// R58: 每日费用系列（series 逐日 by_model 计价）
const costSeries = computed(() => {
  return timeseries.value.map(s => modelCostFromBuckets(s.by_model))
})

const trendOption = computed(() => {
  const series = timeseries.value
  if (!series.length) return null

  const dates = series.map(s => s.date)
  const maxTokens = Math.max(...series.map(s => s.total_tokens), 1)

  return {
    legend: {
      data: ['总 Token', '调用次数', '费用(¥)'],
      top: 0,
    },
    grid: {
      left: '3%',
      right: '12%',
      bottom: '3%',
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      // R58: 三行（Token / 调用 / 费用）
      formatter: (params) => {
        const list = Array.isArray(params) ? params : [params]
        const first = list[0]
        if (!first) return ''
        const i = first.dataIndex
        const calls = series[i]?.calls ?? 0
        const cost = costSeries.value[i] ?? 0
        return `${first.axisValue}<br/>总 Token: ${first.data}<br/>调用次数: ${calls}<br/>费用: ¥${cost.toFixed(2)}`
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        rotate: granularity.value === 'hour' ? 60 : (granularity.value === 'day' ? 45 : 0),
        fontSize: 10,
        interval: granularity.value === 'hour' ? 3 : 0,
        formatter: granularity.value === 'hour'
          ? (v) => v.slice(5)  // "07-14 09:00"
          : (v) => v,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: 'Token 数',
        min: 0,
        max: maxTokens * 1.15,
      },
      {
        type: 'value',
        name: '调用次数',
        min: 0,
      },
      {
        // R58: 第三轴——费用（¥），避免被 Token 量级压制
        type: 'value',
        name: '费用(¥)',
        min: 0,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '总 Token',
        type: 'bar',
        data: series.map(s => s.total_tokens),
        itemStyle: {
          color: '#3b82f6',
          borderRadius: [4, 4, 0, 0],
        },
        barMaxWidth: 40,
      },
      {
        name: '调用次数',
        type: 'line',
        yAxisIndex: 1,
        data: series.map(s => s.calls),
        lineStyle: { color: '#f59e0b', width: 2 },
        itemStyle: { color: '#f59e0b' },
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
      },
      {
        // R58: 费用折线（绿色，第三轴）
        name: '费用(¥)',
        type: 'line',
        yAxisIndex: 2,
        data: costSeries.value,
        lineStyle: { color: '#10b981', width: 2 },
        itemStyle: { color: '#10b981' },
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
    color: ['#3b82f6', '#f59e0b', '#10b981'],
  }
})

function formatNumber(n) {
  if (n == null) return '0'
  return n.toLocaleString()
}

function copyError(msg) {
  const toast = useToastStore()
  navigator.clipboard.writeText(msg).then(() => {
    toast.show('已复制到剪贴板', 'success')
  }).catch(() => {
    toast.show('复制失败', 'error')
  })
}

onMounted(fetchData)
</script>

<style scoped>
.token-monitor {
  max-width: 1400px /* O17: 1100→1400 铺满 */;
  margin: 0 auto;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.stat-card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  box-shadow: var(--shadow-sm);
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.stat-value {
  font: var(--text-h2);
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}

/* Card */
.card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  margin-bottom: var(--space-6);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font: var(--text-h4);
  color: var(--color-text-primary);
  margin: 0;
}

.card-title-icon {
  font-size: var(--font-size-xl);
  line-height: 1;
}

.card-body {
  padding: var(--space-5);
}

/* Tabs */
.tab-group {
  display: flex;
  gap: var(--space-1);
  background: var(--color-surface-secondary);
  padding: 3px;
  border-radius: var(--radius-lg);
}

.tab-btn {
  padding: var(--space-1) var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font: var(--text-body-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn--active {
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  box-shadow: var(--shadow-sm);
}

/* Chart */
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* Function Table */
.func-table {
  display: flex;
  flex-direction: column;
}

.func-table-header,
.func-table-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr 1fr 0.6fr;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-2);
  align-items: center;
}

.func-table-header {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border-light);
}

.func-table-row {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  border-bottom: 1px solid var(--color-border-lighter);
}

.func-table-row:last-child {
  border-bottom: none;
}

.func-col-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.func-col-name.mono {
  font-family: ui-monospace, monospace;
  font-size: var(--font-size-xs);
}

.func-col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* Loading */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10);
  gap: var(--space-4);
  color: var(--color-text-tertiary);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-brand-500);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* round35 FE2 (R127): 错误态 */
.error-title {
  font: var(--text-body-strong);
  color: var(--color-text-primary);
}
.error-hint {
  color: var(--color-text-tertiary);
}
.retry-btn {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
  cursor: pointer;
}
.retry-btn:hover {
  background: var(--color-bg-subtle, rgba(0, 0, 0, 0.04));
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.text-danger {
  color: var(--color-danger-500);
}

/* Failure Card */
.failure-card {
  border-color: var(--color-danger-200);
}

.failure-badge {
  font-size: var(--font-size-sm);
  color: var(--color-danger-600);
  background: var(--color-danger-50);
  padding: 2px var(--space-3);
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-medium);
}

.failure-body {
  padding: 0;
}

.failure-table {
  display: flex;
  flex-direction: column;
}

.failure-table-header,
.failure-table-row {
  display: grid;
  grid-template-columns: 140px 180px 70px 1fr;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  align-items: center;
}

.failure-table-header {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
}

.failure-table-row {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  border-bottom: 1px solid var(--color-border-lighter);
}

.failure-table-row:last-child {
  border-bottom: none;
}

.failure-table-row:hover {
  background: var(--color-surface-secondary);
}

.fail-col-time,
.fail-col-func {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fail-col-dur {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-secondary);
}

.fail-col-msg {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-msg {
  color: var(--color-danger-600);
  font-family: ui-monospace, monospace;
  font-size: var(--font-size-xs);
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: var(--font-size-xs);
}
</style>


