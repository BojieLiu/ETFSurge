import { ref } from 'vue'

const toasts = ref([])
let _id = 0

export function useToast() {
  function toast(msg, type = 'info', duration = 3000) {
    const id = ++_id
    toasts.value.push({ id, msg, type })
    setTimeout(() => {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }, duration)
  }
  return { toasts, toast }
}
