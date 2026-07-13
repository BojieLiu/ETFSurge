<template>
  <div class="skeleton" :class="skeletonClasses" role="status" aria-live="polite" aria-busy="true">
    <div v-if="type === 'text'" class="skeleton-line" :style="{ width: width, height: lineHeight }"></div>
    <div v-if="type === 'text'" class="skeleton-line" :style="{ width: width2, height: lineHeight }"></div>
    <div v-if="type === 'text'" class="skeleton-line" :style="{ width: width3, height: lineHeight }"></div>
    <div v-if="type === 'card'" class="skeleton-card-inner">
      <div class="skeleton-line skeleton-header" :style="{ width: headerWidth }"></div>
      <div class="skeleton-line skeleton-content" :style="{ width: contentWidth1 }"></div>
      <div class="skeleton-line skeleton-content" :style="{ width: contentWidth2 }"></div>
      <div class="skeleton-line skeleton-content" :style="{ width: contentWidth3 }"></div>
    </div>
    <div v-if="type === 'chart'" class="skeleton-chart" :style="{ height }"></div>
    <div v-if="type === 'table'" class="skeleton-table" :style="{ height: tableHeight }">
      <div class="skeleton-table-header">
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
      </div>
      <div v-for="i in rows" :key="i" class="skeleton-table-row">
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell"></div>
      </div>
    </div>
    <div v-if="type === 'avatar'" class="skeleton-avatar" :style="{ width: size, height: size }"></div>
    <div v-if="type === 'button'" class="skeleton-button" :style="{ width: buttonWidth, height: buttonHeight }"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  type: { type: String, default: 'text', validator: v => ['text', 'card', 'chart', 'table', 'avatar', 'button'].includes(v) },
  width: { type: String, default: '100%' },
  width2: { type: String, default: '60%' },
  width3: { type: String, default: '40%' },
  lineHeight: { type: String, default: '1rem' },
  headerWidth: { type: String, default: '30%' },
  contentWidth1: { type: String, default: '80%' },
  contentWidth2: { type: String, default: '60%' },
  contentWidth3: { type: String, default: '40%' },
  height: { type: String, default: '200px' },
  rows: { type: Number, default: 5 },
  tableHeight: { type: String, default: 'auto' },
  size: { type: String, default: '40px' },
  buttonWidth: { type: String, default: '120px' },
  buttonHeight: { type: String, default: '36px' },
  animated: { type: Boolean, default: true }
})

const skeletonClasses = computed(() => [
  'skeleton',
  `skeleton--${props.type}`,
  { 'skeleton--animated': props.animated }
])
</script>

<style scoped>
.skeleton {
  display: inline-block;
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.skeleton--animated {
  background: linear-gradient(
    90deg,
    var(--color-surface-secondary) 25%,
    var(--color-surface-tertiary) 50%,
    var(--color-surface-secondary) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Text Skeleton */
.skeleton--text { display: flex; flex-direction: column; gap: var(--space-2); width: 100%; }
.skeleton-line {
  height: var(--line-height, 1rem);
  border-radius: var(--radius-sm);
  width: var(--width, 100%);
}

/* Card Skeleton */
.skeleton--card { width: 100%; }
.skeleton-card-inner { padding: var(--space-5); }
.skeleton-header { height: 24px; border-radius: var(--radius-sm); }
.skeleton-content { height: 16px; border-radius: var(--radius-sm); margin-top: var(--space-3); }

/* Chart Skeleton */
.skeleton--chart { width: 100%; }
.skeleton-chart {
  height: var(--height, 200px);
  border-radius: var(--radius-lg);
}

/* Table Skeleton */
.skeleton--table { width: 100%; }
.skeleton-table { height: var(--table-height, auto); }
.skeleton-table-header {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}
.skeleton-table-row {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}
.skeleton-table-row:last-child { border-bottom: none; border-radius: 0 0 var(--radius-md) var(--radius-md); }
.skeleton-cell {
  flex: 1;
  height: 16px;
  border-radius: var(--radius-sm);
}

/* Avatar Skeleton */
.skeleton--avatar { border-radius: var(--radius-full); }
.skeleton-avatar {
  width: var(--size, 40px);
  height: var(--size, 40px);
  border-radius: var(--radius-full);
}

/* Button Skeleton */
.skeleton--button { }
.skeleton-button {
  width: var(--button-width, 120px);
  height: var(--button-height, 36px);
  border-radius: var(--radius-md);
}

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .skeleton--animated { animation: none; }
}
</style>