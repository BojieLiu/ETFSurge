<template>
  <AppCard variant="outlined" title="AI 投资顾问" description="向 AI 提问获取投资建议，结合实时行情与组合上下文" icon="💬" class="ai-advisor">
    <div class="ai-advisor__body">
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

      <AppAlert v-if="adviceError" variant="danger" :closable="false">
        <span class="alert-icon" aria-hidden="true">⚠️</span>
        <span>{{ adviceError }}</span>
      </AppAlert>

      <div v-else-if="adviceResponse" class="advice-response">
        <div class="advice-content" v-html="renderMarkdown(adviceResponse)"></div>
      </div>

      <div v-else class="empty-prompt">
        <span class="prompt-icon" aria-hidden="true">💡</span>
        <p>输入上方问题，AI 将结合实时行情与您的组合给出建议</p>
      </div>
    </div>
  </AppCard>
</template>

<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { analysisApi } from '@/api'
import { AppCard, AppButton, AppInput, AppAlert } from '@/components'

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
.ai-advisor {
  /* AppCard handles layout */
}

.ai-advisor__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.advice-input-group {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  align-items: stretch;
}

.advice-input {
  flex: 1;
  min-width: 280px;
}

.advice-response {
  padding: var(--space-4);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}

.advice-content {
  line-height: 1.8;
}

.advice-content :deep(h1),
.advice-content :deep(h2),
.advice-content :deep(h3) {
  margin-top: var(--space-6);
  margin-bottom: var(--space-3);
}

.advice-content :deep(p) {
  margin: var(--space-2) 0;
}

.advice-content :deep(ul),
.advice-content :deep(ol) {
  margin: var(--space-3) 0;
  padding-left: var(--space-6);
}

.advice-content :deep(li) {
  margin: var(--space-1) 0;
}

.advice-content :deep(code) {
  font-family: var(--font-family-mono);
  background: var(--color-neutral-100);
  padding: 0.125rem 0.375rem;
  border-radius: var(--radius-sm);
  font-size: 0.875em;
}

.advice-content :deep(pre) {
  background: var(--color-neutral-900);
  color: var(--color-neutral-100);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  overflow-x: auto;
}

.advice-content :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}

.empty-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-8);
  color: var(--color-text-tertiary);
}

.prompt-icon {
  font-size: 48px;
  opacity: 0.5;
}

@media (max-width: 639px) {
  .advice-input-group {
    flex-direction: column;
  }
  .advice-input {
    min-width: 0;
  }
}
</style>