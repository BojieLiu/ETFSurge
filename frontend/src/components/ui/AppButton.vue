<template>
  <button
    :class="buttonClasses"
    :disabled="disabled || loading"
    :type="type"
    :aria-busy="loading"
    :aria-disabled="disabled || loading"
    @click="handleClick"
  >
    <span v-if="loading" class="btn-loader" aria-hidden="true">
      <svg class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
        <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
      </svg>
    </span>
    <span v-else-if="icon" class="btn-icon" aria-hidden="true">{{ icon }}</span>
    <slot />
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: (v) => ['primary', 'secondary', 'ghost', 'danger', 'success'].includes(v)
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['xs', 'sm', 'md', 'lg'].includes(v)
  },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  type: { type: String, default: 'button', validator: (v) => ['button', 'submit', 'reset'].includes(v) },
  icon: { type: String, default: '' },
  fullWidth: { type: Boolean, default: false }
})

const emit = defineEmits(['click'])

const buttonClasses = computed(() => [
  'btn',
  `btn--${props.variant}`,
  `btn--${props.size}`,
  { 'btn--full': props.fullWidth, 'btn--loading': props.loading, 'btn--disabled': props.disabled }
])

const handleClick = (event) => {
  if (!props.disabled && !props.loading) {
    emit('click', event)
  }
}
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: var(--font-family-sans);
  font-weight: var(--font-weight-semibold);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: var(--transition-fast);
  white-space: nowrap;
  user-select: none;
  text-decoration: none;
}

.btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.btn:disabled,
.btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--loading {
  color: transparent !important;
  pointer-events: none;
}

.btn--full { width: 100%; }

/* Sizes */
.btn--xs {
  height: 28px;
  padding: 0 var(--space-2);
  font-size: var(--font-size-xs);
  gap: var(--space-1);
}

.btn--sm {
  height: var(--btn-height-sm);
  padding: 0 var(--btn-padding-x-sm);
  font-size: var(--btn-font-size-sm);
  gap: var(--space-1);
}

.btn--md {
  height: var(--btn-height-md);
  padding: 0 var(--btn-padding-x-md);
  font-size: var(--btn-font-size-md);
}

.btn--lg {
  height: var(--btn-height-lg);
  padding: 0 var(--btn-padding-x-lg);
  font-size: var(--btn-font-size-lg);
}

/* Variants */
.btn--primary {
  color: var(--color-text-inverse);
  background: var(--color-brand-600);
  border-color: var(--color-brand-600);
}

.btn--primary:hover:not(:disabled) {
  background: var(--color-brand-700);
  border-color: var(--color-brand-700);
}

.btn--primary:active:not(:disabled) {
  background: var(--color-brand-800);
  border-color: var(--color-brand-800);
}

.btn--secondary {
  color: var(--color-text-primary);
  background: var(--color-surface-primary);
  border-color: var(--color-border-medium);
}

.btn--secondary:hover:not(:disabled) {
  background: var(--color-surface-hover);
  border-color: var(--color-border-strong);
}

.btn--secondary:active:not(:disabled) {
  background: var(--color-surface-active);
}

.btn--ghost {
  color: var(--color-text-secondary);
  background: transparent;
  border-color: transparent;
}

.btn--ghost:hover:not(:disabled) {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}

.btn--ghost:active:not(:disabled) {
  background: var(--color-surface-active);
}

.btn--danger {
  color: var(--color-text-inverse);
  background: var(--color-danger-600);
  border-color: var(--color-danger-600);
}

.btn--danger:hover:not(:disabled) {
  background: var(--color-danger-700);
  border-color: var(--color-danger-700);
}

.btn--success {
  color: var(--color-text-inverse);
  background: var(--color-success-600);
  border-color: var(--color-success-600);
}

.btn--success:hover:not(:disabled) {
  background: var(--color-success-700);
  border-color: var(--color-success-700);
}

/* Icons */
.btn-icon {
  display: inline-flex;
  flex-shrink: 0;
  line-height: 1;
}

.btn--xs .btn-icon { font-size: 10px; }
.btn--sm .btn-icon { font-size: 12px; }
.btn--md .btn-icon { font-size: 14px; }
.btn--lg .btn-icon { font-size: 16px; }

/* Loader */
.btn-loader {
  display: inline-flex;
  width: 1em;
  height: 1em;
}

.spinner {
  width: 100%;
  height: 100%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>