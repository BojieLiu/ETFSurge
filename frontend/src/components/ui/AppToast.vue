<template>
  <TransitionGroup name="toast" tag="div" class="toast__container">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :class="[
        'toast',
        `toast--${toast.type}`,
        `toast--${position.split('-')[0]}`,
        `toast--${position.split('-')[1] || 'center'}`,
        { 'toast--closable': toast.closable !== false }
      ]"
      role="alert"
      :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
      :aria-atomic="true"
    >
      <div class="toast__content">
        <div class="toast__icon" aria-hidden="true">
          <component :is="iconComponent" v-if="toast.type" />
        </div>
        <div class="toast__message">
          <p v-if="toast.title" class="toast__title">{{ toast.title }}</p>
          <p v-if="toast.message" class="toast__text">{{ toast.message }}</p>
        </div>
        <button
          v-if="toast.closable !== false"
          class="toast__close"
          @click="remove(toast.id)"
          :aria-label="t('toast.close')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
      
      <div
        v-if="toast.duration && toast.duration > 0"
        class="toast__progress"
        :style="progressStyle(toast)"
      />
    </div>
  </TransitionGroup>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  position: {
    type: String,
    default: 'top-right',
    validator: v => ['top-left', 'top-center', 'top-right', 'bottom-left', 'bottom-center', 'bottom-right'].includes(v)
  },
  maxVisible: { type: Number, default: 5 },
  defaultDuration: { type: Number, default: 4000 },
  gap: { type: Number, default: 8 }
})

const toasts = ref([])

const t = (key) => {
  const dict = { 'toast.close': '关闭' }
  return dict[key] || key
}

const iconComponent = computed(() => {
  return {
    success: 'toast-icon-success',
    danger: 'toast-icon-danger',
    warning: 'toast-icon-warning',
    info: 'toast-icon-info'
  }
})

function add(toast) {
  const id = Date.now() + Math.random()
  const newToast = {
    id,
    type: 'info',
    title: '',
    message: '',
    duration: props.defaultDuration,
    closable: true,
    ...toast
  }
  
  toasts.value.push(newToast)
  
  // Limit max visible
  if (toasts.value.length > props.maxVisible) {
    toasts.value.shift()
  }
  
  // Auto remove
  if (newToast.duration && newToast.duration > 0) {
    setTimeout(() => remove(id), newToast.duration)
  }
  
  return id
}

function remove(id) {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}

function clear() {
  toasts.value = []
}

function progressStyle(toast) {
  return {
    transitionDuration: `${toast.duration}ms`,
    transform: 'scaleX(0)',
    transitionTimingFunction: 'linear'
  }
}

// Global methods
const toastApi = {
  success: (message, title, options) => add({ type: 'success', message, title, ...options }),
  danger: (message, title, options) => add({ type: 'danger', message, title, ...options }),
  error: (message, title, options) => add({ type: 'danger', message, title, ...options }),
  warning: (message, title, options) => add({ type: 'warning', message, title, ...options }),
  info: (message, title, options) => add({ type: 'info', message, title, ...options }),
  remove,
  clear
}

defineExpose(toastApi)
</script>

<style scoped>
.toast__container {
  position: fixed;
  z-index: var(--z-index-toast);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  pointer-events: none;
  max-width: 380px;
}

.toast__container--top { top: var(--space-4); }
.toast__container--bottom { bottom: var(--space-4); }
.toast__container--left { left: var(--space-4); align-items: flex-start; }
.toast__container--center { left: 50%; transform: translateX(-50%); align-items: center; }
.toast__container--right { right: var(--space-4); align-items: flex-end; }

.toast {
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  min-width: 280px;
  max-width: 380px;
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  animation: toast-in var(--duration-normal) var(--ease-spring);
}

.toast-enter-active { animation: toast-in var(--duration-normal) var(--ease-spring); }
.toast-leave-active { animation: toast-out var(--duration-fast) var(--ease-in); }

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateX(100%) scale(0.9);
  }
  to {
    opacity: 1;
    transform: translateX(0) scale(1);
  }
}

@keyframes toast-out {
  to {
    opacity: 0;
    transform: translateX(100%) scale(0.9);
  }
}

.toast__content {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.toast__icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
}

.toast__icon svg {
  width: 24px;
  height: 24px;
}

.toast--success .toast__icon { color: var(--color-success-500); }
.toast--danger .toast__icon { color: var(--color-danger-500); }
.toast--warning .toast__icon { color: var(--color-warning-500); }
.toast--info .toast__icon { color: var(--color-brand-500); }

.toast__message {
  flex: 1;
  min-width: 0;
}

.toast__title {
  margin: 0 0 var(--space-1);
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.toast__text {
  margin: 0;
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.toast__close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: var(--transition-fast);
  margin-top: -4px;
  margin-right: -4px;
}

.toast__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.toast__close:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.toast__progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 3px;
  width: 100%;
  background: currentColor;
  opacity: 0.3;
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  transform-origin: left center;
  transform: scaleX(1);
}

.toast--success { border-left: 3px solid var(--color-success-500); }
.toast--danger { border-left: 3px solid var(--color-danger-500); }
.toast--warning { border-left: 3px solid var(--color-warning-500); }
.toast--info { border-left: 3px solid var(--color-brand-500); }
</style>