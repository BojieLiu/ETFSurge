<template>
  <div class="app-layout" :class="{ 'app-layout--has-sidebar': hasSidebar }">
    <!-- Header -->
    <header class="app-header" role="banner">
      <div class="app-header__inner">
        <slot name="header-left">
          <div class="app-header__brand">
            <router-link to="/" class="app-header__logo" aria-label="ETF Surge 首页">
              <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" class="app-header__logo-icon">
                <rect width="32" height="32" rx="8" fill="currentColor"/>
                <path d="M8 20L14 14L24 20" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span class="app-header__logo-text">ETF Surge</span>
            </router-link>
          </div>
        </slot>

        <slot name="header-center">
          <nav class="app-header__nav" aria-label="主导航" v-if="$slots['header-center'] || navItems.length">
            <slot name="header-center">
              <router-link
                v-for="item in navItems"
                :key="item.path"
                :to="item.path"
                class="app-header__nav-link"
                :class="{ 'app-header__nav-link--active': isActiveRoute(item.path) }"
                :aria-current="isActiveRoute(item.path) ? 'page' : undefined"
              >
                <span class="app-header__nav-icon" aria-hidden="true">{{ item.icon }}</span>
                <span>{{ item.label }}</span>
              </router-link>
            </slot>
          </nav>
        </slot>

        <slot name="header-right">
          <div class="app-header__actions">
            <slot name="header-actions">
              <!-- Default: Connection status -->
              <div class="app-header__status" aria-live="polite" aria-atomic="true">
                <span class="status-indicator" :class="connectionStatus"></span>
                <span class="status-text">{{ connectionStatusText }}</span>
              </div>
              
              <!-- Task Indicator -->
              <TaskIndicator />
            </slot>
          </div>
        </slot>

        <!-- Mobile Menu Toggle -->
        <button
          v-if="hasSidebar"
          class="app-header__menu-toggle"
          @click="sidebarOpen = !sidebarOpen"
          :aria-expanded="sidebarOpen"
          :aria-controls="sidebarId"
          aria-label="切换侧边栏"
        >
          <svg v-if="!sidebarOpen" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </header>

    <!-- Sidebar Overlay (Mobile) -->
    <div
      v-if="hasSidebar && sidebarOpen"
      class="app-sidebar-overlay"
      @click="sidebarOpen = false"
      aria-hidden="true"
    ></div>

    <!-- Sidebar -->
    <aside
      v-if="hasSidebar"
      :id="sidebarId"
      class="app-sidebar"
      :class="{ 'app-sidebar--open': sidebarOpen, 'app-sidebar--collapsed': sidebarCollapsed }"
      role="navigation"
      aria-label="侧边栏导航"
    >
      <div class="app-sidebar__inner">
        <slot name="sidebar">
          <nav class="app-sidebar__nav" v-if="navItems.length">
            <router-link
              v-for="item in navItems"
              :key="item.path"
              :to="item.path"
              class="app-sidebar__item"
              :class="{ 'app-sidebar__item--active': isActiveRoute(item.path) }"
              :aria-current="isActiveRoute(item.path) ? 'page' : undefined"
            >
              <span class="app-sidebar__icon" aria-hidden="true">{{ item.icon }}</span>
              <span class="app-sidebar__label" v-if="!sidebarCollapsed">{{ item.label }}</span>
            </router-link>
          </nav>
        </slot>
      </div>
    </aside>

    <!-- Main Content -->
    <main id="main-content" class="app-main" role="main">
      <div class="app-main__inner">
        <!-- Page Header -->
        <header v-if="$slots['page-header'] || pageTitle" class="app-page-header">
          <div class="app-page-header__content">
            <slot name="page-header">
              <div v-if="pageTitle || pageDescription">
                <h1 v-if="pageTitle" class="app-page-header__title">{{ pageTitle }}</h1>
                <p v-if="pageDescription" class="app-page-header__description">{{ pageDescription }}</p>
              </div>
            </slot>
          </div>
          <div class="app-page-header__actions">
            <slot name="page-header-actions" />
          </div>
        </header>

        <!-- Page Content -->
        <div class="app-page">
          <slot />
        </div>
      </div>
    </main>

    <!-- Footer -->
    <footer v-if="$slots.footer" class="app-footer" role="contentinfo">
      <slot name="footer" />
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TaskIndicator from '../components/TaskIndicator.vue'

const props = defineProps({
  navItems: {
    type: Array,
    default: () => []
  },
  pageTitle: String,
  pageDescription: String,
  hasSidebar: { type: Boolean, default: false },
  sidebarCollapsed: { type: Boolean, default: false },
  connectionStatus: {
    type: String,
    default: 'disconnected',
    validator: v => ['connected', 'connecting', 'disconnected', 'error'].includes(v)
  }
})

const emit = defineEmits(['update:sidebarCollapsed', 'sidebarToggle'])

const route = useRoute()
const router = useRouter()
const sidebarOpen = ref(false)
const sidebarId = `app-sidebar-${Math.random().toString(36).slice(2, 9)}`

const connectionStatusText = computed(() => {
  const map = {
    connected: '实时连接正常',
    connecting: '连接中...',
    disconnected: '未连接',
    error: '连接异常'
  }
  return map[props.connectionStatus] || '未知状态'
})

function isActiveRoute(path) {
  return route.path === path || (path !== '/' && route.path.startsWith(path + '/'))
}

function handleResize() {
  if (window.innerWidth >= 1024) {
    sidebarOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  handleResize()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

// Close sidebar on route change (mobile)
watch(() => route.path, () => {
  if (window.innerWidth < 1024) {
    sidebarOpen.value = false
  }
})
</script>

<style scoped>
/* ==========================================
   APP LAYOUT - 应用整体布局
   ========================================== */

.app-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-bg-primary);
}

/* Header */
.app-header {
  position: sticky;
  top: 0;
  z-index: var(--z-index-fixed);
  height: var(--header-height);
  background: var(--color-surface-primary);
  border-bottom: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-xs);
}

.app-header__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  max-width: var(--container-max-xl);
  margin: 0 auto;
  padding: 0 var(--space-padding-md);
  gap: var(--space-gap-md);
}

@media (min-width: 1024px) {
  .app-header__inner {
    padding: 0 var(--space-padding-lg);
  }
}

/* Brand / Logo */
.app-header__brand {
  flex-shrink: 0;
}

.app-header__logo {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-brand-600);
  text-decoration: none;
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-xl);
  font-family: var(--font-family-display);
}

.app-header__logo:hover {
  color: var(--color-brand-700);
}

.app-header__logo:focus-visible {
  outline: none;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-focus);
}

.app-header__logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.app-header__logo-text {
  display: none;
}

@media (min-width: 640px) {
  .app-header__logo-text {
    display: inline;
  }
}

/* Navigation */
.app-header__nav {
  display: none;
  align-items: center;
  gap: var(--space-1);
}

@media (min-width: 768px) {
  .app-header__nav {
    display: flex;
  }
}

.app-header__nav-link {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-md);
  text-decoration: none;
  transition: var(--transition-fast);
  white-space: nowrap;
}

.app-header__nav-link:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}

.app-header__nav-link--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.app-header__nav-icon {
  font-size: var(--font-size-base);
  line-height: 1;
}

/* Actions */
.app-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}

.app-header__status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-indicator.connected {
  background: var(--color-success-500);
  box-shadow: 0 0 0 2px var(--color-bg-success-subtle);
}

.status-indicator.connecting {
  background: var(--color-warning-500);
  animation: pulse 1.5s ease-in-out infinite;
}

.status-indicator.disconnected {
  background: var(--color-neutral-400);
}

.status-indicator.error {
  background: var(--color-danger-500);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* Menu Toggle (Mobile) */
.app-header__menu-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-fast);
}

.app-header__menu-toggle:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.app-header__menu-toggle:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.app-header__menu-toggle svg {
  width: 24px;
  height: 24px;
}

@media (min-width: 1024px) {
  .app-header__menu-toggle {
    display: none;
  }
}

/* Sidebar Overlay (Mobile) */
.app-sidebar-overlay {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-index-fixed) - 1);
  background: var(--color-bg-overlay);
  opacity: 0;
  animation: fadeIn var(--duration-fast) var(--ease-out) forwards;
}

@keyframes fadeIn {
  to { opacity: 1; }
}

/* Sidebar */
.app-sidebar {
  position: fixed;
  top: var(--header-height);
  left: 0;
  bottom: 0;
  z-index: var(--z-index-fixed);
  width: var(--sidebar-width);
  background: var(--color-surface-primary);
  border-right: 1px solid var(--color-border-light);
  transform: translateX(-100%);
  transition: transform var(--duration-normal) var(--ease-out);
  overflow-y: auto;
}

.app-sidebar--open {
  transform: translateX(0);
}

.app-sidebar--collapsed {
  width: var(--sidebar-width-collapsed);
}

@media (min-width: 1024px) {
  .app-sidebar {
    transform: translateX(0);
  }
  
  .app-sidebar--collapsed {
    transform: translateX(0);
  }
}

.app-sidebar__inner {
  height: 100%;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
}

.app-sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex: 1;
}

.app-sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-md);
  text-decoration: none;
  transition: var(--transition-fast);
  white-space: nowrap;
  overflow: hidden;
}

.app-sidebar__item:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}

.app-sidebar__item--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.app-sidebar__icon {
  font-size: var(--font-size-lg);
  line-height: 1;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.app-sidebar__label {
  transition: opacity var(--duration-fast) var(--ease-out), width var(--duration-fast) var(--ease-out);
}

.app-sidebar--collapsed .app-sidebar__label {
  opacity: 0;
  width: 0;
  pointer-events: none;
}

/* Main Content */
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0; /* Important for flex children */
}

.app-main__inner {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding-left: 0;
  transition: padding-left var(--duration-normal) var(--ease-out);
}

.app-layout--has-sidebar .app-main__inner {
  padding-left: 0;
}

@media (min-width: 1024px) {
  .app-layout--has-sidebar .app-main__inner {
    padding-left: var(--sidebar-width);
  }
  
  .app-layout--has-sidebar .app-sidebar--collapsed ~ .app-main .app-main__inner {
    padding-left: var(--sidebar-width-collapsed);
  }
}

/* Page Header */
.app-page-header {
  flex-shrink: 0;
  padding: var(--space-6) var(--space-padding-md);
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-surface-primary);
}

@media (min-width: 1024px) {
  .app-page-header {
    padding: var(--space-6) var(--space-padding-lg);
  }
}

.app-page-header__content {
  max-width: var(--container-max-xl);
  margin: 0 auto;
}

.app-page-header__title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  line-height: var(--line-height-tight);
  color: var(--color-text-primary);
  margin-bottom: var(--space-1);
}

.app-page-header__description {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.app-page-header__actions {
  max-width: var(--container-max-xl);
  margin: var(--space-4) auto 0;
  padding: 0 var(--space-padding-md);
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

@media (min-width: 1024px) {
  .app-page-header__actions {
    padding: 0 var(--space-padding-lg);
  }
}

/* Page Content */
.app-page {
  flex: 1;
  min-height: 0;
  padding: var(--space-6) var(--space-padding-md);
}

@media (min-width: 1024px) {
  .app-page {
    padding: var(--space-6) var(--space-padding-lg);
  }
}

.app-page > * {
  max-width: var(--container-max-xl);
  margin: 0 auto;
}

/* Footer */
.app-footer {
  flex-shrink: 0;
  padding: var(--space-4) var(--space-padding-md);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

@media (min-width: 1024px) {
  .app-footer {
    padding: var(--space-4) var(--space-padding-lg);
  }
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