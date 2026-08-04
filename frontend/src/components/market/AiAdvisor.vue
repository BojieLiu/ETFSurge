<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">💬 AI 投资顾问</h2>
      <p class="section-desc">向 AI 提问获取投资建议，结合实时行情与组合上下文</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <input
            type="text"
            v-model="query"
            placeholder="输入您的投资问题，如：当前市场风格偏向成长还是价值？是否该调仓？"
            class="text-input"
            @keydown.enter="send"
          />
          <button class="btn-primary" @click="send" :disabled="loading">
            {{ loading ? '思考中...' : '🤖 发送提问' }}
          </button>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
        <div v-if="response" class="response" v-html="renderMarkdown(response)"></div>
        <div v-if="!response && !loading && !error" class="hint">
          💡 输入上方问题，AI 将结合实时行情与您的组合给出建议
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const query = ref('')
const response = ref('')
const loading = ref(false)
const error = ref('')
const { start: startStream, stop: stopStream } = useLLMStream()

async function send() {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  response.value = ''
  error.value = ''
  try {
    await startStream('/llm-advice/stream', { query: q, market: props.marketTab }, (token) => {
      response.value += token
    })
  } catch (e) {
    error.value = '提问失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
  }
}
// R5: 市场切换重置——A→US 后旧市场的投顾回答/输入不应残留（交互优化）
// O29 (round7 §7 P29): 补 query 清空——旧实现只清回答/错误，输入框残留
// A 股问题切到美股后语义错乱（注释意图 vs 实现缺失）。
watch(() => props.marketTab, () => {
  stopStream()
  response.value = ''
  error.value = ''
  loading.value = false
  query.value = ''
})

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
  font: var(--text-body);
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
.response { margin-top: var(--space-4); line-height: 1.8; }
.hint { margin-top: var(--space-4); padding: var(--space-4); text-align: center; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
</style>
