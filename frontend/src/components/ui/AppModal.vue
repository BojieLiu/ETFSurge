<template>
  <Transition name="modal-overlay">
    <div
      v-if="modelValue"
      class="modal__overlay"
      @click="handleOverlayClick"
      :aria-hidden="!modelValue"
    />
  </Transition>

  <Transition name="modal">
    <div
      v-if="modelValue"
      :id="modalId"
      class="modal"
      :class="[`modal--${size}`, { 'modal--fullscreen': fullscreen }]"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="title ? titleId : undefined"
      :aria-describedby="descriptionId"
      @keydown.esc="handleEsc"
    >
      <div class="modal__container">
        <header v-if="title || $slots.header" class="modal__header">
          <h2 v-if="title" :id="titleId" class="modal__title">{{ title }}</h2>
          <slot name="header" />
          <button
            v-if="closable"
            class="modal__close"
            @click="close"
            :aria-label="t('modal.close')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </header>

        <div class="modal__body">
          <slot />
        </div>

        <footer v-if="$slots.footer || (showConfirm && !loading)" class="modal__footer">
          <slot name="footer">
            <div class="modal__footer-actions">
              <AppButton
                v-if="showCancel"
                variant="ghost"
                size="sm"
                @click="close"
                :disabled="loading"
              >
                {{ cancelText }}
              </AppButton>
              <AppButton
                v-if="showConfirm"
                :variant="confirmVariant"
                size="sm"
                :loading="loading"
                @click="confirm"
                :disabled="loading"
              >
                {{ confirmText }}
              </AppButton>
            </div>
          </slot>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import AppButton from './AppButton.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: String,
  description: String,
  size: {
    type: String,
    default: 'md',
    validator: v => ['sm', 'md', 'lg', 'xl', 'full'].includes(v)
  },
  fullscreen: { type: Boolean, default: false },
  closable: { type: Boolean, default: true },
  closeOnOverlayClick: { type: Boolean, default: true },
  closeOnEsc: { type: Boolean, default: true },
  showConfirm: { type: Boolean, default: false },
  showCancel: { type: Boolean, default: false },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  confirmVariant: { type: String, default: 'primary' },
  loading: { type: Boolean, default: false },
  destroyOnClose: { type: Boolean, default: false },
  trapFocus: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel', 'close'])

const modalId = `modal-${Math.random().toString(36).slice(2, 9)}`
const titleId = `${modalId}-title`
const descriptionId = `${modalId}-description`

let lastFocusedElement = null
let focusTrapCleanup = null

const t = (key) => {
  const dict = { 'modal.close': '关闭' }
  return dict[key] || key
}

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function confirm() {
  emit('confirm')
}

function cancel() {
  emit('cancel')
  close()
}

function handleOverlayClick() {
  if (props.closeOnOverlayClick) close()
}

function handleEsc(event) {
  if (props.closeOnEsc && event.key === 'Escape') close()
}

function activateFocusTrap() {
  if (!props.trapFocus) return
  
  const modal = document.getElementById(modalId)
  if (!modal) return

  const focusableElements = modal.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  )
  const firstElement = focusableElements[0]
  const lastElement = focusableElements[focusableElements.length - 1]

  function handleTab(e) {
    if (e.key !== 'Tab') return

    if (e.shiftKey) {
      if (document.activeElement === firstElement) {
        e.preventDefault()
        lastElement?.focus()
      }
    } else {
      if (document.activeElement === lastElement) {
        e.preventDefault()
        firstElement?.focus()
      }
    }
  }

  modal.addEventListener('keydown', handleTab)
  firstElement?.focus()

  return () => modal.removeEventListener('keydown', handleTab)
}

watch(() => props.modelValue, (open) => {
  if (open) {
    lastFocusedElement = document.activeElement
    document.body.style.overflow = 'hidden'
    document.body.setAttribute('data-modal-open', 'true')
    nextTick(() => {
      focusTrapCleanup = activateFocusTrap()
    })
  } else {
    document.body.style.overflow = ''
    document.body.removeAttribute('data-modal-open')
    focusTrapCleanup?.()
    lastFocusedElement?.focus()
  }
})

onMounted(() => {
  if (props.modelValue) {
    document.body.style.overflow = 'hidden'
    document.body.setAttribute('data-modal-open', 'true')
  }
})

onUnmounted(() => {
  document.body.style.overflow = ''
  document.body.removeAttribute('data-modal-open')
})

</script>

<style scoped>
.modal__overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-index-modal-backdrop);
  background: var(--modal-backdrop);
  opacity: 0;
  animation: modal-overlay-in var(--duration-normal) var(--ease-out) forwards;
}

@keyframes modal-overlay-in {
  to { opacity: 1; }
}

.modal-overlay-leave-active {
  animation: modal-overlay-out var(--duration-fast) var(--ease-in) forwards;
}

@keyframes modal-overlay-out {
  to { opacity: 0; }
}

.modal {
  position: fixed;
  inset: 0;
  z-index: var(--z-index-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  pointer-events: none;
}

.modal__container {
  pointer-events: auto;
  width: 100%;
  max-width: var(--modal-width-md);
  max-height: var(--modal-max-height);
  background: var(--color-surface-primary);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  opacity: 0;
  transform: scale(0.95) translateY(20px);
  animation: modal-in var(--duration-normal) var(--ease-out) forwards;
}

@keyframes modal-in {
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-leave-active .modal__container {
  animation: modal-out var(--duration-fast) var(--ease-in) forwards;
}

@keyframes modal-out {
  to {
    opacity: 0;
    transform: scale(0.95) translateY(-20px);
  }
}

/* Sizes */
.modal--sm .modal__container { max-width: var(--modal-width-sm); }
.modal--md .modal__container { max-width: var(--modal-width-md); }
.modal--lg .modal__container { max-width: var(--modal-width-lg); }
.modal--xl .modal__container { max-width: var(--modal-width-xl); }
.modal--full .modal__container { max-width: var(--modal-width-full); }
.modal--fullscreen .modal__container {
  max-width: 100%;
  max-height: 100%;
  height: 100%;
  border-radius: 0;
}

.modal__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.modal__title {
  margin: 0;
  font: var(--text-h3);
  color: var(--color-text-primary);
  flex: 1;
}

.modal__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  flex-shrink: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: var(--transition-fast);
}

.modal__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.modal__close:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.modal__body {
  flex: 1;
  overflow: auto;
  padding: var(--space-6);
}

.modal__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.modal__footer-actions {
  display: flex;
  gap: var(--space-3);
  width: 100%;
  justify-content: flex-end;
}

@media (max-width: 480px) {
  .modal {
    padding: 0;
    align-items: flex-end;
  }
  
  .modal__container {
    max-height: 85vh;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
    animation: modal-bottom-in var(--duration-normal) var(--ease-out) forwards;
  }
  
  @keyframes modal-bottom-in {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }
  
  .modal-leave-active .modal__container {
    animation: modal-bottom-out var(--duration-fast) var(--ease-in) forwards;
  }
  
  @keyframes modal-bottom-out {
    to { transform: translateY(100%); }
  }
}
</style>