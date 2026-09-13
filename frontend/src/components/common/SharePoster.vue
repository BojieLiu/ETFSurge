<template>
  <div class="share-poster" :data-variant="variant" aria-hidden="true">
    <div class="share-poster__header">
      <img class="share-poster__logo" src="../../assets/logo.svg" alt="ETFSurge" />
      <span class="share-poster__brand">ETFSurge</span>
      <span class="share-poster__time">{{ generatedAt }}</span>
    </div>
    <h3 class="share-poster__title">{{ title }}</h3>
    <div class="share-poster__model">{{ modelLine || '模型未知' }}</div>
    <p class="share-poster__body">{{ body }}</p>
    <p v-if="disclaimer" class="share-poster__disclaimer">{{ disclaimer }}</p>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: 'ETFSurge 分享' },
  modelLine: { type: String, default: '' },
  generatedAt: { type: String, default: '' },
  body: { type: String, default: '' },
  disclaimer: { type: String, default: '' },
  variant: { type: String, default: 'llm' },
})
</script>

<style scoped>
.share-poster {
  width: 750px;
  background: var(--color-surface-primary, #fff);
  color: var(--color-text-primary, #111827);
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: var(--radius-lg, 12px);
  padding: var(--space-5, 20px) var(--space-5, 20px);
}
.share-poster__header {
  display: flex; align-items: center; gap: 10px;
  background: var(--color-brand-700, #1e40af);
  color: #fff; margin: -20px -20px 16px; padding: 14px 20px;
  border-radius: 12px 12px 0 0;
}
.share-poster__logo { width: 28px; height: 28px; }
.share-poster__brand { font-weight: 700; font-size: 20px; }
.share-poster__time { margin-left: auto; font-size: 13px; opacity: 0.85; }
.share-poster__title { font-size: 22px; margin: 0 0 8px; }
.share-poster__model {
  display: inline-block; font-size: 14px; color: var(--color-brand-700, #1d4ed8);
  background: var(--color-bg-brand-subtle, #eff6ff);
  border-radius: 999px; padding: 4px 12px; margin-bottom: 12px;
}
.share-poster__body { font-size: 16px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; margin: 0 0 12px; }
.share-poster__disclaimer { font-size: 12px; color: var(--color-text-tertiary, #6b7280); margin: 0; }
</style>
