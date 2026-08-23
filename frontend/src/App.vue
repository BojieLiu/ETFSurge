<template>
  <div class="app">
    <!-- Skip link for accessibility -->
    <a href="#main-content" class="skip-link">跳转到主内容</a>

    <!-- Top Navigation -->
    <header class="header" role="banner">
      <nav class="nav container" aria-label="主导航">
        <router-link to="/" class="nav-brand" aria-label="ETF Surge 首页">
          <svg class="nav-logo" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="currentColor"/>
            <path d="M8 20L14 14L24 20" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span>ETF Surge</span>
        </router-link>

        <div class="nav-links" role="navigation" aria-label="页面导航">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="nav-link"
            :class="{ 'nav-link--active': isActiveRoute(item.path) }"
            :aria-current="isActiveRoute(item.path) ? 'page' : undefined"
          >
            <span class="nav-link-icon" aria-hidden="true">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>

        <!-- Connection Status -->
        <div class="nav-status" aria-live="polite" aria-atomic="true">
          <span class="status-indicator" :class="connectionStatus" aria-hidden="true"></span>
          <span class="status-text" v-if="connectionStatusText">{{ connectionStatusText }}</span>
        </div>

        <!-- Warmup Indicator -->
        <div v-if="isWarmingUp" class="nav-warmup" title="数据预热中" aria-label="数据预热中">
          <span class="warmup-dot" aria-hidden="true"></span>
          <span class="warmup-label">预热中</span>
        </div>

        <!-- Global task indicator (Plan A) -->
        <TaskIndicator />
      </nav>
    </header>

    <!-- Main Content -->
    <main id="main-content" class="main" role="main">
      <div class="container">
        <!-- Page Header (injected by views) — F21: 品牌图标 + 标题/描述层级分离 -->
        <header class="page-header" v-if="$route.meta.title">
          <span class="page-header-icon" aria-hidden="true">{{ routeMetaIcon }}</span>
          <div class="page-header-text">
            <h1 class="page-title">{{ $route.meta.title }}</h1>
            <p class="page-description" v-if="$route.meta.description">{{ $route.meta.description }}</p>
          </div>
        </header>

        <!-- Router View with Transition -->
        <transition name="page" mode="out-in">
          <router-view />
        </transition>
      </div>
    </main>

    <!-- Toast Container -->
    <div class="toast-container" role="region" aria-label="通知" aria-live="polite" aria-atomic="true">
      <TransitionGroup name="toast" tag="div" class="toast-list">
        <div
          v-for="toast in toastStore.toasts"
          :key="toast.id"
          :class="['toast', `toast--${toast.type}`]"
          role="alert"
          :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
        >
          <span class="toast-icon" aria-hidden="true">
            <component :is="toastIcons[toast.type]" />
          </span>
          <span class="toast-message">{{ toast.msg }}</span>
          <button
            class="toast-close"
            @click="dismissToast(toast.id)"
            aria-label="关闭通知"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useToastStore } from './stores/toast'
import { useTaskStore } from './stores/task'
import { useMarketStore } from './stores/market'
import { useWarmupStatus } from './composables/useWarmupStatus'
import { useTaskWS } from './composables/useTaskWS'
import TaskIndicator from './components/TaskIndicator.vue'

const router = useRouter()
const route = useRoute()
const toastStore = useToastStore()
const marketStore = useMarketStore()

// Warmup status (global — used in nav-bar indicator)
const { isWarmingUp, startPolling, stopPolling } = useWarmupStatus()

// Navigation items
const navItems = [
  { path: '/', label: 'Dashboard', icon: '📊' },
  { path: '/portfolio-analysis', label: '组合与分析', icon: '📁' },
  { path: '/market-analysis', label: '行情分析', icon: '📰' },
  { path: '/news', label: '资讯', icon: '🗞️' },
  { path: '/token-monitor', label: 'Token 监控', icon: '🔑' },
  { path: '/source-monitor', label: '数据源', icon: '📡' },
  { path: '/admin/config', label: '配置', icon: '⚙️' }
]

const isActiveRoute = (path) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

// F21 (round6 §16.9): 页头品牌图标——按路由 title 映射（回退 📈）
const PAGE_ICONS = {
  Dashboard: '📊',
  '组合与分析': '📁',
  '行情分析': '📰',
  '资讯': '🗞️',
  'Token 监控': '🔑',
  '数据源': '📡',
  '配置': '⚙️',
}
const routeMetaIcon = computed(() => {
  const t = route.meta?.title
  return (t && PAGE_ICONS[t]) || '📈'
})

// round19 P6-① (2026-08-12 方案 A，用户已确认): 连接生命周期提升至 App.vue——
// WS 全站常驻（轻量单连接 + 30s heartbeat），导航栏状态真实反映通道健康，
// 非首页页面不再显示「离线」（旧实现连接绑定 Dashboard 挂载，离开首页即断连）。
// 展示与连接同生命周期；Dashboard 等页面通过 onWSMessage 注册/注销消费回调。
const connectionStatus = computed(() => {
  switch (marketStore.wsStatus) {
    case 'connected': return 'connected'
    case 'connecting':
    case 'reconnecting': return 'connecting'
    default: return 'idle' // idle / stopped —— 中性态，不渲染「离线」
  }
})
const connectionStatusText = computed(() => {
  switch (marketStore.wsStatus) {
    case 'connected': return '已连接'
    case 'connecting': return '连接中...'
    case 'reconnecting': return '连接中...'
    case 'stopped': return '行情连接未启用'
    case 'idle': return ''
    default: return '行情通道异常'
  }
})

// Toast icons
const toastIcons = {
  success: {
    template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`
  },
  error: {
    template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`
  },
  warning: {
    template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
  },
  info: {
    template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
  }
}

const dismissToast = (id) => {
  toastStore.dismiss(id)
}

// ── Global task-notification WebSocket (P2-4: 收敛到 useTaskWS composable) ──
// 单条持久连接驱动导航栏任务指示器；连接/回填/节流/自动建任务/重连逻辑
// 已抽取至 composables/useTaskWS.js（对齐 useNewsWS 模式）。
const taskStore = useTaskStore()
const { connect: connectTaskWs, close: closeTaskWs } = useTaskWS()

// Start warmup polling on mount, stop on unmount
onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})

onMounted(() => {
  // Initial fetch: load any tasks that existed before this page load
  taskStore.fetchAndMergeTasks()
  connectTaskWs()
  // round19 P6-①: 全站常驻行情连接（方案 A）——Dashboard 不再 connect/disconnect
  marketStore.connectWS()
})

onUnmounted(() => {
  closeTaskWs()
  marketStore.disconnectWS()
})
</script>

<style scoped>
/* ==========================================
   App Layout
   ========================================== */
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-family: var(--font-family-sans);
  font-size: var(--font-size-base);
  line-height: var(--line-height-normal);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Skip Link */
.skip-link {
  position: absolute;
  top: -100%;
  left: var(--space-4);
  padding: var(--space-2) var(--space-4);
  background: var(--color-brand-600);
  color: white;
  border-radius: var(--radius-md);
  z-index: var(--z-index-max);
  text-decoration: none;
  font-weight: var(--font-weight-medium);
  transition: top var(--transition-fast);
}
.skip-link:focus {
  top: var(--space-4);
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* ==========================================
   Header / Navigation
   ========================================== */
.header {
  position: sticky;
  top: 0;
  z-index: var(--z-index-fixed);
  background: var(--color-surface-primary);
  border-bottom: 1px solid var(--color-border-light);
  backdrop-filter: blur(8px);
  background: rgba(255, 255, 255, 0.9);
}

@media (prefers-color-scheme: dark) {
  .header {
    background: rgba(15, 23, 42, 0.9);
    border-bottom-color: var(--color-border-light);
  }
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  height: 60px;
}

.nav-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font: var(--text-h3);
  color: var(--color-brand-600);
  text-decoration: none;
  white-space: nowrap;
}

.nav-brand:hover {
  color: var(--color-brand-700);
}

.nav-brand:focus-visible {
  outline: none;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-focus);
}

.nav-logo {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.nav-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  text-decoration: none;
  transition: var(--transition-fast);
  white-space: nowrap;
}

.nav-link:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}

.nav-link--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.nav-link--active:hover {
  color: var(--color-brand-700);
  background: var(--color-brand-100);
}

.nav-link-icon {
  font-size: var(--font-size-base);
  line-height: 1;
}

.nav-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  font: var(--text-caption);
  color: var(--color-text-tertiary);
  border-radius: var(--radius-full);
  background: var(--color-surface-tertiary);
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.status-indicator.connected {
  background: var(--color-success-600);
  box-shadow: 0 0 0 2px var(--color-bg-success-subtle);
}

.status-indicator.connecting {
  background: var(--color-warning-600);
  animation: pulse 1.5s ease-in-out infinite;
}

.status-indicator.disconnected {
  background: var(--color-danger-600);
}

/* round19 P6-②: 中性态（idle/stopped）——灰点，不再以红色「离线」暗示故障 */
.status-indicator.idle {
  background: var(--color-text-tertiary);
  opacity: 0.55;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Nav Warmup Indicator */
.nav-warmup {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  font: var(--text-caption);
  color: var(--color-text-warning);
  background: var(--color-bg-warning-subtle);
  border-radius: var(--radius-full);
  white-space: nowrap;
}
.warmup-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-warning-500);
  animation: warmup-pulse-dot 1.5s ease-in-out infinite;
}
@keyframes warmup-pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.warmup-label { font-weight: var(--font-weight-medium); }

/* ==========================================
   Main Content
   ========================================== */
.main {
  flex: 1;
  width: 100%;
  padding: var(--space-6) 0;
  /* F13: reserve vertical space for async route views so loading them
     does not collapse the layout and shift surrounding elements (CLS). */
  min-height: 70vh;
}

.container {
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 var(--space-4);
}

@media (min-width: 640px) {
  .container { padding: 0 var(--space-6); }
}

@media (min-width: 1024px) {
  .container { padding: 0 var(--space-8); }
}

/* Page Header — F21 (round6 §16.9): 标题放大加粗 + 描述缩小浅灰 + 间距拉开
   层级分离；品牌主色 + 左侧图标；标题下方细分隔线。 */
.page-header {
  margin-bottom: var(--space-6);
  padding: var(--space-4) 0 var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  border-bottom: 2px solid var(--color-brand-200, rgba(37, 99, 235, 0.15));
}

.page-header-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg, 12px);
  background: var(--color-brand-50, rgba(37, 99, 235, 0.08));
  color: var(--color-brand-700);
  font-size: 22px;
  flex-shrink: 0;
}

.page-header-text {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.page-title {
  font-size: calc(var(--font-size-2xl, 1.75rem) + 2px);
  font-weight: 800;
  line-height: var(--line-height-tight);
  color: var(--color-text-primary);
  letter-spacing: var(--letter-spacing-tight);
  margin: 0;
}

.page-description {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  opacity: 0.85;
  line-height: var(--line-height-relaxed);
}

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

/* ==========================================
   Toast Notifications
   ========================================== */
.toast-container {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  z-index: var(--z-index-toast);
  pointer-events: none;
}

.toast-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  pointer-events: auto;
}

.toast {
  display: inline-flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  min-width: 280px;
  max-width: 420px;
  font-size: var(--font-size-sm);
  line-height: var(--line-height-normal);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  animation: toast-in var(--duration-normal) var(--ease-spring);
}

.toast--success {
  border-color: var(--color-success-200);
  background: var(--color-bg-success-subtle);
  color: var(--color-text-success);
}

.toast--error {
  border-color: var(--color-danger-200);
  background: var(--color-bg-danger-subtle);
  color: var(--color-text-danger);
}

.toast--warning {
  border-color: var(--color-warning-200);
  background: var(--color-bg-warning-subtle);
  color: var(--color-text-warning);
}

.toast--info {
  border-color: var(--color-info-200);
  background: var(--color-bg-info-subtle);
  color: var(--color-text-info);
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateX(100%) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateX(0) scale(1);
  }
}

.toast-leave-active {
  position: absolute;
  right: 0;
  animation: toast-out var(--duration-fast) var(--ease-in) forwards;
}

@keyframes toast-out {
  to {
    opacity: 0;
    transform: translateX(100%) scale(0.95);
  }
}

.toast-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}

.toast--success .toast-icon { color: var(--color-success-600); }
.toast--error .toast-icon { color: var(--color-danger-600); }
.toast--warning .toast-icon { color: var(--color-warning-600); }
.toast--info .toast-icon { color: var(--color-info-600); }

.toast-message {
  flex: 1;
  word-break: break-word;
}

.toast-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  color: inherit;
  opacity: 0.5;
  border-radius: var(--radius-sm);
  transition: var(--transition-fast);
  flex-shrink: 0;
}

.toast-close:hover {
  opacity: 1;
  background: rgba(0, 0, 0, 0.05);
}

.toast-close:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* ==========================================
   Responsive
   ========================================== */
@media (max-width: 768px) {
  .nav-links {
    display: none;
  }

  .nav-status .status-text {
    display: none;
  }

  .nav-warmup { display: none; }

  .page-title { font-size: var(--font-size-xl); }
  .main { padding: var(--space-4) 0; }
  .toast { min-width: auto; max-width: calc(100vw - var(--space-8)); }
}

@media (max-width: 480px) {
  .nav-brand span { display: none; }
  .container { padding: 0 var(--space-3); }
}
</style>