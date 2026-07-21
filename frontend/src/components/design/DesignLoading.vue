<template>
  <AppCard
    variant="outlined"
    title="智能组合设计生成中..."
    :description="stepLabel"
    icon="⏳"
    class="design-loading"
    :padding="false"
  >
    <template #header-action v-if="!failed">
      <AppBadge :variant="progress >= 100 ? 'success' : 'default'" class="progress-badge">
        {{ progress }}%
      </AppBadge>
    </template>

    <div class="design-loading__body">
      <div v-if="failed" class="design-loading__error">
        <div class="error-icon" aria-hidden="true">❌</div>
        <h4 class="error-title">生成失败</h4>
        <p class="error-message">{{ failed }}</p>
        <p class="error-hint">请检查后端服务是否正常运行</p>
      </div>

      <div v-else class="design-loading__progress">
        <div class="loading-progress-bar">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progress + '%' }"></div>
          </div>
        </div>

        <div class="loading-steps">
          <LoadingStep
            v-for="step in steps"
            :key="step.id"
            :icon="step.icon"
            :label="step.label"
            :threshold="step.threshold"
            :progress="progress"
          />
        </div>

        <div v-if="progress > 0" class="loading-hint">
          方案生成中，完成后会通过通知栏提醒您
        </div>
      </div>
    </div>

    <template #footer v-if="!failed">
      <div class="design-loading__footer">
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">← 返回</AppButton>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppBadge from '@/components/ui/AppBadge.vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  stepLabel: { type: String, default: '正在采集数据...' },
  failed: { type: String, default: '' }
})

defineEmits(['cancel'])

const steps = [
  { id: 1, icon: '🔍', label: '采集全市场数据', threshold: 20 },
  { id: 2, icon: '📊', label: '筛选候选标的', threshold: 40 },
  { id: 3, icon: '⚙️', label: '因子评分与权重分配', threshold: 80 },
  { id: 4, icon: '📁', label: '生成组合方案', threshold: 100 }
]

// LoadingStep sub-component
const LoadingStep = {
  props: { icon: String, label: String, threshold: Number, progress: Number },
  template: `
    <div class="loading-step" :class="{ done: progress >= threshold, active: progress >= threshold - 20 && progress < threshold }">
      <span class="step-icon">{{ icon }}</span>
      <span class="step-label">{{ label }}</span>
      <span v-if="progress >= threshold" class="step-check" aria-hidden="true">✓</span>
    </div>
  `
}
</script>

<style scoped>
.design-loading {
  max-width: 520px;
  margin: 0 auto;
}

.design-loading__body {
  padding: var(--card-padding);
}

.design-loading__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-4);
}

.error-icon {
  font-size: 48px;
  opacity: 0.8;
}

.error-title {
  margin: 0;
  font: var(--text-h4);
  color: var(--color-text-danger);
}

.error-message {
  margin: 0;
  font: var(--text-body);
  color: var(--color-text-secondary);
}

.error-hint {
  margin: 0;
  font: var(--text-body-sm);
  color: var(--color-text-tertiary);
}

.design-loading__progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.loading-progress-bar {
  width: 100%;
}

.progress-bar {
  height: 8px;
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-brand-500), var(--color-brand-400));
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease-out);
}

.loading-steps {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.loading-step {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  transition: var(--transition-fast);
}

.loading-step.done {
  background: var(--color-bg-success-subtle);
  color: var(--color-success-700);
}

.loading-step.active {
  background: var(--color-bg-brand-subtle);
  color: var(--color-brand-700);
}

.step-icon {
  font-size: var(--font-size-base);
  flex-shrink: 0;
}

.step-label {
  flex: 1;
}

.step-check {
  color: var(--color-success-500);
  font-weight: var(--font-weight-bold);
  flex-shrink: 0;
}

.loading-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  text-align: center;
}

.design-loading__footer {
  display: flex;
  justify-content: center;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
}

.progress-badge {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}
</style>