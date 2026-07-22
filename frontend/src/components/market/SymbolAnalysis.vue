<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">📈 个股/ETF 分析</h2>
      <p class="section-desc">输入股票或 ETF 代码，查看技术图表、指标与 AI 研报</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <input
            type="text"
            v-model="query"
            placeholder="输入代码，如 510050、000001、贵州茅台..."
            class="text-input"
            @keydown.enter="doAnalyze"
          />
          <button class="btn-primary" @click="doAnalyze" :disabled="loading">
            {{ loading ? '分析中...' : '🔍 分析' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Quick examples -->
    <div v-if="!query" class="quick-chips">
      <span class="chip-label">快速输入:</span>
      <button v-for="ex in examples" :key="ex" class="chip" @click="quickSelect(ex)">{{ ex }}</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <!-- Chart + Indicators + AI Report (TODO) -->
    <div v-if="symbol" class="result-area">
      <p>已选择: <strong>{{ symbol }}</strong></p>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ marketTab: { type: String, default: 'A' }, selectedSymbol: { type: String, default: null } })

const query = ref('')
const symbol = ref('')
const loading = ref(false)
const error = ref('')

const examples = ['510050', '159915', '518880', '513100', '159941']

function quickSelect(code) {
  query.value = code
  symbol.value = code
}

async function doAnalyze() {
  const q = query.value.trim()
  if (!q) return
  symbol.value = q
  loading.value = true
  error.value = ''
  // TODO: chart + indicator fetch
  setTimeout(() => { loading.value = false }, 500)
}
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }
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
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
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
.quick-chips { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-3); padding: 0 var(--space-1); }
.chip-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.chip { padding: var(--space-1) var(--space-3); font-size: var(--font-size-sm); font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); color: var(--color-brand-600); background: var(--color-bg-brand-subtle); border: 1px solid var(--color-brand-200); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); }
.chip:hover { background: var(--color-brand-100); border-color: var(--color-brand-400); }
.result-area { margin-top: var(--space-4); padding: var(--space-4); text-align: center; color: var(--color-text-secondary); }
</style>
