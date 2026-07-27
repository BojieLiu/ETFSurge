<template>
  <section class="card factor-model">
    <div class="card-header">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">🧮</span>
        因子模型概览
      </h2>
    </div>

    <div class="model-body">
      <!-- Loading -->
      <div v-if="loading" class="loading-container">
        <div class="loading-spinner" aria-hidden="true"></div>
        <p>因子数据加载中...</p>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="error-container">
        <p>加载失败: {{ error }}</p>
        <button class="btn btn-sm btn-primary" @click="fetchData">重试</button>
      </div>

      <template v-else>
        <!-- Stats Overview Row -->
        <div class="stats-row">
          <div class="stat-item">
            <span class="stat-num">{{ data?.total ?? 0 }}</span>
            <span class="stat-lbl">已接入</span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-up">{{ summary?.valid ?? 0 }}</span>
            <span class="stat-lbl">有效</span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-warn">{{ summary?.warn ?? 0 }}</span>
            <span class="stat-lbl">低于阈值</span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-muted">{{ summary?.no_data ?? 0 }}</span>
            <span class="stat-lbl">无数据</span>
          </div>
          <div class="stat-item">
            <span class="stat-num" :class="avgIcClass">{{ formattedAvgIc }}</span>
            <span class="stat-lbl">平均 |IC|</span>
          </div>
        </div>

        <!-- Expandable Category Cards -->
        <div v-for="cat in categories" :key="cat.name" class="category-card">
          <div class="cat-header" @click="toggleCategory(cat.name)" role="button" tabindex="0" @keydown.enter="toggleCategory(cat.name)">
            <span class="cat-expand" :class="{ expanded: expanded[cat.name] }">▸</span>
            <span class="cat-name">{{ catLabel(cat.name) }}</span>
            <span class="cat-count-badge">{{ cat.count }} 因子</span>
            <span class="cat-stats-detail">
              <span class="cat-stat valid">{{ cat.valid_count }} 有效</span>
              <span v-if="cat.warn_count > 0" class="cat-stat warn">⚠️ {{ cat.warn_count }}</span>
              <span v-if="cat.no_data_count > 0" class="cat-stat no-data">{{ cat.no_data_count }} 无数据</span>
            </span>
            <span v-if="cat.avg_ic !== null" class="cat-avg-ic" :class="avgIcColor(cat.avg_ic)">
              IC {{ cat.avg_ic.toFixed(4) }}
            </span>
          </div>

          <Transition name="expand">
            <div v-show="expanded[cat.name]" class="cat-body">
              <!-- Factor Table Header -->
              <div class="factor-row factor-header">
                <span class="factor-name">因子名称</span>
                <span class="factor-ic-bar-col">IC 强度</span>
                <span class="factor-ic-val">IC 值</span>
                <span class="factor-desc">简介</span>
              </div>
              <!-- Factor Rows -->
              <div
                v-for="f in cat.factors"
                :key="f.code"
                class="factor-row"
              >
                <span class="factor-name">
                  <AppTooltip placement="right" :disabled="!f.description">
                    <span class="factor-name-text">{{ f.name }}</span>
                    <template #content>
                      <div class="tooltip-rich">
                        <div class="tip-title">{{ f.name }}</div>
                        <div class="tip-code">{{ f.code }}</div>
                        <div v-if="f.description" class="tip-desc">{{ f.description }}</div>
                        <div class="tip-meta">
                          <span class="tip-meta-item">标准化: {{ f.standardization }}</span>
                          <span class="tip-meta-item">IC 阈值: {{ f.ic_threshold }}</span>
                        </div>
                        <div class="tip-ic">
                          当前 IC:
                          <strong :class="icColorClass(f.ic_value)">
                            {{ f.ic_value !== null ? f.ic_value.toFixed(4) : '无数据' }}
                          </strong>
                          <span v-if="f.ic_value !== null" class="tip-status" :class="icStatusClass(f)">
                            {{ abs(f.ic_value) >= (f.ic_threshold || 0.02) ? '✅ 有效' : '⚠️ 低于阈值' }}
                          </span>
                        </div>
                      </div>
                    </template>
                  </AppTooltip>
                </span>
                <span class="factor-ic-bar-col">
                  <span class="ic-bar-track">
                    <span
                      v-if="f.ic_value !== null"
                      class="ic-bar-fill"
                      :class="f.ic_value >= 0 ? 'ic-pos' : 'ic-neg'"
                      :style="{ width: icBarWidth(f.ic_value) }"
                    ></span>
                  </span>
                </span>
                <span class="factor-ic-val" :class="icColorClass(f.ic_value)">
                  {{ f.ic_value !== null ? f.ic_value.toFixed(4) : '--' }}
                </span>
                <span class="factor-desc" :title="f.description">{{ truncate(f.description, 24) }}</span>
              </div>
              <div v-if="!cat.factors.length" class="factor-empty">该分类暂无已接入因子</div>
            </div>
          </Transition>
        </div>

        <!-- IC Bar Chart -->
        <div class="ic-chart-section">
          <h3 class="ic-chart-title">因子 IC 表现</h3>
          <div ref="chartRef" class="ic-chart-container"></div>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { factorsApi } from '../api'
import AppTooltip from './ui/AppTooltip.vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, TooltipComponent } from 'echarts/components'

echarts.use([BarChart, CanvasRenderer, GridComponent, TooltipComponent])

/* ── State ── */
const loading = ref(false)
const error = ref('')
const data = ref(null)
const expanded = ref({})
const chartRef = ref(null)
let chartInstance = null

/* ── Derived ── */
const summary = computed(() => data.value?.summary ?? null)
const categories = computed(() => data.value?.categories ?? [])

const formattedAvgIc = computed(() => {
  const v = summary.value?.avg_ic
  return v !== null && v !== undefined ? v.toFixed(4) : '--'
})
const avgIcClass = computed(() => {
  const v = summary.value?.avg_ic
  if (v === null || v === undefined) return ''
  return v >= 0.03 ? 'text-up' : v >= 0.02 ? '' : 'text-warn'
})

/* ── Helpers ── */
const abs = Math.abs

function catLabel(name) {
  const labels = {
    technical: '技术指标', style: '风格因子', sentiment: '情绪因子',
    etf_specific: 'ETF 因子', china_specific: '政策因子',
    momentum: '动量因子', valuation: '估值因子',
  }
  return labels[name] || name
}

function icBarWidth(val) {
  if (val === null || val === undefined) return '0px'
  const pct = Math.min(Math.abs(val) * 800, 100)
  return `${Math.max(pct, 4)}%`
}

function icColorClass(val) {
  if (val === null || val === undefined) return ''
  return val >= 0 ? 'text-up' : 'text-down'
}

function icStatusClass(f) {
  if (f.ic_value === null) return ''
  return abs(f.ic_value) >= (f.ic_threshold || 0.02) ? 'status-ok' : 'status-warn'
}

function avgIcColor(val) {
  if (val === null || val === undefined) return ''
  return val >= 0.03 ? 'text-up' : val >= 0.02 ? '' : 'text-warn'
}

function truncate(s, max) {
  if (!s) return ''
  return s.length > max ? s.slice(0, max) + '...' : s
}

/* ── Accordion ── */
function toggleCategory(name) {
  expanded.value[name] = !expanded.value[name]
}

/* ── Chart ── */
function renderChart() {
  if (!chartRef.value) return

  // Collect all factors with IC values, sort by |IC| desc, take top 15
  const allFactors = categories.value.flatMap(c => c.factors || [])
  const withIc = allFactors.filter(f => f.ic_value !== null)
  if (!withIc.length) {
    chartRef.value.style.display = 'none'
    return
  }
  chartRef.value.style.display = ''

  const sorted = [...withIc]
    .sort((a, b) => abs(b.ic_value) - abs(a.ic_value))
    .slice(0, 15)
    .reverse()

  const names = sorted.map(f => {
    const n = f.name || f.code.split('.').pop()
    return n.length > 14 ? n.slice(0, 12) + '...' : n
  })
  const values = sorted.map(f => f.ic_value)
  const colors = values.map(v => v >= 0 ? '#ef4444' : '#22c55e')

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        const idx = sorted.length - 1 - p.dataIndex
        const item = sorted[idx]
        return `<strong>${item.name || item.code}</strong><br/>类别: ${catLabel(item.category || '')}<br/>IC: <strong>${item.ic_value.toFixed(4)}</strong>`
      },
    },
    grid: { left: '3%', right: '8%', top: '3%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, formatter: (v) => v.toFixed(2) },
      splitLine: { lineStyle: { type: 'dashed', color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { fontSize: 11, width: 100, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      barMaxWidth: 16,
      label: {
        show: true,
        position: 'right',
        fontSize: 11,
        formatter: (p) => abs(p.value).toFixed(4),
      },
    }],
  }

  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(option)
}

function handleResize() {
  chartInstance?.resize()
}

/* ── Data ── */
async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const resp = await factorsApi.getActive()
    data.value = resp.data
    // Default: expand first category
    if (resp.data?.categories?.length) {
      expanded.value[resp.data.categories[0].name] = true
    }
  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.factor-model { overflow: visible; }
.model-body { padding: var(--space-5); }

/* Loading / Error */
.loading-container, .error-container {
  display: flex; flex-direction: column; align-items: center; gap: var(--space-3);
  padding: var(--space-8); color: var(--color-text-secondary);
}
.loading-spinner {
  width: 28px; height: 28px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-brand-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Stats Row */
.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.stat-item {
  display: flex; flex-direction: column; align-items: center;
  gap: var(--space-1); padding: var(--space-3);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg);
}
.stat-num { font-size: var(--font-size-xl); font-weight: var(--font-weight-bold); color: var(--color-text-primary); }
.stat-lbl { font-size: var(--font-size-xs); color: var(--color-text-secondary); }

/* Category Card */
.category-card {
  margin-bottom: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.cat-header {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-secondary);
  cursor: pointer;
  user-select: none;
  transition: background var(--transition-fast);
}
.cat-header:hover { background: var(--color-surface-hover); }
.cat-expand {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.cat-expand.expanded { transform: rotate(90deg); }
.cat-name { font-weight: var(--font-weight-semibold); color: var(--color-text-primary); flex-shrink: 0; }
.cat-count-badge {
  font-size: var(--font-size-xs); color: var(--color-brand-600);
  background: var(--color-brand-50); padding: 0.1rem 0.5rem;
  border-radius: var(--radius-full); flex-shrink: 0;
}
.cat-stats-detail { display: flex; gap: var(--space-2); flex: 1; }
.cat-stat { font-size: var(--font-size-xs); }
.cat-stat.valid { color: var(--color-success-600); }
.cat-stat.warn { color: var(--color-warning-600); }
.cat-stat.no-data { color: var(--color-text-tertiary); }
.cat-avg-ic { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); flex-shrink: 0; }

/* Expand transition */
.expand-enter-active, .expand-leave-active {
  transition: max-height 0.25s ease, opacity 0.2s ease;
  max-height: 2000px; overflow: hidden;
}
.expand-enter-from, .expand-leave-to {
  max-height: 0; opacity: 0;
}

/* Factor Rows */
.cat-body { border-top: 1px solid var(--color-border-light); }
.factor-row {
  display: grid;
  grid-template-columns: 140px 100px 80px 1fr;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-sm);
  align-items: center;
  transition: background var(--transition-fast);
}
.factor-row:hover { background: var(--color-surface-hover); }
.factor-header {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  background: var(--color-surface-primary);
  border-bottom: 1px solid var(--color-border-light);
  font-weight: var(--font-weight-medium);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.factor-name-text {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  cursor: help;
  border-bottom: 1px dashed var(--color-border-medium);
}

/* IC Bar */
.factor-ic-bar-col { display: flex; align-items: center; }
.ic-bar-track {
  width: 80px; height: 8px;
  background: var(--color-neutral-200);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.ic-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}
.ic-bar-fill.ic-pos { background: #ef4444; }
.ic-bar-fill.ic-neg { background: #22c55e; }

.factor-ic-val { font-family: monospace; font-size: var(--font-size-xs); text-align: right; }
.factor-desc {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.factor-empty {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* Tooltip Rich Content */
.tooltip-rich {
  min-width: 200px;
  line-height: var(--line-height-normal);
}
.tip-title { font-weight: var(--font-weight-bold); margin-bottom: var(--space-1); }
.tip-code { font-size: var(--font-size-xs); color: var(--color-text-tertiary); margin-bottom: var(--space-1); font-family: monospace; }
.tip-desc { font-size: var(--font-size-sm); margin-bottom: var(--space-2); color: var(--color-text-secondary); }
.tip-meta { display: flex; gap: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); margin-bottom: var(--space-1); }
.tip-meta-item { white-space: nowrap; }
.tip-ic { font-size: var(--font-size-sm); padding-top: var(--space-1); border-top: 1px solid var(--color-border-light); }
.tip-status { margin-left: var(--space-2); font-size: var(--font-size-xs); }
.tip-status.status-ok { color: var(--color-success-600); }
.tip-status.status-warn { color: var(--color-warning-600); }

/* IC Chart Section */
.ic-chart-section {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
}
.ic-chart-title {
  margin: 0 0 var(--space-3);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.ic-chart-container {
  width: 100%; height: 280px;
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg);
}

/* Colors */
.text-up { color: #ef4444; }
.text-down { color: #22c55e; }
.text-warn { color: #f59e0b; }
.text-muted { color: var(--color-text-tertiary); }

/* Responsive */
@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(3, 1fr); }
  .factor-row { grid-template-columns: 100px 60px 70px 1fr; }
  .cat-stats-detail { display: none; }
  .ic-chart-container { height: 200px; }
}

.btn { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); padding: 0.5rem 1rem; font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); border: 1px solid transparent; }
.btn-primary { background: var(--color-brand-500); color: #fff; border-color: var(--color-brand-500); }
.btn-primary:hover { background: var(--color-brand-600); }
.btn-sm { padding: 0.3rem 0.6rem; font-size: 0.8rem; }
</style>
