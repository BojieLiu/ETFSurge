<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">💬</span>
        AI 投资顾问
      </h2>
      <p class="section-desc">向 AI 提问获取投资建议，结合实时行情与组合上下文</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="advice-input-group">
          <AppInput
            v-model="adviceQuery"
            placeholder="输入您的投资问题，如：当前市场风格偏向成长还是价值？是否该调仓？"
            @keydown.enter="sendAdviceQuery"
            :disabled="adviceLoading"
            class="advice-input"
          />
          <AppButton
            variant="primary"
            @click="sendAdviceQuery"
            :loading="adviceLoading"
            :disabled="adviceLoading || !adviceQuery.trim()"
          >
            <span class="btn-icon" aria-hidden="true" v-if="!adviceLoading">🤖</span>
            <span class="animate-spin" v-else aria-hidden="true">⏳</span>
            {{ adviceLoading ? '思考中...' : '发送提问' }}
          </AppButton>
        </div>

        <div v-if="adviceError" class="alert alert--error" role="alert">
          <span class="alert-icon" aria-hidden="true">⚠️</span>
          <span>{{ adviceError }}</span>
        </div>

        <div v-if="adviceResponse" class="advice-response">
          <div class="advice-content" v-html="renderMarkdown(adviceResponse)"></div>
        </div>

        <div v-if="!adviceResponse && !adviceLoading && !adviceError" class="empty-prompt">
          <span class="prompt-icon" aria-hidden="true">💡</span>
          <p>输入上方问题，AI 将结合实时行情与您的组合给出建议</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { analysisApi } from '../../api'

defineProps({ marketTab: { type: String, default: 'A' } })

const adviceQuery = ref('')
const adviceResponse = ref('')
const adviceLoading = ref(false)
const adviceError = ref('')

async function sendAdviceQuery() {
  const query = adviceQuery.value.trim()
  if (!query || adviceLoading.value) return
  adviceLoading.value = true
  adviceResponse.value = ''
  adviceError.value = ''
  try {
    const context = {
      include_market_data: true,
      include_news: true,
      portfolio_symbols: [],
      market: 'A',
    }
    const res = await analysisApi.llmAdvice(query, context)
    adviceResponse.value = res.data.advice || res.data
  } catch (e) {
    adviceError.value = '提问失败：' + (e?.message || '网络错误')
  } finally {
    adviceLoading.value = false
  }
}
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-1); }
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: visible; }
.card-body { padding: var(--space-5); }
.advice-input-group { display: flex; gap: var(--space-3); margin-bottom: var(--space-4); }
.advice-input { flex: 1; }
.alert { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); font-size: var(--font-size-sm); }
.alert--error { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 1px solid var(--color-danger-200); }
.advice-response { margin-top: var(--space-4); }
.advice-content { line-height: 1.8; }
.advice-content :deep(h1), .advice-content :deep(h2), .advice-content :deep(h3) { margin-top: var(--space-6); margin-bottom: var(--space-3); }
.advice-content :deep(p) { margin: var(--space-2) 0; }
.advice-content :deep(ul), .advice-content :deep(ol) { padding-left: var(--space-6); margin: var(--space-2) 0; }
.empty-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.prompt-icon { font-size: var(--font-size-3xl); }
</style>
