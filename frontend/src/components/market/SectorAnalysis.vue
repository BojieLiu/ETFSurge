<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">🏭 板块/概念分析</h2>
      <p class="section-desc">输入板块代码或名称，AI 深度解读</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <input
            type="text"
            v-model="query"
            placeholder="输入板块代码/名称，如 BK0477、半导体..."
            class="text-input"
            @keydown.enter="analyze"
          />
          <button class="btn-primary" @click="analyze" :disabled="loading">
            {{ loading ? '分析中...' : '🔍 AI 分析板块' }}
          </button>
        </div>
        <div v-if="error" class="error">{{ error }}</div>
        <div v-if="result" class="result" v-html="renderMarkdown(result)"></div>
      </div>
    </div>
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

async function analyze() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  result.value = ''
  try {
    // TODO: integrate with real API
    result.value = `分析板块: ${q}`
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
.error { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.result { margin-top: var(--space-4); line-height: 1.8; }
</style>
