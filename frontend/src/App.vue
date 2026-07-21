<template>
  <AppLayout
    :nav-items="navItems"
    :connection-status="connectionStatus"
    :page-title="$route.meta.title"
    :page-description="$route.meta.description"
  >
    <template #page-header-actions>
      <slot name="page-header-actions" />
    </template>

    <template #default>
      <transition name="page" mode="out-in">
        <router-view />
      </transition>
    </template>
  </AppLayout>

  <!-- Toast Container (Global) -->
  <Teleport to="body">
    <AppToast position="top-right" :max-visible="5" default-duration="4000" />
  </Teleport>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePortfolioStore } from '@/stores/portfolio'
import { useToastStore } from '@/stores/toast'
import { useTaskStore } from '@/stores/task'
import AppLayout from '@/components/layout/AppLayout.vue'
import AppToast from '@/components/ui/AppToast.vue'
import TaskIndicator from '@/components/TaskIndicator.vue'

const route = useRoute()
const router = useRouter()
const portfolioStore = usePortfolioStore()
const toastStore = useToastStore()
const taskStore = useTaskStore()

const navItems = [
  { path: '/', label: 'Dashboard', icon: '📊' },
  { path: '/portfolio-analysis', label: '组合分析', icon: '📈' },
  { path: '/market-analysis', label: '行情分析', icon: '📰' },
  { path: '/news', label: '资讯监控', icon: '📋' },
  { path: '/token-monitor', label: 'Token监控', icon: '🔑' }
]

const connectionStatus = ref('connecting')
const connectionStatusText = computed(() => {
  const map = {
    connected: '实时连接正常',
    connecting: '连接中...',
    disconnected: '未连接',
    error: '连接异常'
  }
  return map[connectionStatus.value] || '未知状态'
})

// Initialize WebSocket connection status
onMounted(() => {
  // Listen to portfolio store connection status
  const unsubscribe = portfolioStore.$subscribe((mutation, state) => {
    if (mutation.type === 'direct') return
    connectionStatus.value = state.wsConnected ? 'connected' : 'disconnected'
  })

  // Initial check
  connectionStatus.value = portfolioStore.wsConnected ? 'connected' : 'connecting'

  // Cleanup on unmount (not needed in Vue 3 setup but good practice)
})
</script>

<style scoped>
/* Page Transition */
.page-enter-active,
.page-leave-active {
  transition: opacity var(--duration-normal) var(--ease-out),
              transform var(--duration-normal) var(--ease-out);
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* Skip Link (Accessibility) */
.skip-link {
  position: absolute;
  top: -100%;
  left: 50%;
  transform: translateX(-50%);
  padding: var(--space-3) var(--space-6);
  background: var(--color-brand-600);
  color: white;
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-md);
  z-index: var(--z-index-max);
  transition: top var(--duration-fast) var(--ease-out);
}

.skip-link:focus {
  top: var(--space-4);
}
</style>