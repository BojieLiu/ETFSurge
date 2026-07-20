<template>
  <div v-if="hasError" class="error-overlay">
    <div class="error-card">
      <span class="error-icon" aria-hidden="true">⚠️</span>
      <h3>{{ errorMessage || '仪表盘加载异常' }}</h3>
      <p>发生意外错误，请刷新页面重试</p>
      <AppButton variant="primary" @click="$emit('retry')">重试</AppButton>
    </div>
  </div>
</template>

<script setup>
import AppButton from '../ui/AppButton.vue'

defineProps({
  hasError: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' }
})

defineEmits(['retry'])
</script>

<style scoped>
.error-overlay {
  display: flex;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
}
.error-card {
  text-align: center;
  max-width: 400px;
  padding: var(--space-8);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
}
.error-icon {
  font-size: var(--font-size-5xl);
  display: block;
  margin-bottom: var(--space-4);
}
.error-card h3 {
  margin: 0 0 var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.error-card p {
  margin: 0 0 var(--space-6);
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}
</style>
