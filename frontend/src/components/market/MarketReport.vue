<template>
  <AppCard variant="outlined" title="市场综合研判" description="基于实时行情与宏观数据的 AI 市场环境分析" icon="📊" class="market-report">
    <template #header-action>
      <AppButton
        variant="primary"
        @click="generateMarketReport"
        :loading="marketLoading"
        :disabled="marketLoading"
      >
        <span v-if="!marketLoading" class="btn-icon" aria-hidden="true">🤖</span>
        <span v-else class="animate-spin" aria-hidden="true">⏳</span>
        {{ marketLoading ? '分析中...' : '生成市场研判' }}
      </AppButton>
    </template>

    <AppSkeleton v-if="marketLoading" type="text" :rows="8" />

    <AppAlert v-else-if="marketError" variant="danger" :closable="false">
      <span class="alert-icon" aria-hidden="true">⚠️</span>
      <span>{{ marketError }}</span>
    </AppAlert>

    <div v-else-if="marketReport" class="report-container">
      <div class="report-content" v-html="renderMarkdown(marketReport)"></div>
      <AppAlert variant="warning" class="report-disclaimer" :closable="false">
        <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
        <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
      </AppAlert>
    </div>

    <div v-else class="empty-prompt">
      <span class="prompt-icon" aria-hidden="true">💡</span>
      <p>点击上方按钮生成当前市场环境研判报告</p>
    </div>
  </AppCard>
</template>

<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { useLLMStream } from '@/composables/useLLMStream'
import { AppCard, AppButton, AppSkeleton, AppAlert } from '@/components'

defineProps({ marketTab: { type: String, default: 'A' } })

const marketReport = ref('')
const marketLoading = ref(false)
const marketError = ref('')

const { streaming: marketStreaming, fullText: marketStreamText, error: marketStreamError, disclaimer: marketStreamDisclaimer, start: startMarketStream, stop: stopMarketStream } = useLLMStream()

async function generateMarketReport() {
  marketLoading.value = true
  marketReport.value = ''
  marketError.value = ''
  try {
    const result = await startMarketStream('/llm-report/stream', { symbols: null }, (token) => {
      marketReport.value += token
    })
    if (result?.disclaimer) {
      marketStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    marketError.value = '生成失败：' + (e?.message || '网络错误')
  } finally {
    marketLoading.value = false
  }
}
</script>

<style scoped>
.market-report {
  /* AppCard handles layout */
}

.report-container {
  margin-top: var(--space-4);
}

.report-content {
  line-height: 1.8;
}

.report-content :deep(h1),
.report-content :deep(h2),
.report-content :deep(h3) {
  margin-top: var(--space-6);
  margin-bottom: var(--space-3);
}

.report-content :deep(p) {
  margin: var(--space-2) 0;
}

.report-content :deep(ul),
.report-content :deep(ol) {
  margin: var(--space-3) 0;
  padding-left: var(--space-6);
}

.report-content :deep(li) {
  margin: var(--space-1) 0;
}

.report-content :deep(code) {
  font-family: var(--font-family-mono);
  background: var(--color-neutral-100);
  padding: 0.125rem 0.375rem;
  border-radius: var(--radius-sm);
  font-size: 0.875em;
}

.report-content :deep(pre) {
  background: var(--color-neutral-900);
  color: var(--color-neutral-100);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  overflow-x: auto;
  margin: var(--space-4) 0;
}

.report-content :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
  font-size: inherit;
}

.report-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--space-4) 0;
}

.report-content :deep(th),
.report-content :deep(td) {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  text-align: left;
}

.report-content :deep(th) {
  background: var(--color-surface-secondary);
  font-weight: var(--font-weight-semibold);
}

.report-disclaimer {
  margin-top: var(--space-4);
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
  font-size: 32px;
  opacity: 0.6;
}

.animate-spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>