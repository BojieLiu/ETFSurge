<template>
  <div class="factor-ic-view">
    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="loading-spinner" aria-hidden="true"></div>
      <p>因子 IC 数据加载中...</p>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <p>加载失败: {{ error }}</p>
      <button class="btn btn-primary" @click="fetchIC">重试</button>
    </div>

    <template v-else>
      <!-- Stats Cards -->
      <section class="stats-grid" aria-label="概览统计">
        <div class="stat-card">
          <span class="stat-label">因子数量</span>
          <span class="stat-value">{{ icData.total }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">有效因子</span>
          <span class="stat-value text-up">{{ validCount }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">无效因子</span>
          <span class="stat-value text-down">{{ invalidCount }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">平均 |IC|</span>
          <span class="stat-value">{{ avgAbsIC.toFixed(4) }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">更新时间</span>
          <span class="stat-value" style="font-size: 0.85em">{{ formatTime(icData.updated_at) }}</span>
        </div>
      </section>

      <!-- Filter & Sort Controls -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">🔍</span>
            因子 IC 排序
          </h2>
          <div class="filter-group">
            <select v-model="categoryFilter" class="select-input" @change="applyFilters">
              <option value="">全部分类</option>
              <option value="style">风格</option>
              <option value="technical">技术</option>
              <option value="sentiment">情绪</option>
              <!-- P2-4 (R4-11c): 选项对齐后端 categories 归一化值（_get_factor_category
                   输出 china_specific/etf_specific；旧 'china'/'etf' → 过滤恒为空） -->
              <option value="china_specific">A 股特有</option>
              <option value="etf_specific">ETF</option>
            </select>
            <select v-model="sortBy" class="select-input" @change="applyFilters">
              <option value="abs_ic">|IC| 降序</option>
              <option value="ic_value">IC 降序</option>
              <option value="code">因子代码</option>
              <option value="category">分类</option>
            </select>
            <button class="btn btn-secondary btn-sm" @click="fetchIC">
              刷新
            </button>
          </div>
        </div>
      </section>

      <!-- Factor IC Table -->
      <section class="card">
        <div class="card-body" style="padding: 0; overflow-x: auto">
          <table class="data-table">
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
              <tr v-for="f in filteredFactors" :key="f.code" :class="rowClass(f)">
                <td>
                  <span class="factor-code" :title="f.code">{{ f.code }}</span>
                </td>
                <td><span class="category-badge" :class="'category-' + f.category">{{ f.category }}</span></td>
                <td :class="icValueClass(f.ic_value)">{{ f.ic_value.toFixed(4) }}</td>
                <td>
                  <span v-if="isValid(f)" class="valid-badge valid">有效</span>
                  <span v-else class="valid-badge invalid">无效</span>
                </td>
                <td>{{ f.sample_count ?? '-' }}</td>
              </tr>
              <tr v-if="filteredFactors.length === 0">
                <td colspan="5" class="empty-row">暂无数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { factorsApi } from '../api/index.js'

const loading = ref(true)
const error = ref(null)
const icData = ref({ factors: [], total: 0, updated_at: '' })

const categoryFilter = ref('')
const sortBy = ref('abs_ic')
const IC_THRESHOLD = 0.02

async function fetchIC() {
  loading.value = true
  error.value = null
  try {
    const res = await factorsApi.getIC()
    icData.value = res.data
  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  // Triggers re-computation of filteredFactors
}

const filteredFactors = computed(() => {
  let list = icData.value.factors || []

  // Category filter
  if (categoryFilter.value) {
    list = list.filter((f) => f.category === categoryFilter.value)
  }

  // Sorting
  const sortField = sortBy.value
  const sorted = [...list]
  if (sortField === 'abs_ic') {
    sorted.sort((a, b) => Math.abs(b.ic_value) - Math.abs(a.ic_value))
  } else if (sortField === 'ic_value') {
    sorted.sort((a, b) => b.ic_value - a.ic_value)
  } else if (sortField === 'code') {
    sorted.sort((a, b) => a.code.localeCompare(b.code))
  } else if (sortField === 'category') {
    sorted.sort((a, b) => a.category.localeCompare(b.category))
  }

  return sorted
})

const validCount = computed(() => (icData.value.factors || []).filter((f) => Math.abs(f.ic_value) >= IC_THRESHOLD).length)
const invalidCount = computed(() => (icData.value.factors || []).filter((f) => Math.abs(f.ic_value) < IC_THRESHOLD).length)
const avgAbsIC = computed(() => {
  const list = icData.value.factors || []
  if (list.length === 0) return 0
  return list.reduce((s, f) => s + Math.abs(f.ic_value), 0) / list.length
})

function isValid(f) {
  return Math.abs(f.ic_value) >= IC_THRESHOLD
}

function rowClass(f) {
  const abs = Math.abs(f.ic_value)
  if (abs >= 0.05) return 'row-strong'
  if (abs >= IC_THRESHOLD) return 'row-valid'
  return 'row-weak'
}

function icValueClass(val) {
  if (val > 0.01) return 'text-up'
  if (val < -0.01) return 'text-down'
  return ''
}

function formatTime(iso) {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(fetchIC)
</script>

<style scoped>
.factor-ic-view {
  padding: 1rem;
  max-width: 1200px;
  margin: 0 auto;
}

.loading-state {
  text-align: center;
  padding: 3rem;
  color: var(--text-secondary, #888);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-color, #e0e0e0);
  border-top-color: var(--primary, #409eff);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-state {
  text-align: center;
  padding: 2rem;
  color: var(--danger, #e74c3c);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.stat-card {
  background: var(--card-bg, #fff);
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}

.stat-label {
  display: block;
  font-size: 0.8rem;
  color: var(--text-secondary, #888);
  margin-bottom: 0.3rem;
}

.stat-value {
  font-size: 1.3rem;
  font-weight: 700;
}

.card {
  background: var(--card-bg, #fff);
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color, #eaeaea);
  flex-wrap: wrap;
  gap: 0.5rem;
}

.card-title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.card-title-icon {
  margin-right: 0.3rem;
}

.card-body {
  padding: 1rem;
}

.filter-group {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}

.select-input {
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border-color, #d0d0d0);
  border-radius: 4px;
  background: var(--input-bg, #fff);
  font-size: 0.85rem;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.data-table th {
  background: var(--table-header-bg, #f5f7fa);
  padding: 0.6rem 0.8rem;
  text-align: left;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 2px solid var(--border-color, #e0e0e0);
}

.data-table td {
  padding: 0.5rem 0.8rem;
  border-bottom: 1px solid var(--border-color, #eee);
}

.data-table tbody tr:hover {
  background: var(--table-hover-bg, #f0f7ff);
}

.factor-code {
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
  word-break: break-all;
}

.category-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.category-technical { background: #e3f2fd; color: #1565c0; }
.category-style { background: #fce4ec; color: #c62828; }
.category-sentiment { background: #f3e5f5; color: #7b1fa2; }
.category-china { background: #fff3e0; color: #e65100; }
.category-etf { background: #e8f5e9; color: #2e7d32; }
.category-unknown { background: #f5f5f5; color: #616161; }

.valid-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

.valid-badge.valid { background: #e8f5e9; color: #2e7d32; }
.valid-badge.invalid { background: #fbe9e7; color: #bf360c; }

.row-strong { background: rgba(46, 125, 50, 0.04); }
.row-valid { background: rgba(255, 193, 7, 0.04); }
.row-weak { background: transparent; }

.empty-row {
  text-align: center;
  color: var(--text-secondary, #999);
  padding: 2rem !important;
}

.text-up { color: var(--up-color, #e74c3c); }
.text-down { color: var(--down-color, #27ae60); }

.btn {
  padding: 0.4rem 0.8rem;
  border: 1px solid var(--border-color, #d0d0d0);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: background 0.15s;
}

.btn-primary {
  background: var(--primary, #409eff);
  color: #fff;
  border-color: var(--primary, #409eff);
}

.btn-secondary {
  background: var(--btn-bg, #f5f5f5);
  color: var(--text-primary, #333);
}

.btn-sm { padding: 0.3rem 0.6rem; font-size: 0.8rem; }

@media (max-width: 640px) {
  .factor-ic-view { padding: 0.5rem; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .card-header { flex-direction: column; align-items: flex-start; }
  .filter-group { width: 100%; }
  .select-input { flex: 1; }
}
</style>
