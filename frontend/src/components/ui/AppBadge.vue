<template>
  <span
    :class="badgeClasses"
    :style="badgeStyles"
    role="status"
    :aria-label="ariaLabel"
  >
    <span v-if="dot" class="badge__dot" aria-hidden="true" />
    <span v-else-if="count !== undefined && count !== null" class="badge__count" aria-hidden="true">
      {{ displayCount }}
    </span>
    <slot v-else />
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'default',
    validator: v => ['default', 'success', 'danger', 'warning', 'info', 'outline'].includes(v)
  },
  color: String,
  size: {
    type: String,
    default: 'md',
    validator: v => ['sm', 'md', 'lg'].includes(v)
  },
  dot: { type: Boolean, default: false },
  count: Number,
  maxCount: { type: Number, default: 99 },
  showZero: { type: Boolean, default: false },
  rounded: { type: Boolean, default: true },
  ariaLabel: String
})

const displayCount = computed(() => {
  if (props.count === undefined || props.count === null) return ''
  if (props.count === 0 && !props.showZero) return ''
  return props.count > props.maxCount ? `${props.maxCount}+` : String(props.count)
})

const ariaLabel = computed(() => {
  if (props.ariaLabel) return props.ariaLabel
  if (props.count !== undefined && props.count !== null) {
    return `${props.count} 条通知`
  }
  return ''
})

const badgeClasses = computed(() => [
  'badge',
  `badge--${props.variant}`,
  `badge--${props.size}`,
  { 'badge--dot': props.dot, 'badge--count': props.count !== undefined, 'badge--rounded': props.rounded }
])

const badgeStyles = computed(() => {
  if (!props.color) return {}
  if (props.variant === 'outline') {
    return { color: props.color, borderColor: props.color }
  }
  return { backgroundColor: props.color }
})
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-family-sans);
  font-weight: var(--font-weight-semibold);
  line-height: 1;
  white-space: nowrap;
  vertical-align: middle;
}

/* Sizes */
.badge--sm {
  height: 16px;
  padding: 0 var(--space-2);
  font-size: 10px;
  border-radius: var(--radius-full);
}

.badge--md {
  height: var(--badge-height);
  padding: 0 var(--badge-padding-x);
  font-size: var(--badge-font-size);
  border-radius: var(--radius-full);
}

.badge--lg {
  height: 24px;
  padding: 0 var(--space-3);
  font-size: var(--font-size-xs);
  border-radius: var(--radius-full);
}

/* Variants */
.badge--default {
  background: var(--color-brand-100);
  color: var(--color-brand-700);
}

.badge--success {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.badge--danger {
  background: var(--color-danger-100);
  color: var(--color-danger-700);
}

.badge--warning {
  background: var(--color-warning-100);
  color: var(--color-warning-700);
}

.badge--info {
  background: var(--color-info-100);
  color: var(--color-info-700);
}

.badge--outline {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-medium);
}

/* Dot */
.badge--dot {
  width: var(--badge-height);
  padding: 0;
  border-radius: 50%;
}

.badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

/* Count */
.badge--count {
  min-width: var(--badge-height);
}

/* Custom color override */
.badge[style*="background-color"] {
  color: white;
}
</style>