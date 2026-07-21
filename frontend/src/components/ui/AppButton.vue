<template>
  <button
    :class="buttonClasses"
    :disabled="disabled || loading"
    :type="type"
    :aria-busy="loading"
    :aria-disabled="disabled || loading"
    @click="handleClick"
  >
    <span v-if="loading" class="btn__loader" aria-hidden="true">
      <svg class="btn__spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
        <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
      </svg>
    </span>
    <span v-else-if="icon" class="btn__icon" aria-hidden="true">{{ icon }}</span>
    <slot />
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'primary',
    validator: v => ['primary', 'secondary', 'ghost', 'danger', 'success', 'outline'].includes(v)
  },
  size: {
    type: String,
    default: 'md',
    validator: v => ['xs', 'sm', 'md', 'lg'].includes(v)
  },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  type: { type: String, default: 'button', validator: v => ['button', 'submit', 'reset'].includes(v) },
  icon: { type: String, default: '' },
  fullWidth: { type: Boolean, default: false },
  block: { type: Boolean, default: false }
})

const emit = defineEmits(['click'])

const buttonClasses = computed(() => [
  'btn',
  `btn--${props.variant}`,
  `btn--${props.size}`,
  { 'btn--full': props.fullWidth || props.block, 'btn--loading': props.loading, 'btn--disabled': props.disabled }
])

function handleClick(event) {
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
  outline: none;
}

.btn:focus-visible {
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

/* Primary */
.btn--primary {
  background: var(--color-brand-600);
  color: white;
}

.btn--primary:hover:not(:disabled) {
  background: var(--color-brand-700);
}

.btn--primary:active:not(:disabled) {
  background: var(--color-brand-800);
}

/* Secondary */
.btn--secondary {
  background: var(--color-surface-secondary);
  color: var(--color-text-primary);
  border-color: var(--color-border-light);
}

.btn--secondary:hover:not(:disabled) {
  background: var(--color-surface-hover);
  border-color: var(--color-border-medium);
}

/* Ghost */
.btn--ghost {
  background: transparent;
  color: var(--color-text-secondary);
}

.btn--ghost:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

/* Danger */
.btn--danger {
  background: var(--color-danger-600);
  color: white;
}

.btn--danger:hover:not(:disabled) {
  background: var(--color-danger-700);
}

/* Success */
.btn--success {
  background: var(--color-success-600);
  color: white;
}

.btn--success:hover:not(:disabled) {
  background: var(--color-success-700);
}

/* Outline */
.btn--outline {
  background: transparent;
  color: var(--color-brand-600);
  border-color: var(--color-brand-300);
}

.btn--outline:hover:not(:disabled) {
  background: var(--color-bg-brand-subtle);
  border-color: var(--color-brand-500);
}

/* Loader */
.btn__loader {
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn__spinner {
  width: 16px;
  height: 16px;
  animation: btn-spin 1s linear infinite;
}

@keyframes btn-spin {
  to { transform: rotate(360deg); }
}

/* Icon */
.btn__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1em;
  line-height: 1;
}
</style>