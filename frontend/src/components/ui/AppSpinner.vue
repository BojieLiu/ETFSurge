<template>
  <div
    class="spinner"
    :class="[`spinner--${size}`, { 'spinner--inline': inline }]"
    :style="{ width: sizeValue, height: sizeValue }"
    role="status"
    :aria-label="label || '加载中'"
    aria-live="polite"
  >
    <svg class="spinner__svg" viewBox="0 0 50 50" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle
        class="spinner__track"
        cx="25"
        cy="25"
        r="20"
        stroke="currentColor"
        stroke-width="4"
        stroke-opacity="0.15"
      />
      <circle
        class="spinner__indicator"
        cx="25"
        cy="25"
        r="20"
        stroke="currentColor"
        stroke-width="4"
        stroke-linecap="round"
        stroke-dasharray="31.4 94.25"
        stroke-dashoffset="0"
        transform="rotate(-90 25 25)"
      />
    </svg>
    <span v-if="label && !inline" class="spinner__label">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: {
    type: String,
    default: 'md',
    validator: v => ['xs', 'sm', 'md', 'lg', 'xl'].includes(v)
  },
  label: String,
  inline: { type: Boolean, default: false },
  color: String
})

const sizeMap = {
  xs: '16px',
  sm: '24px',
  md: '32px',
  lg: '48px',
  xl: '64px'
}

const sizeValue = computed(() => sizeMap[props.size] || '32px')
</script>

<style scoped>
.spinner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
  color: var(--color-brand-500);
}

.spinner--inline {
  flex-direction: row;
  gap: var(--space-2);
}

.spinner__svg {
  width: 100%;
  height: 100%;
  animation: spinner-rotate 1s linear infinite;
}

@keyframes spinner-rotate {
  to { transform: rotate(360deg); }
}

.spinner__track {
  animation: spinner-dash 1.5s ease-in-out infinite;
}

@keyframes spinner-dash {
  0% {
    stroke-dasharray: 1, 150;
    stroke-dashoffset: 0;
  }
  50% {
    stroke-dasharray: 90, 150;
    stroke-dashoffset: -35;
  }
  100% {
    stroke-dasharray: 90, 150;
    stroke-dashoffset: -124;
  }
}

.spinner__indicator {
  animation: spinner-dash 1.5s ease-in-out infinite;
}

.spinner__label {
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* Size variations via container size */
.spinner--xs { width: 16px; height: 16px; }
.spinner--sm { width: 24px; height: 24px; }
.spinner--md { width: 32px; height: 32px; }
.spinner--lg { width: 48px; height: 48px; }
.spinner--xl { width: 64px; height: 64px; }

/* Inline label adjustments */
.spinner--inline .spinner__label {
  font-size: var(--font-size-sm);
}
</style>