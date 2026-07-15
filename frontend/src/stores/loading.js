import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useLoadingStore = defineStore('loading', () => {
  const active = ref(false)
  const message = ref('加载中...')

  function show(msg = '加载中...') {
    message.value = msg
    active.value = true
  }

  function hide() {
    active.value = false
    message.value = '加载中...'
  }

  return { active, message, show, hide }
})
