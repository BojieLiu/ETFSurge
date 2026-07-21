// Toast Plugin - 全局 Toast 管理
import { reactive, ref } from 'vue'
import AppToast from '@/components/ui/AppToast.vue'

const toasts = reactive([])
let toastId = 0

function addToast(toast) {
  const id = ++toastId
  const newToast = {
    id,
    type: 'info',
    title: '',
    message: '',
    duration: 4000,
    closable: true,
    createdAt: Date.now(),
    ...toast
  }
  toasts.push(newToast)

  // Limit max visible
  if (toasts.length > 5) {
    toasts.shift()
  }

  if (newToast.duration && newToast.duration > 0) {
    setTimeout(() => removeToast(id), newToast.duration)
  }

  return id
}

function removeToast(id) {
  const index = toasts.findIndex(t => t.id === id)
  if (index !== -1) {
    toasts.splice(index, 1)
  }
}

function clearToasts() {
  toasts.length = 0
}

const toastApi = {
  success: (message, title, options) => addToast({ type: 'success', message, title, ...options }),
  error: (message, title, options) => addToast({ type: 'error', message, title, ...options }),
  danger: (message, title, options) => addToast({ type: 'error', message, title, ...options }),
  warning: (message, title, options) => addToast({ type: 'warning', message, title, ...options }),
  info: (message, title, options) => addToast({ type: 'info', message, title, ...options }),
  remove: removeToast,
  clear: clearToasts
}

export default {
  install(app) {
    // Provide globally
    app.provide('toast', toastApi)
    app.provide('toasts', toasts)

    // Register global component
    app.component('AppToast', AppToast)

    // Global properties (Vue 2 style, for backward compatibility)
    app.config.globalProperties.$toast = toastApi
  }
}

export { toastApi, toasts }