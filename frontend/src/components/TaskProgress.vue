<template>
  <div class="task-progress">
    <!-- Loading / Running state -->
    <div v-if="taskStatus === 'running'" class="loading-section">
      <span class="loading-spinner">&#9203;</span>
      <span>{{ taskStage || '任务执行中...' }}</span>
      <div v-if="taskProgress > 0" class="progress-bar">
        <div class="progress-fill" :style="{ width: taskProgress + '%' }"></div>
      </div>
    </div>

    <!-- Error state -->
    <div v-else-if="taskStatus === 'failed'" class="error-section">
      <div class="error-icon">&#10060;</div>
      <p class="error-message">{{ errorMessage || '任务执行失败' }}</p>
      <div class="error-actions">
        <AppButton variant="primary" size="sm" @click="$emit('retry')">重新尝试</AppButton>
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">取消</AppButton>
      </div>
    </div>

    <!-- Completed state -->
    <div v-else-if="taskStatus === 'completed'" class="completed-section">
      <div class="completed-icon">&#9989;</div>
      <p class="completed-message">任务已完成</p>
    </div>
  </div>
</template>

<script setup>
import AppButton from './ui/AppButton.vue'

defineProps({
  taskStatus: {
    type: String,
    default: 'running',
    validator: (v) => ['running', 'completed', 'failed', ''].includes(v)
  },
  taskProgress: {
    type: Number,
    default: 0
  },
  taskStage: {
    type: String,
    default: ''
  },
  errorMessage: {
    type: String,
    default: ''
  }
})

defineEmits(['retry', 'cancel'])
</script>

<style scoped>
.task-progress {
  width: 100%;
}

.loading-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) 0;
}

.loading-spinner {
  font-size: 2rem;
  animation: spin 1.5s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-primary-light, #5C6BC0));
  border-radius: var(--radius-full);
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.progress-fill::after {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent);
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  to { left: 100%; }
}

/* Error state */
.error-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  text-align: center;
}

.error-icon {
  font-size: 2rem;
}

.error-message {
  color: var(--color-danger-600, #E53935);
  font-size: var(--font-size-sm);
  max-width: 280px;
  line-height: 1.5;
}

.error-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

/* Completed state */
.completed-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) 0;
}

.completed-icon {
  font-size: 2rem;
}

.completed-message {
  color: var(--color-success-600, #43A047);
  font-size: var(--font-size-sm);
}
</style>
