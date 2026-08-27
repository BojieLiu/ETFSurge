<template>
  <div class="tabs" :class="[`tabs--${variant}`, { 'tabs--full-width': fullWidth }]" role="tablist" :aria-label="ariaLabel">
    <div class="tabs__nav" ref="navRef" :class="{ 'tabs__nav--scrollable': scrollable }">
      <div class="tabs__nav-inner" :style="navInnerStyle">
        <button
          v-for="(tab, index) in tabs"
          :key="tab.value"
          :class="[
            'tabs__tab',
            { 'tabs__tab--active': modelValue === tab.value },
            { 'tabs__tab--disabled': tab.disabled },
            tab.class
          ]"
          :id="`tab-${tab.value}`"
          :aria-controls="`panel-${tab.value}`"
          :aria-selected="modelValue === tab.value"
          :aria-disabled="tab.disabled"
          role="tab"
          tabindex="modelValue === tab.value ? 0 : -1"
          @click="!tab.disabled && selectTab(tab.value)"
          @keydown="handleKeydown($event, tab.value, index)"
        >
          <span v-if="tab.icon" class="tabs__tab-icon" aria-hidden="true">{{ tab.icon }}</span>
          <span class="tabs__tab-label">{{ tab.label }}</span>
          <span v-if="tab.badge !== undefined && tab.badge !== null" class="tabs__tab-badge">{{ tab.badge }}</span>
        </button>

        <!-- Line indicator -->
        <div
          v-if="variant === 'line'"
          class="tabs__indicator"
          :style="indicatorStyle"
          aria-hidden="true"
        ></div>
      </div>
    </div>

    <!-- Scroll buttons for horizontal scroll -->
    <button
      v-if="scrollable"
      class="tabs__scroll-btn tabs__scroll-btn--prev"
      @click="scroll(-1)"
      :disabled="scrollLeft <= 0"
      aria-label="向左滚动"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" aria-hidden="true">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
    <button
      v-if="scrollable"
      class="tabs__scroll-btn tabs__scroll-btn--next"
      @click="scroll(1)"
      :disabled="scrollLeft + clientWidth >= scrollWidth - 1"
      aria-label="向右滚动"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" aria-hidden="true">
        <polyline points="9 18 15 12 9 6"/>
      </svg>
    </button>
  </div>

  <!-- Tab Panels -->
  <div class="tabs__panels" v-if="lazy || !lazy">
    <div
      v-for="tab in tabs"
      :key="tab.value"
      :id="`panel-${tab.value}`"
      role="tabpanel"
      :aria-labelledby="`tab-${tab.value}`"
      :hidden="modelValue !== tab.value"
      class="tabs__panel"
      :class="{ 'tabs__panel--active': modelValue === tab.value }"
    >
      <slot :name="tab.value" :tab="tab" />
      <slot v-if="!tab.slot" name="default" :tab="tab" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], required: true },
  tabs: {
    type: Array,
    default: () => [],
    validator: arr => arr.every(t => t.value !== undefined && t.label)
  },
  variant: {
    type: String,
    default: 'line',
    validator: v => ['line', 'enclosed', 'soft'].includes(v)
  },
  fullWidth: { type: Boolean, default: false },
  lazy: { type: Boolean, default: false },
  ariaLabel: String,
  animated: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'change'])

const navRef = ref(null)
const scrollLeft = ref(0)
const clientWidth = ref(0)
const scrollWidth = ref(0)
const tabRects = new Map()

const scrollable = computed(() => scrollWidth.value > clientWidth.value)

const activeTab = computed(() => props.tabs.find(t => t.value === props.modelValue))

const navInnerStyle = computed(() => {
  if (!activeTab.value || !tabRects.has(activeTab.value)) return {}
  const rect = tabRects.get(activeTab.value)
  if (props.variant !== 'line') return {}
  return {
    transform: `translateX(${-scrollLeft.value}px)`
  }
})

const indicatorStyle = computed(() => {
  if (!activeTab.value || !tabRects.has(activeTab.value) || props.variant !== 'line') {
    return { width: 0, transform: 'translateX(-9999px)' }
  }
  const rect = tabRects.get(activeTab.value)
  return {
    width: `${rect.width}px`,
    transform: `translateX(${rect.left - scrollLeft.value}px)`
  }
})

function selectTab(value) {
  if (props.modelValue === value) return
  emit('update:modelValue', value)
  emit('change', value)
  scrollToTab(value)
}

function handleKeydown(event, value, index) {
  const tabs = props.tabs.filter(t => !t.disabled)
  const currentIndex = tabs.findIndex(t => t.value === value)
  
  let newIndex = currentIndex
  switch (event.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      event.preventDefault()
      newIndex = (currentIndex + 1) % tabs.length
      break
    case 'ArrowLeft':
    case 'ArrowUp':
      event.preventDefault()
      newIndex = (currentIndex - 1 + tabs.length) % tabs.length
      break
    case 'Home':
      event.preventDefault()
      newIndex = 0
      break
    case 'End':
      event.preventDefault()
      newIndex = tabs.length - 1
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      selectTab(value)
      return
  }
  
  if (newIndex !== currentIndex) {
    const newValue = tabs[newIndex].value
    selectTab(newValue)
    nextTick(() => {
      const btn = navRef.value?.querySelector(`[data-value="${newValue}"]`)
      btn?.focus()
    })
  }
}

function updateRects() {
  if (!navRef.value) return
  const tabs = navRef.value.querySelectorAll('.tabs__tab')
  tabRects.clear()
  tabs.forEach(tab => {
    const rect = tab.getBoundingClientRect()
    const containerRect = navRef.value.getBoundingClientRect()
    tabRects.set(tab.dataset.value, {
      left: rect.left - containerRect.left,
      width: rect.width
    })
  })
  clientWidth.value = navRef.value.clientWidth
  scrollWidth.value = navRef.value.scrollWidth
  scrollLeft.value = navRef.value.scrollLeft
}

function scrollToTab(value) {
  if (!navRef.value || !tabRects.has(value)) return
  const rect = tabRects.get(value)
  const centerOffset = (clientWidth.value - rect.width) / 2
  const targetScroll = rect.left - centerOffset
  navRef.value.scrollTo({ left: Math.max(0, targetScroll), behavior: props.animated ? 'smooth' : 'auto' })
}

function scroll(direction) {
  if (!navRef.value) return
  const amount = clientWidth.value * 0.8
  navRef.value.scrollBy({ left: direction * amount, behavior: 'smooth' })
}

function onScroll() {
  if (!navRef.value) return
  scrollLeft.value = navRef.value.scrollLeft
}

onMounted(() => {
  nextTick(() => {
    updateRects()
    scrollToTab(props.modelValue)
    navRef.value?.addEventListener('scroll', onScroll)
    window.addEventListener('resize', updateRects)
  })
})

onUnmounted(() => {
  navRef.value?.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', updateRects)
})

watch(() => props.tabs, updateRects)
watch(() => props.modelValue, (val) => {
  nextTick(() => scrollToTab(val))
})
</script>

<style scoped>
.tabs {
  display: flex;
  flex-direction: column;
}

.tabs__nav {
  position: relative;
  display: flex;
  overflow: hidden;
}

.tabs__nav-inner {
  display: flex;
  gap: var(--space-1);
  transition: transform var(--duration-normal) var(--ease-out);
  will-change: transform;
}

.tabs__tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: var(--transition-fast);
  white-space: nowrap;
  user-select: none;
}

.tabs__tab:hover:not(.tabs__tab--disabled) {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}

.tabs__tab:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.tabs__tab--disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tabs__tab-icon {
  font-size: var(--font-size-base);
  line-height: 1;
}

.tabs__tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 var(--space-1);
  font: var(--text-caption);
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
  border-radius: var(--radius-full);
}

/* Variants */
.tabs--line .tabs__nav {
  border-bottom: 1px solid var(--color-border-light);
}

.tabs--line .tabs__tab {
  padding-bottom: calc(var(--space-3) - 1px);
  margin-bottom: -1px;
  border-bottom: 2px solid transparent;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}

.tabs--line .tabs__tab--active {
  color: var(--color-brand-600);
  border-bottom-color: var(--color-brand-600);
}

.tabs--enclosed .tabs__tab {
  border: 1px solid transparent;
  border-radius: var(--radius-full);
}

.tabs--enclosed .tabs__tab--active {
  color: white;
  background: var(--color-brand-600);
}

.tabs--enclosed .tabs__tab--active:hover {
  background: var(--color-brand-700);
}

.tabs--soft .tabs__tab {
  border-radius: var(--radius-md);
}

.tabs--soft .tabs__tab--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.tabs--soft .tabs__tab--active:hover {
  background: var(--color-bg-brand-subtle);
}

.tabs--full-width .tabs__tab {
  flex: 1;
}

/* Indicator */
.tabs__indicator {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--color-brand-600);
  border-radius: 2px 2px 0 0;
  transition: transform var(--duration-normal) var(--ease-out), width var(--duration-normal) var(--ease-out);
  pointer-events: none;
}

/* Scroll buttons */
.tabs__scroll-btn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-fast);
  z-index: 2;
  box-shadow: var(--shadow-sm);
}

.tabs__scroll-btn:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  border-color: var(--color-border-medium);
}

.tabs__scroll-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.tabs__scroll-btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.tabs__scroll-btn--prev {
  left: 0;
  margin-left: -8px;
}

.tabs__scroll-btn--next {
  right: 0;
  margin-right: -8px;
}

/* Panels */
.tabs__panels {
  flex: 1;
}

.tabs__panel {
  display: none;
  animation: tabs-panel-fade var(--duration-normal) var(--ease-out);
}

.tabs__panel--active {
  display: block;
}

@keyframes tabs-panel-fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Mobile scroll hint */
@media (max-width: 639px) {
  .tabs__nav {
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  
  .tabs__nav::-webkit-scrollbar {
    display: none;
  }
  
  .tabs__scroll-btn {
    display: none;
  }
}
</style>