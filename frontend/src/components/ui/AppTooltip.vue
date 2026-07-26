<template>
  <span class="tooltip" :class="[`tooltip--${placement}`, { 'tooltip--open': open }]" role="tooltip" :id="tooltipId">
    <slot name="trigger">
      <span class="tooltip__trigger" 
        @mouseenter="handleMouseEnter"
        @mouseleave="handleMouseLeave"
        @focus="handleMouseEnter"
        @blur="handleMouseLeave"
        @click="handleClick"
        tabindex="0"
      >
        <slot />
      </span>
    </slot>

    <Transition name="tooltip">
      <div
        v-show="open"
        class="tooltip__content"
        :style="contentStyle"
        :aria-describedby="tooltipId"
      >
        <div class="tooltip__arrow" aria-hidden="true" />
        <div class="tooltip__inner">
          <slot name="content">{{ content }}</slot>
        </div>
      </div>
    </Transition>
  </span>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  content: String,
  placement: {
    type: String,
    default: 'top',
    validator: v => ['top', 'bottom', 'left', 'right', 'top-start', 'top-end', 'bottom-start', 'bottom-end', 'left-start', 'left-end', 'right-start', 'right-end'].includes(v)
  },
  trigger: {
    type: String,
    default: 'hover',
    validator: v => ['hover', 'click', 'focus', 'contextmenu'].includes(v)
  },
  delay: { type: Number, default: 150 },
  offset: { type: Number, default: 8 },
  disabled: { type: Boolean, default: false },
  persistent: { type: Boolean, default: false }
})

const emit = defineEmits(['visible-change'])

const open = ref(false)
const tooltipId = `tooltip-${Math.random().toString(36).slice(2, 9)}`
let hideTimer = null
let showTimer = null
let contentRef = null

const contentStyle = computed(() => {
  if (!contentRef) return {}
  
  const rect = contentRef.getBoundingClientRect()
  const triggerRect = contentRef.parentElement?.querySelector('.tooltip__trigger')?.getBoundingClientRect()
  
  // Styles will be handled by CSS, this is for dynamic positioning if needed
  return {}
})

function show() {
  if (props.disabled) return
  clearTimeout(hideTimer)
  
  showTimer = setTimeout(() => {
    open.value = true
    emit('visible-change', true)
  }, props.delay)
}

function hide() {
  if (props.persistent) return
  clearTimeout(showTimer)
  
  hideTimer = setTimeout(() => {
    open.value = false
    emit('visible-change', false)
  }, props.delay)
}

function handleMouseEnter() {
  if (props.trigger === 'hover' || props.trigger === 'focus') show()
}

function handleMouseLeave() {
  if (props.trigger === 'hover' || props.trigger === 'focus') hide()
}

function handleClick(event) {
  if (props.trigger === 'click') {
    event.stopPropagation()
    open.value = !open.value
    emit('visible-change', open.value)
  }
}

function handleContextMenu(event) {
  if (props.trigger === 'contextmenu') {
    event.preventDefault()
    show()
  }
}

function handleKeyDown(event) {
  if (event.key === 'Escape') {
    open.value = false
    emit('visible-change', false)
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleKeyDown)
  clearTimeout(showTimer)
  clearTimeout(hideTimer)
})

function handleDocumentClick(event) {
  if (props.trigger === 'click' && open.value) {
    const el = contentRef?.parentElement
    if (el && !el.contains(event.target)) {
      open.value = false
      emit('visible-change', false)
    }
  }
}
</script>

<style scoped>
.tooltip {
  position: relative;
  display: inline-flex;
}

.tooltip__trigger {
  cursor: help;
}

.tooltip__content {
  position: absolute;
  z-index: var(--z-index-tooltip);
  display: flex;
  flex-direction: column;
  pointer-events: none;
  opacity: 0;
  visibility: hidden;
  transition: opacity var(--duration-fast) var(--ease-out),
              visibility var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.tooltip--open .tooltip__content {
  opacity: 1;
  visibility: visible;
}

/* Placement: Top */
.tooltip--top .tooltip__content {
  bottom: calc(100% + var(--offset));
  left: 50%;
  transform: translateX(-50%) translateY(4px);
}

.tooltip--top.tooltip--open .tooltip__content {
  transform: translateX(-50%) translateY(0);
}

.tooltip--top .tooltip__arrow {
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%) rotate(45deg);
}

/* Placement: Bottom */
.tooltip--bottom .tooltip__content {
  top: calc(100% + var(--offset));
  left: 50%;
  transform: translateX(-50%) translateY(-4px);
}

.tooltip--bottom.tooltip--open .tooltip__content {
  transform: translateX(-50%) translateY(0);
}

.tooltip--bottom .tooltip__arrow {
  top: -4px;
  left: 50%;
  transform: translateX(-50%) rotate(45deg);
}

/* Placement: Left */
.tooltip--left .tooltip__content {
  right: calc(100% + var(--offset));
  top: 50%;
  transform: translateY(-50%) translateX(4px);
}

.tooltip--left.tooltip--open .tooltip__content {
  transform: translateY(-50%) translateX(0);
}

.tooltip--left .tooltip__arrow {
  right: -4px;
  top: 50%;
  transform: translateY(-50%) rotate(45deg);
}

/* Placement: Right */
.tooltip--right .tooltip__content {
  left: calc(100% + var(--offset));
  top: 50%;
  transform: translateY(-50%) translateX(-4px);
}

.tooltip--right.tooltip--open .tooltip__content {
  transform: translateY(-50%) translateX(0);
}

.tooltip--right .tooltip__arrow {
  left: -4px;
  top: 50%;
  transform: translateY(-50%) rotate(45deg);
}

/* Start/End variants */
.tooltip--top-start .tooltip__content,
.tooltip--bottom-start .tooltip__content {
  left: 0;
  right: auto;
  transform-origin: left center;
  transform: translateX(0) translateY(4px);
}

.tooltip--top-start.tooltip--open .tooltip__content,
.tooltip--bottom-start.tooltip--open .tooltip__content {
  transform: translateX(0) translateY(0);
}

.tooltip--top-start .tooltip__arrow,
.tooltip--bottom-start .tooltip__arrow {
  left: 12px;
  right: auto;
  transform: translateX(-50%) rotate(45deg);
}

.tooltip--top-end .tooltip__content,
.tooltip--bottom-end .tooltip__content {
  right: 0;
  left: auto;
  transform-origin: right center;
  transform: translateX(0) translateY(4px);
}

.tooltip--top-end.tooltip--open .tooltip__content,
.tooltip--bottom-end.tooltip--open .tooltip__content {
  transform: translateX(0) translateY(0);
}

.tooltip--top-end .tooltip__arrow,
.tooltip--bottom-end .tooltip__arrow {
  right: 12px;
  left: auto;
  transform: translateX(50%) rotate(45deg);
}

.tooltip--left-start .tooltip__content,
.tooltip--right-start .tooltip__content {
  top: 0;
  bottom: auto;
  transform-origin: center top;
  transform: translateY(0) translateX(4px);
}

.tooltip--left-start.tooltip--open .tooltip__content,
.tooltip--right-start.tooltip--open .tooltip__content {
  transform: translateY(0) translateX(0);
}

.tooltip--left-start .tooltip__arrow,
.tooltip--right-start .tooltip__arrow {
  top: 12px;
  bottom: auto;
  transform: translateY(-50%) rotate(45deg);
}

.tooltip--left-end .tooltip__content,
.tooltip--right-end .tooltip__content {
  bottom: 0;
  top: auto;
  transform-origin: center bottom;
  transform: translateY(0) translateX(4px);
}

.tooltip--left-end.tooltip--open .tooltip__content,
.tooltip--right-end.tooltip--open .tooltip__content {
  transform: translateY(0) translateX(0);
}

.tooltip--left-end .tooltip__arrow,
.tooltip--right-end .tooltip__arrow {
  bottom: 12px;
  top: auto;
  transform: translateY(50%) rotate(45deg);
}

.tooltip__inner {
  padding: var(--space-2) var(--space-3);
  font: var(--text-caption);
  line-height: var(--line-height-normal);
  color: var(--color-text-inverse);
  background: var(--color-neutral-900);
  border-radius: var(--radius-md);
  white-space: nowrap;
  max-width: 240px;
  word-break: break-word;
  box-shadow: var(--shadow-lg);
}

.tooltip__arrow {
  position: absolute;
  width: 8px;
  height: 8px;
  background: var(--color-neutral-900);
  pointer-events: none;
}

/* Animations */
.tooltip-enter-active,
.tooltip-leave-active {
  transition: opacity var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.tooltip-enter-from,
.tooltip-leave-to {
  opacity: 0;
}

.tooltip--top .tooltip-enter-from,
.tooltip--top .tooltip-leave-to {
  transform: translateX(-50%) translateY(8px);
}

.tooltip--bottom .tooltip-enter-from,
.tooltip--bottom .tooltip-leave-to {
  transform: translateX(-50%) translateY(-8px);
}

.tooltip--left .tooltip-enter-from,
.tooltip--left .tooltip-leave-to {
  transform: translateY(-50%) translateX(8px);
}

.tooltip--right .tooltip-enter-from,
.tooltip--right .tooltip-leave-to {
  transform: translateY(-50%) translateX(-8px);
}
</style>