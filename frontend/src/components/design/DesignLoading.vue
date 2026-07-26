<template>
  <div class="panel-body design-loading">
    <div v-if="failed" class="feature-card loading-card error">
      <div class="error-icon">❌</div>
      <h3 class="loading-title">生成失败</h3>
      <p class="loading-text">{{ failed }}</p>
      <p class="loading-hint">3 秒后将返回设置页，请检查后端服务是否正常运行</p>
      <div class="panel-footer" style="margin-top:20px;text-align:center">
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">&#8592; 返回</AppButton>
      </div>
    </div>
    <div v-else class="feature-card loading-card">
      <div class="loading-spinner-pulse"></div>
      <h3 class="loading-title">智能组合设计生成中...</h3>
      <p class="loading-text">{{ stepLabel }}</p>
      <div class="loading-progress">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <span class="progress-percent">{{ progress }}%</span>
      </div>
      <div class="loading-section">
        <div class="loading-steps">
          <div class="loading-step" :class="{ done: progress >= 20 }">
            <span class="step-icon">&#128200;</span> 采集全市场数据
            <span v-if="progress >= 20" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="{ done: progress >= 40 }">
            <span class="step-icon">&#128269;</span> 筛选候选标的
            <span v-if="progress >= 40" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="{ active: progress >= 40 && progress < 80 }">
            <span class="step-icon">&#9881;</span> 因子评分与权重分配
            <span v-if="progress >= 80" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="{ done: progress >= 80 }">
            <span class="step-icon">&#128221;</span> 生成组合方案
            <span v-if="progress >= 80" class="step-check">&#10003;</span>
          </div>
        </div>
        <div class="loading-hint" v-if="progress > 0">
          方案生成中，完成后会通过通知栏提醒您
        </div>
      </div>
      <div class="panel-footer" style="margin-top:20px;text-align:center">
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">&#8592; 返回</AppButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import AppButton from '../ui/AppButton.vue'

defineProps({
  progress: { type: Number, default: 0 },
  stepLabel: { type: String, default: '正在采集数据...' },
  failed: { type: String, default: '' }
})

defineEmits(['cancel'])
</script>

<style scoped>
.panel-body {
  padding: var(--space-4) 0;
}

.feature-card {
  max-width: 520px;
  margin: 0 auto;
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.loading-card {
  padding: var(--space-6) var(--space-5);
  text-align: center;
}

.loading-card.error {
  border-color: #e53935;
  background: #fff5f5;
}

.error-icon {
  font-size: 3em;
  margin-bottom: var(--space-3);
}

.loading-title {
  font: var(--text-h4);
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
}

.loading-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3);
}

.loading-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin: var(--space-3) 0 0;
}

.loading-spinner-pulse {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--space-4);
  border: 4px solid var(--color-bg-tertiary);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), #42a5f5);
  border-radius: var(--radius-full);
  transition: width 0.5s ease;
  position: relative;
}

.progress-fill::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  to { left: 100%; }
}

.progress-percent {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  min-width: 30px;
  text-align: right;
}

.loading-section {
  text-align: left;
}

.loading-steps {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.loading-step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  padding: var(--space-2);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.loading-step.done {
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
}

.loading-step.active {
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
  background: rgba(25, 118, 210, 0.08);
}

.step-icon {
  font-size: 1.2em;
  width: 24px;
  text-align: center;
}

.step-check {
  margin-left: auto;
  color: var(--color-success, #43A047);
  font-weight: var(--font-weight-bold);
}
</style>
