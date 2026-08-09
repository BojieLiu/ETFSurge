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
          <div class="stat-item stat-item-primary">
            <span class="stat-num stat-num-brand">{{ data?.total ?? 0 }}</span>
            <span class="stat-lbl">已接入</span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-up">{{ summary?.valid ?? 0 }}</span>
            <span class="stat-lbl">
              <span class="stat-icon stat-icon-valid" aria-hidden="true">✓</span>
              有效
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-warn">{{ summary?.warn ?? 0 }}</span>
            <span class="stat-lbl">
              <span class="stat-icon stat-icon-warn" aria-hidden="true">⚠</span>
              低于阈值
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-num text-muted">{{ summary?.no_data ?? 0 }}</span>
            <span class="stat-lbl">无数据</span>
          </div>
          <div class="stat-item">
            <span class="stat-num stat-num-static">{{ summary?.static ?? 0 }}</span>
            <span class="stat-lbl">
              <AppTooltip placement="top">
                <span class="stat-icon stat-icon-static" aria-hidden="true">🔒</span>
                静态标识
                <template #content>
                  <div class="tooltip-rich">静态标识因子（如政策哑变量）不参与 IC 统计，非数据缺失</div>
                </template>
              </AppTooltip>
            </span>
          </div>
          <div class="stat-item">
            <span class="stat-num" :class="avgIcClass">{{ formattedAvgIc }}</span>
            <span class="stat-lbl">平均 |IC|</span>
          </div>
        </div>

        <!-- IC Sort Table (P2-1: merged from FactorICView.vue) -->
        <div class="card ic-sort-card">
          <div class="card-header ic-sort-header">
            <h3 class="card-title">
              <span class="card-title-icon" aria-hidden="true">🔍</span>
              因子 IC 排序
            </h3>
            <div class="ic-sort-controls">
              <select v-model="icCategoryFilter" class="select-input" aria-label="分类过滤">
                <option value="">全部分类</option>
                <option v-for="c in icCategories" :key="c" :value="c">{{ catLabel(c) }}</option>
              </select>
              <select v-model="icSortBy" class="select-input" aria-label="排序方式">
                <option value="abs_ic">|IC| 降序</option>
                <option value="ic_value">IC 降序</option>
                <option value="code">因子代码</option>
                <option value="category">分类</option>
              </select>
            </div>
          </div>
          <div class="ic-sort-stats">
            <span class="ic-stat">有效 <b class="text-up">{{ icValidCount }}</b></span>
            <span class="ic-stat">无效 <b class="text-down">{{ icInvalidCount }}</b></span>
            <span class="ic-stat">平均 |IC| <b>{{ icAvgAbsIC.toFixed(4) }}</b></span>
          </div>
          <div class="ic-sort-table-wrap">
            <table class="data-table ic-sort-table">
              <thead>
                <tr>
                  <th>因子代码</th>
                  <th>分类</th>
                  <th>IC 值</th>
                  <th>有效性</th>
                  <th>样本数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="f in icSortedFactors" :key="f.code" :class="icRowClass(f)">
                  <td>
                    <span class="factor-code" :title="f.code">{{ f.code }}</span>
                  </td>
                  <td><span class="category-badge" :class="'category-' + f.category">{{ catLabel(f.category) }}</span></td>
                  <td :class="icValueClass(f.ic_value)">
                    {{ f.ic_value === null || f.ic_value === undefined ? '--' : f.ic_value.toFixed(4) }}
                  </td>
                  <td>
                    <span v-if="f.ic_value === null || f.ic_value === undefined" class="valid-badge no-data">无数据</span>
                    <span v-else-if="abs(f.ic_value) >= 0.02" class="valid-badge valid">有效</span>
                    <span v-else class="valid-badge invalid">无效</span>
                  </td>
                  <td>{{ f.sample_count ?? '-' }}</td>
                </tr>
                <tr v-if="icSortedFactors.length === 0">
                  <td colspan="5" class="empty-row">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Section Divider -->
        <div class="section-divider">
          <span class="section-divider-label">因子分类</span>
        </div>

        <!-- Expandable Category Cards -->
        <div v-for="cat in categories" :key="cat.name" class="category-card">
          <div class="cat-header" @click="toggleCategory(cat.name)" role="button" tabindex="0" @keydown.enter="toggleCategory(cat.name)">
            <span class="cat-expand" :class="{ expanded: expanded[cat.name] }">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                <path d="M3 1l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
              </svg>
            </span>
            <span class="cat-name">{{ catLabel(cat.name) }}</span>
            <span class="cat-count-badge">{{ cat.count }} 因子</span>
            <span class="cat-stats-detail">
              <!-- F22: valid=0 且含 static 时显示"N 静态"替代"0 有效"（消除"政策因子全坏了"误读） -->
              <span v-if="cat.valid_count === 0 && cat.static_count > 0" class="cat-stat static">
                <span class="stat-dot stat-dot-static"></span>
                {{ cat.static_count }} 静态
              </span>
              <span v-else class="cat-stat valid">
                <span class="stat-dot stat-dot-valid"></span>
                {{ cat.valid_count }} 有效
              </span>
              <span v-if="cat.warn_count > 0" class="cat-stat warn">
                <span class="stat-dot stat-dot-warn"></span>
                {{ cat.warn_count }} 待关注
              </span>
              <span v-if="cat.no_data_count > 0" class="cat-stat no-data">{{ cat.no_data_count }} 无数据</span>
              <span v-if="cat.static_count > 0 && cat.valid_count > 0" class="cat-stat static">
                <span class="stat-dot stat-dot-static"></span>
                {{ cat.static_count }} 静态
              </span>
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
                :class="{ 'factor-row-highlight': f.ic_value !== null && abs(f.ic_value) >= 0.05 }"
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
                            <!-- P2-8: no_data 显示 reason（数据源缺失原因）而非笼统「无数据」 -->
                            {{ f.ic_value !== null ? f.ic_value.toFixed(4) : (f.status === 'no_data' ? '无数据' : '--') }}
                          </strong>
                          <span v-if="f.ic_value !== null" class="tip-status" :class="icStatusClass(f)">
                            {{ abs(f.ic_value) >= (f.ic_threshold || 0.02) ? '✅ 有效' : '⚠️ 低于阈值' }}
                          </span>
                          <!-- P2-8: no_data/warn 的 reason（数据源缺失 / 弱 IC 阈值说明）tooltip -->
                          <span v-else-if="f.reason" class="tip-status status-no-data">
                            <AppTooltip placement="top">
                              ⚠️ {{ f.status === 'no_data' ? '无数据' : '待关注' }}
                              <template #content>
                                <div class="tooltip-rich">{{ f.reason }}</div>
                              </template>
                            </AppTooltip>
                          </span>
                          <!-- F22: static 因子语义标注（不再落入"低于阈值/无效"侧） -->
                          <span v-else-if="f.status === 'static'" class="tip-status status-static">
                            🔒 静态标识（政策哑变量），不参与 IC 统计，非数据缺失
                          </span>
                          <!-- O21 (round7 §7 P21): IC 定义/正负含义/阈值分档说明——用户看到
                               0.07/-0.04 无法判断含义，补解读 -->
                          <div class="tip-ic-explain">
                            IC（信息系数）= 因子值与未来收益的截面相关性：正 IC 表示因子值越高未来收益越好（因子有效），
                            负 IC 为反向指标（低因子值反而预示高收益），|IC| 越接近 1 预测力越强。
                            判定：|IC| ≥ {{ f.ic_threshold || 0.02 }} 视为有效，低于阈值信号弱（⚠️），
                            IC 为 null 表示数据不足或数据源未接入。
                          </div>
                        </div>
                      </div>
                    </template>
                  </AppTooltip>
                  <span v-if="f.status === 'static'" class="factor-static-badge">
                    <AppTooltip placement="top">
                      静态
                      <template #content>
                        <div class="tooltip-rich">静态标识因子（政策哑变量）不参与 IC 统计，非数据缺失</div>
                      </template>
                    </AppTooltip>
                  </span>
                </span>
                <span class="factor-ic-bar-col">
                  <span v-if="f.ic_value !== null" class="ic-bar-wrap">
                    <span
                      class="ic-bar-fill"
                      :class="f.ic_value >= 0 ? 'ic-pos' : 'ic-neg'"
                      :style="{ width: icBarWidth(f.ic_value) }"
                    ></span>
                    <span class="ic-bar-label">{{ abs(f.ic_value).toFixed(4) }}</span>
                  </span>
                  <span v-else class="ic-bar-empty">--</span>
                </span>
                <span class="factor-ic-val" :class="icColorClass(f.ic_value)">
                  <!-- P2-8 (round9 §6.5.1 触发): 区分 no_data 与 warn——null → 「无数据」+ reason
                       tooltip（数据源缺失原因）；warn（弱 IC，ic_value 非 null）→ 显示数值+阈值 -->
                  <AppTooltip v-if="f.ic_value === null" placement="top" :disabled="!f.reason">
                    <span class="factor-ic-no-data">{{ f.status === 'no_data' ? '无数据' : '--' }}</span>
                    <template #content>
                      <div class="tooltip-rich">{{ f.reason }}</div>
                    </template>
                  </AppTooltip>
                  <template v-else>{{ f.ic_value.toFixed(4) }}</template>
                </span>
                <span class="factor-desc" :title="f.description">{{ truncate(f.description, 24) }}</span>
              </div>
              <div v-if="!cat.factors.length" class="factor-empty">该分类暂无已接入因子</div>
            </div>
          </Transition>
        </div>

        <!-- IC Bar Chart Section -->
        <div class="ic-chart-section">
          <div class="section-divider section-divider-chart">
            <span class="section-divider-label">因子 IC 表现</span>
          </div>
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

/* ── Computed ── */
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
  return `${Math.max(pct, 6)}%`
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

  // Use brand blue gradient for positive, warm orange for negative
  const brandBlue = '#3b82f6'
  const warmOrange = '#f97316'
  const colors = values.map(v => {
    const intensity = Math.min(Math.abs(v) * 10, 0.9)
    if (v >= 0) {
      return rgbaColor(brandBlue, intensity)
    }
    return rgbaColor(warmOrange, intensity)
  })

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
    grid: { left: '3%', right: '10%', top: '5%', bottom: '5%', containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, formatter: (v) => v.toFixed(2) },
      splitLine: { lineStyle: { type: 'dashed', color: '#e2e8f0' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { fontSize: 11, width: 100, overflow: 'truncate', fontWeight: 500 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({
        value: v,
        itemStyle: {
          color: colors[i],
          borderRadius: [0, 4, 4, 0],
        },
      })),
      barMaxWidth: 18,
      label: {
        show: true,
        // F2 (round6 §13.2): 正值 right / 负值 left——负值柱从 0 向左延伸，
        // position:'right' 会把标签压在柱身上（文字与图案重叠）。
        position: (p) => (p.value >= 0 ? 'right' : 'left'),
        fontSize: 11,
        fontWeight: 600,
        fontFamily: 'monospace',
        formatter: (p) => abs(p.value).toFixed(4),
      },
      // F2: 相邻柱标签互叠时纵向错位
      labelLayout: { moveOverlap: 'shiftY' },
    }],
  }

  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(option)
}

function rgbaColor(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function handleResize() {
  chartInstance?.resize()
}

/* ── IC Sort Table (P2-1: merged from FactorICView.vue) ── */
const icSortBy = ref('abs_ic')
const icCategoryFilter = ref('')

const icSortedFactors = computed(() => {
  const all = categories.value.flatMap(c => (c.factors || []))
    .filter(f => f.status !== 'static')
  let list = icCategoryFilter.value
    ? all.filter(f => f.category === icCategoryFilter.value)
    : all
  const sortField = icSortBy.value
  const sorted = [...list]
  if (sortField === 'abs_ic') {
    sorted.sort((a, b) => abs(b.ic_value ?? 0) - abs(a.ic_value ?? 0))
  } else if (sortField === 'ic_value') {
    sorted.sort((a, b) => (b.ic_value ?? 0) - (a.ic_value ?? 0))
  } else if (sortField === 'code') {
    sorted.sort((a, b) => a.code.localeCompare(b.code))
  } else if (sortField === 'category') {
    sorted.sort((a, b) => a.category.localeCompare(b.category))
  }
  return sorted
})

const icValidCount = computed(() => icSortedFactors.value.filter(f => abs(f.ic_value ?? 0) >= 0.02).length)
const icInvalidCount = computed(() => icSortedFactors.value.filter(f => abs(f.ic_value ?? 0) < 0.02).length)
const icAvgAbsIC = computed(() => {
  const list = icSortedFactors.value.filter(f => f.ic_value !== null)
  if (list.length === 0) return 0
  return list.reduce((s, f) => s + abs(f.ic_value), 0) / list.length
})
const icCategories = computed(() => {
  const set = new Set()
  categories.value.forEach(c => { if (c.name) set.add(c.name) })
  return [...set]
})

function icRowClass(f) {
  const v = f.ic_value
  if (v === null || v === undefined) return 'ic-row-null'
  const av = abs(v)
  if (av >= 0.05) return 'ic-row-strong'
  if (av >= 0.02) return 'ic-row-valid'
  return 'ic-row-weak'
}

function icValueClass(val) {
  if (val === null || val === undefined) return ''
  if (val > 0.01) return 'text-up'
  if (val < -0.01) return 'text-down'
  return ''
}

/* ── Data ── */
async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const resp = await factorsApi.getActive()
    data.value = resp.data
    // Default: all collapsed
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
.model-body { padding: var(--space-6); }

/* Loading / Error */
.loading-container, .error-container {
  display: flex; flex-direction: column; align-items: center; gap: var(--space-4);
  padding: var(--space-10); color: var(--color-text-secondary);
}
.loading-spinner {
  width: 28px; height: 28px;
  border: 3px solid var(--color-border-light);
  border-top-color: var(--color-brand-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── IC Sort Table (P2-1) ── */
.ic-sort-card {
  margin-bottom: var(--space-2);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.ic-sort-header {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-secondary);
}
.ic-sort-controls { display: flex; gap: var(--space-2); }
.ic-sort-controls .select-input {
  font-size: var(--font-size-xs);
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-sm);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
}
.ic-sort-stats {
  display: flex; gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}
.ic-sort-stats b { font-family: monospace; }
.ic-sort-table-wrap { overflow-x: auto; padding: var(--space-3) var(--space-4); }
.ic-sort-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-xs); }
.ic-sort-table th, .ic-sort-table td {
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid var(--color-border-light);
  text-align: left;
}
.ic-sort-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}
.ic-row-strong { background: var(--color-brand-50); }
.ic-row-valid { background: transparent; }
.ic-row-weak { opacity: 0.75; }
.ic-row-null { color: var(--color-text-tertiary); }
.valid-badge {
  display: inline-block; padding: 0.05rem 0.5rem;
  border-radius: var(--radius-full); font-size: 0.625rem;
  font-weight: var(--font-weight-medium);
}
.valid-badge.valid { color: var(--color-success-700); background: var(--color-success-50); }
.valid-badge.invalid { color: var(--color-warning-700); background: var(--color-warning-50); }
.valid-badge.no-data { color: var(--color-text-tertiary); background: var(--color-surface-tertiary); }
.category-badge {
  display: inline-block; padding: 0.05rem 0.5rem;
  border-radius: var(--radius-full); font-size: 0.625rem;
  background: var(--color-surface-tertiary); color: var(--color-text-secondary);
}
.factor-code { font-family: monospace; font-size: 0.75rem; }
.empty-row { text-align: center; padding: var(--space-6); color: var(--color-text-tertiary); }

/* ── Section Divider ── */
.section-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-6) 0 var(--space-4);
}
.section-divider::before,
.section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border-light);
}
.section-divider-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  white-space: nowrap;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.section-divider-chart {
  margin-top: 0;
  margin-bottom: var(--space-4);
}

/* ── Stats Row ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--space-3);
}
.stat-item {
  display: flex; flex-direction: column; align-items: center;
  gap: var(--space-1); padding: var(--space-4) var(--space-3);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}
.stat-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transform: translateY(-1px);
}
.stat-item-primary {
  background: linear-gradient(135deg, var(--color-brand-50), var(--color-neutral-0));
  border-color: var(--color-brand-200);
}
.stat-num {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: 1.1;
}
.stat-num-brand {
  color: var(--color-brand-600);
}
.stat-num-static {
  color: var(--color-text-tertiary);
}
.stat-lbl {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
.stat-icon {
  font-size: 0.625rem /* O17 */;
}
.stat-icon-valid { color: var(--color-success-600); }
.stat-icon-warn { color: var(--color-warning-600); }

/* ── Category Card ── */
.category-card {
  margin-bottom: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: box-shadow 0.2s ease;
}
.category-card:hover {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
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
  color: var(--color-text-tertiary);
  transition: transform 0.25s ease;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-sm);
}
.cat-expand:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-active);
}
.cat-expand.expanded { transform: rotate(90deg); }
.cat-name {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  flex-shrink: 0;
  font-size: var(--font-size-base);
}
.cat-count-badge {
  font-size: var(--font-size-xs); color: var(--color-brand-700);
  background: var(--color-brand-50); padding: 0.15rem 0.6rem;
  border-radius: var(--radius-full); flex-shrink: 0;
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-brand-100);
}
.cat-stats-detail { display: flex; gap: var(--space-3); flex: 1; flex-wrap: wrap; }
.cat-stat {
  font-size: var(--font-size-xs);
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.cat-stat.valid { color: var(--color-success-600); }
.cat-stat.warn { color: var(--color-warning-600); }
.cat-stat.no-data { color: var(--color-text-tertiary); }
.stat-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.stat-dot-valid { background: var(--color-success-500); }
.stat-dot-warn { background: var(--color-warning-500); }
.stat-dot-static { background: var(--color-text-tertiary); }
.cat-stat.static { color: var(--color-text-tertiary); }
.factor-static-badge {
  display: inline-flex; align-items: center;
  margin-left: var(--space-2);
  font-size: 0.625rem /* O17 */; color: var(--color-text-tertiary);
  background: var(--color-surface-tertiary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-full);
  padding: 0.05rem 0.5rem;
  font-weight: var(--font-weight-medium);
  cursor: help;
  flex-shrink: 0;
}
.status-static { color: var(--color-text-tertiary); }
.cat-avg-ic {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  flex-shrink: 0;
  font-family: monospace;
  padding: 0.1rem 0.5rem;
  border-radius: var(--radius-sm);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
}

/* ── Expand transition ── */
.expand-enter-active, .expand-leave-active {
  transition: max-height 0.25s ease, opacity 0.2s ease;
  max-height: 2000px; overflow: hidden;
}
.expand-enter-from, .expand-leave-to {
  max-height: 0; opacity: 0;
}

/* ── Factor Rows ── */
.cat-body { border-top: 1px solid var(--color-border-light); }
.factor-row {
  display: grid;
  grid-template-columns: 160px 120px 90px 1fr;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-sm);
  align-items: center;
  transition: background var(--transition-fast);
  min-height: 40px;
}
.factor-row:hover {
  background: var(--color-surface-hover);
}
.factor-row-highlight {
  background: rgba(59, 130, 246, 0.02);
}
.factor-header {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  background: var(--color-surface-primary);
  border-bottom: 1px solid var(--color-border-medium);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  min-height: 32px;
}
.factor-name-text {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  cursor: help;
  border-bottom: 1px dashed var(--color-border-medium);
  font-size: var(--font-size-sm);
}
.factor-name-text:hover {
  color: var(--color-brand-600);
  border-bottom-color: var(--color-brand-300);
}

/* ── IC Bar ── */
.factor-ic-bar-col {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.ic-bar-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  position: relative;
}
.ic-bar-fill {
  height: 8px;
  border-radius: var(--radius-full);
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s ease;
  min-width: 6px;
}
.ic-bar-fill.ic-pos {
  background: linear-gradient(90deg, var(--color-brand-300), var(--color-brand-600));
}
.ic-bar-fill.ic-neg {
  background: linear-gradient(90deg, #fdba74, var(--color-warning-600));
}
.ic-bar-label {
  font-size: 0.625rem /* O17 */;
  font-family: monospace;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
}
.ic-bar-empty {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  letter-spacing: 0.5px;
}

.factor-ic-val {
  font-family: monospace;
  font-size: var(--font-size-xs);
  text-align: right;
  font-weight: var(--font-weight-medium);
}
.factor-desc {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-left: var(--space-1);
}
.factor-empty {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* ── Tooltip Rich Content ── */
.tooltip-rich {
  min-width: 220px;
  line-height: var(--line-height-normal);
}
.tip-title { font-weight: var(--font-weight-bold); margin-bottom: var(--space-1); font-size: var(--font-size-base); }
.tip-code { font-size: var(--font-size-xs); color: var(--color-text-tertiary); margin-bottom: var(--space-1); font-family: monospace; }
.tip-desc { font-size: var(--font-size-sm); margin-bottom: var(--space-2); color: var(--color-text-secondary); }
.tip-meta { display: flex; gap: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); margin-bottom: var(--space-1); }
.tip-meta-item { white-space: nowrap; }
.tip-ic { font-size: var(--font-size-sm); padding-top: var(--space-1); border-top: 1px solid var(--color-border-light); }
.tip-status { margin-left: var(--space-2); font-size: var(--font-size-xs); }
.tip-status.status-ok { color: var(--color-success-600); }
.tip-status.status-warn { color: var(--color-warning-600); }

/* ── IC Chart Section ── */
.ic-chart-section {
  margin-top: var(--space-6);
}
.ic-chart-section .section-divider {
  margin-top: 0;
}
.ic-chart-container {
  width: 100%; height: 300px;
  background: var(--color-surface-secondary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
  padding: var(--space-2);
}

/* ── Colors ── */
.text-warn { color: var(--color-warning-600); }
.text-muted { color: var(--color-text-tertiary); }

/* ── Responsive ── */
@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(3, 1fr); }
  .factor-row { grid-template-columns: 120px 80px 70px 1fr; gap: var(--space-1); }
  .cat-stats-detail { display: none; }
  .ic-chart-container { height: 220px; }
  .model-body { padding: var(--space-4); }
}

</style>

