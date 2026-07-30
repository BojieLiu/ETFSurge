<template>
  <div class="source-monitor">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p>加载中...</p>
    </div>

    <template v-else>
      <!-- Stats Cards -->
      <section class="stats-grid" aria-label="数据源概览">
        <div class="stat-card">
          <span class="stat-label">数据源总数</span>
          <span class="stat-value">{{ sources.length }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">可用</span>
          <span class="stat-value text-success">{{ availableCount }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">熔断中</span>
          <span class="stat-value" :class="{ 'text-danger': circuitBrokenCount > 0 }">
            {{ circuitBrokenCount }}
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">发生异常</span>
          <span class="stat-value" :class="{ 'text-danger': failureCount > 0 }">
            {{ failureCount }}
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">最近失败</span>
          <span class="stat-value" :class="{ 'text-danger': failures.length > 0 }">
            {{ failures.length }}
          </span>
        </div>
      </section>

      <!-- Timeline Chart -->
      <section class="card chart-section">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📈</span>
            事件趋势 ({{ timelineHours }}h)
          </h2>
          <div class="tab-group" role="tablist" aria-label="时间范围切换">
            <button
              :class="['tab-btn', { 'tab-btn--active': timelineHours === 1 }]"
              role="tab"
              :aria-selected="timelineHours === 1"
              @click="switchTimeline(1)"
            >1小时</button>
            <button
              :class="['tab-btn', { 'tab-btn--active': timelineHours === 6 }]"
              role="tab"
              :aria-selected="timelineHours === 6"
              @click="switchTimeline(6)"
            >6小时</button>
            <button
              :class="['tab-btn', { 'tab-btn--active': timelineHours === 24 }]"
              role="tab"
              :aria-selected="timelineHours === 24"
              @click="switchTimeline(24)"
            >24小时</button>
          </div>
        </div>
        <div class="card-body">
          <v-chart
            v-if="timelineOption"
            :option="timelineOption"
            :style="{ height: '300px' }"
            autoresize
          />
          <div v-else class="chart-empty">暂无数据</div>
        </div>
      </section>

      <!-- Source Health Table -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">🔌</span>
            数据源状态
          </h2>
          <button class="refresh-btn" @click="fetchData" aria-label="刷新数据">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" aria-hidden="true">
              <path d="M23 4v6h-6M1 20v-6h6"/>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
            </svg>
          </button>
        </div>
        <div class="card-body">
          <div v-if="sources.length" class="source-table">
            <div class="source-table-header">
              <span class="src-col-type">类型</span>
              <span class="src-col-name">数据源</span>
              <span class="src-col-status">状态</span>
              <span class="src-col-num">失败次数</span>
              <span class="src-col-num">冷却中</span>
              <span class="src-col-cb">熔断器</span>
            </div>
            <div
              v-for="src in enrichedSources"
              :key="src.name"
              class="source-table-row"
            >
              <span class="src-col-type">
                <span :class="['type-badge', src.category === 'system' ? 'type-system' : 'type-data']">
                  {{ src.category === 'system' ? '系统' : '数据' }}
                </span>
              </span>
              <span class="src-col-name mono">{{ src.name }}</span>
              <span class="src-col-status">
                <span :class="['status-badge', src.available ? 'status-ok' : 'status-error']">
                  {{ src.available ? '可用' : '不可用' }}
                </span>
              </span>
              <span class="src-col-num" :class="{ 'text-danger': src.failures > 0 }">
                {{ src.failures }}
              </span>
              <span class="src-col-num">
                {{ src.cooldown_remaining > 0 ? src.cooldown_remaining.toFixed(0) + 's' : '-' }}
              </span>
              <span class="src-col-cb">
                <span :class="['cb-badge', src.cbState === 'closed' ? 'cb-closed' : 'cb-open']">
                  {{ src.cbState === 'closed' ? '正常' : '熔断' }}
                </span>
              </span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无数据源记录</div>
        </div>
      </section>

      <!-- Recent Failures -->
      <section v-if="failures.length" class="card failure-card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">❌</span>
            最近失败事件
          </h2>
          <span class="failure-badge">{{ failures.length }} 条</span>
        </div>
        <div class="card-body failure-body">
          <div class="failure-table">
            <div class="failure-table-header">
              <span class="fail-col-time">时间</span>
              <span class="fail-col-src">数据源</span>
              <span class="fail-col-route">路径</span>
              <span class="fail-col-target">标的</span>
              <span class="fail-col-dur">耗时</span>
              <span class="fail-col-msg">错误信息</span>
            </div>
            <div
              v-for="(f, i) in failures"
              :key="i"
              class="failure-table-row"
            >
              <span class="fail-col-time mono">{{ formatTime(f.timestamp) }}</span>
              <span class="fail-col-src mono">{{ f.source_name }}</span>
              <span class="fail-col-route mono">{{ f.route }}</span>
              <span class="fail-col-target mono">{{ f.target }}</span>
              <span class="fail-col-dur">{{ f.duration_ms.toFixed(0) }}ms</span>
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
import { ref, computed, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { adminApi } from '../api'
import { useToastStore } from '../stores/toast'
import logger from '../utils/logger'

use([CanvasRenderer, LineChart, BarChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent])

const loading = ref(true)
const sources = ref([])
const circuitBreakers = ref([])
const timeline = ref([])
const failures = ref([])
const timelineHours = ref(1)

async function fetchData() {
  loading.value = true
  // 分步请求，每个独立 try/catch，防止单个端点挂起阻塞全部页面
  try {
    const healthRes = await adminApi.sourcesHealth()
    sources.value = healthRes.data || []
  } catch (e) {
    logger.error('sourcesHealth failed', e)
  }
  try {
    const cbRes = await adminApi.sourcesCircuitBreakers()
    circuitBreakers.value = cbRes.data || []
  } catch (e) {
    logger.error('sourcesCircuitBreakers failed', e)
  }
  try {
    const tlRes = await adminApi.sourcesTimeline(timelineHours.value)
    timeline.value = tlRes.data || []
  } catch (e) {
    logger.error('sourcesTimeline failed', e)
  }
  try {
    const failRes = await adminApi.sourcesFailures(10)
    failures.value = failRes.data || []
  } catch (e) {
    logger.error('sourcesFailures failed', e)
  }
  loading.value = false
}

async function switchTimeline(hours) {
  timelineHours.value = hours
  await fetchData()
}

const availableCount = computed(() => sources.value.filter(s => s.available).length)
const circuitBrokenCount = computed(() => circuitBreakers.value.filter(cb => cb.state === 'open').length)
const failureCount = computed(() => sources.value.filter(s => s.failures > 0).length)

// Z33: Categorize sources as 'data' or 'system' (threadpool/monitoring)
function getSourceCategory(name) {
  const systemPrefixes = ['threadpool', 'thread_pool', 'system_']
  return systemPrefixes.some(p => name.startsWith(p)) ? 'system' : 'data'
}

const enrichedSources = computed(() => {
  const cbMap = {}
  circuitBreakers.value.forEach(cb => { cbMap[cb.name] = cb })
  return sources.value.map(src => ({
    ...src,
    cbState: cbMap[src.name]?.state || 'closed',
    category: getSourceCategory(src.name),
  }))
})

const timelineOption = computed(() => {
  const data = timeline.value
  if (!data.length) return null

  const buckets = data.map(d => {
    const t = new Date(d.bucket)
    const pad = (n) => String(n).padStart(2, '0')
    return `${pad(t.getHours())}:${pad(t.getMinutes())}`
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['成功', '失败'],
      top: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: buckets,
      axisLabel: {
        rotate: timelineHours.value > 6 ? 45 : 0,
        fontSize: 10,
        interval: timelineHours.value > 6 ? 5 : 0,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: '事件数',
        min: 0,
      },
    ],
    series: [
      {
        name: '成功',
        type: 'bar',
        stack: 'total',
        data: data.map(d => d.success),
        itemStyle: { color: '#22c55e', borderRadius: [0, 0, 0, 0] },
        barMaxWidth: 30,
      },
      {
        name: '失败',
        type: 'bar',
        stack: 'total',
        data: data.map(d => d.failure),
        itemStyle: { color: '#ef4444', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 30,
      },
    ],
    color: ['#22c55e', '#ef4444'],
  }
})

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
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
.source-monitor {
  max-width: 1100px;
  margin: 0 auto;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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

.text-success {
  color: var(--color-success-500, #22c55e);
}

.text-danger {
  color: var(--color-danger-500);
}

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

.refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-surface-primary);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.refresh-btn:hover {
  background: var(--color-surface-secondary);
  color: var(--color-text-primary);
}

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

.source-table {
  display: flex;
  flex-direction: column;
}

.source-table-header,
.source-table-row {
  display: grid;
  grid-template-columns: 1.5fr 0.8fr 0.8fr 0.8fr 0.8fr;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-2);
  align-items: center;
}

.source-table-header {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border-light);
}

.source-table-row {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  border-bottom: 1px solid var(--color-border-lighter);
}

.source-table-row:last-child {
  border-bottom: none;
}

.src-col-type {
  text-align: center;
  width: 48px;
  flex-shrink: 0;
}
.type-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.4;
}
.type-data {
  background: #e0f2fe;
  color: #0369a1;
}
.type-system {
  background: #f3e8ff;
  color: #7c3aed;
}
.src-col-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.src-col-name.mono {
  font-family: ui-monospace, monospace;
  font-size: var(--font-size-xs);
}

.src-col-num {
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.status-badge {
  display: inline-block;
  padding: 2px var(--space-3);
  border-radius: var(--radius-full);
  font: var(--text-caption);
}

.status-ok {
  background: var(--color-success-50, #f0fdf4);
  color: var(--color-success-700, #15803d);
}

.status-error {
  background: var(--color-danger-50);
  color: var(--color-danger-700, #b91c1c);
}

.cb-badge {
  display: inline-block;
  padding: 2px var(--space-3);
  border-radius: var(--radius-full);
  font: var(--text-caption);
  text-align: center;
}

.cb-closed {
  background: var(--color-success-50, #f0fdf4);
  color: var(--color-success-700, #15803d);
}

.cb-open {
  background: var(--color-danger-50);
  color: var(--color-danger-700, #b91c1c);
}

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

@keyframes spin {
  to { transform: rotate(360deg); }
}

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
  grid-template-columns: 130px 100px 100px 80px 70px 1fr;
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
.fail-col-src,
.fail-col-route,
.fail-col-target {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fail-col-dur {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-secondary);
}

.fail-col-msg-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
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

.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all 0.15s;
}

.copy-btn:hover {
  background: var(--color-surface-secondary);
  color: var(--color-text-primary);
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}
</style>
