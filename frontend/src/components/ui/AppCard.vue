<template>
  <article
    class="app-card"
    :class="[
      `app-card--${variant}`,
      layoutClass,
      { 'app-card--hoverable': hoverable && !disabled },
      { 'app-card--clickable': clickable && !disabled },
      { 'app-card--disabled': disabled },
      { 'app-card--bordered': bordered },
      { 'app-card--padded': padded }
    ]"
    :tabindex="clickable ? 0 : undefined"
    :role="clickable ? 'button' : undefined"
    :aria-disabled="disabled"
    @click="handleClick"
    @keydown.enter.space.prevent="handleClick"
  >
    <!-- Horizontal layout: icon left, content right, no header/footer -->
    <template v-if="layout === 'horizontal'">
      <div v-if="icon || $slots['header-icon']" class="app-card__main-icon" aria-hidden="true">
        <slot name="header-icon">
          <span v-if="icon" v-html="resolvedIcon"></span>
        </slot>
      </div>
      <div class="app-card__content">
        <slot />
      </div>
    </template>

    <!-- Vertical layout (default) -->
    <template v-else>
      <header v-if="$slots.header || title || description" class="app-card__header">
        <div class="app-card__header-content">
          <div v-if="$slots['header-icon'] || icon" class="app-card__icon" aria-hidden="true">
            <slot name="header-icon" :icon="icon">
              <span v-if="icon">{{ icon }}</span>
            </slot>
          </div>
          <div class="app-card__titles" v-if="title || description || $slots['header-title'] || $slots['header-description']">
            <h3 v-if="title || $slots['header-title']" class="app-card__title">
              <slot name="header-title">{{ title }}</slot>
            </h3>
            <p v-if="description || $slots['header-description']" class="app-card__description">
              <slot name="header-description">{{ description }}</slot>
            </p>
          </div>
        </div>
        <div v-if="$slots['header-action']" class="app-card__header-action">
          <slot name="header-action" />
        </div>
      </header>

      <div class="app-card__content">
        <slot />
      </div>

      <footer v-if="$slots.footer" class="app-card__footer">
        <slot name="footer" />
      </footer>
    </template>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { icon as getIcon } from '../../utils/icons.js'

const props = defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: v => ['default', 'elevated', 'outlined', 'filled'].includes(v)
  },
  layout: {
    type: String,
    default: 'vertical',
    validator: v => ['vertical', 'horizontal'].includes(v)
  },
  title: String,
  description: String,
  icon: String,
  hoverable: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  bordered: { type: Boolean, default: true },
  padded: { type: Boolean, default: true }
})

const emit = defineEmits(['click'])

const resolvedIcon = computed(() => {
  if (!props.icon) return ''
  const svg = getIcon(props.icon)
  return svg || props.icon
})

const layoutClass = computed(() => props.layout === 'horizontal' ? 'app-card--horizontal' : 'app-card--vertical')

function handleClick(event) {
  if (!props.disabled && props.clickable) {
    emit('click', event)
  }
}
</script>

<style scoped>
.app-card {
  background: var(--color-surface-primary);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: var(--transition-normal);
}

.app-card--bordered {
  border: 1px solid var(--color-border-light);
}

/* Variants */
.app-card--default {
  box-shadow: var(--shadow-sm);
}

.app-card--elevated {
  border: none;
  box-shadow: var(--shadow-md);
}

.app-card--outlined {
  box-shadow: none;
  border: 1px solid var(--color-border-medium);
}

.app-card--filled {
  background: var(--color-surface-secondary);
  border: none;
  box-shadow: none;
}

/* Padding - shared */
.app-card--padded .app-card__header,
.app-card--padded .app-card__content,
.app-card--padded .app-card__footer {
  padding: var(--card-padding);
}

/* Horizontal layout: padding goes on the card itself, content has no padding */
.app-card--padded.app-card--horizontal {
  padding: var(--card-padding);
}
.app-card--padded.app-card--horizontal .app-card__content {
  padding: 0;
}

/* Hoverable */
.app-card--hoverable:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.app-card--elevated.app-card--hoverable:hover {
  box-shadow: var(--shadow-lg);
}

/* Clickable */
.app-card--clickable {
  cursor: pointer;
  user-select: none;
}

.app-card--clickable:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
  border-color: var(--color-border-focus);
}

.app-card--clickable:active {
  transform: scale(0.98);
  transition: var(--duration-instant);
}

/* Disabled */
.app-card--disabled {
  opacity: 0.6;
  pointer-events: none;
}

/* Header (vertical layout) */
.app-card--vertical .app-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-gap-md);
  padding-bottom: var(--space-gap-sm);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.app-card--vertical .app-card__header-content {
  display: flex;
  align-items: flex-start;
  gap: var(--space-gap-md);
  flex: 1;
  min-width: 0;
}

.app-card__icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-bg-brand-subtle);
  color: var(--color-brand-600);
  font-size: var(--font-size-lg);
}

.app-card__titles {
  flex: 1;
  min-width: 0;
}

.app-card__title {
  margin: 0;
  font: var(--text-h3);
  color: var(--color-text-primary);
  line-height: var(--line-height-snug);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-card__description {
  margin: var(--space-half) 0 0 0;
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.app-card__header-action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-gap-sm);
}

/* Horizontal layout */
.app-card--horizontal {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: var(--space-4);
}

.app-card--horizontal .app-card__main-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--color-surface-secondary);
  font-size: var(--font-size-2xl);
  line-height: 1;
}

.app-card--horizontal .app-card__content {
  flex: 1;
  min-width: 0;
}

/* Footer (vertical layout) */
.app-card--vertical .app-card__footer {
  display: flex;
  align-items: center;
  gap: var(--space-gap-sm);
  padding-top: var(--space-gap-sm);
  border-top: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

/* Density variants (backward-compat) */
.app-card--compact .app-card__header,
.app-card--compact .app-card__content,
.app-card--compact .app-card__footer {
  padding: var(--space-3);
}

.app-card--spacious .app-card__header,
.app-card--spacious .app-card__content,
.app-card--spacious .app-card__footer {
  padding: var(--space-6);
}
</style>
