<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">📊 指数分析</h2>
      <p class="section-desc">输入指数代码，查看 AI 解读与行情数据</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <input
            type="text"
            v-model="query"
            placeholder="输入指数代码，如 000001 (上证)、HSI (恒生)、SPX (标普)..."
            class="text-input"
            @keydown.enter="analyze"
          />
          <button class="btn-primary" @click="analyze" :disabled="loading">
            {{ loading ? '分析中...' : '🔍 AI 分析指数' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Quick examples -->
    <div v-if="!query" class="quick-chips">
      <span class="chip-label">常用指数:</span>
      <button v-for="ex in examples" :key="ex.code" class="chip" @click="quickSelect(ex)">{{ ex.label }}</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="result" class="result" v-html="renderMarkdown(result)"></div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '../../utils/markdown'

defineProps({ marketTab: { type: String, default: 'A' } })

const query = ref('')
const loading = ref(false)
const result = ref('')
const error = ref('')

const examples = [
  { code: '000001', label: '上证指数' },
  { code: '399001', label: '深证成指' },
  { code: '399006', label: '创业板指' },
  { code: 'HSI', label: '恒生指数' },
  { code: 'SPX', label: '标普500' },
]

function quickSelect(ex) {
  query.value = ex.code
  analyze()
}

async function analyze() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  result.value = ''
  // TODO: integrate with real API
  setTimeout(() => {
    result.value = `分析指数: ${q}`
    loading.value = false
  }, 500)
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
.result { margin-top: var(--space-4); line-height: 1.8; }
.quick-chips { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-3); padding: 0 var(--space-1); }
.chip-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.chip { padding: var(--space-1) var(--space-3); font-size: var(--font-size-sm); font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); color: var(--color-brand-600); background: var(--color-bg-brand-subtle); border: 1px solid var(--color-brand-200); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); }
.chip:hover { background: var(--color-brand-100); border-color: var(--color-brand-400); }
</style>
