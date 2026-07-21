<template>
  <div
    class="avatar"
    :class="[
      `avatar--${size}`,
      { 'avatar--square': shape === 'square', 'avatar--has-status': status }
    ]"
    :style="avatarStyles"
    :aria-label="alt"
    role="img"
  >
    <img
      v-if="src"
      :src="src"
      :alt="alt"
      class="avatar__image"
      @error="handleError"
      :loading="lazy ? 'lazy' : undefined"
    />
    <span v-else-if="icon" class="avatar__icon" aria-hidden="true">{{ icon }}</span>
    <span v-else class="avatar__fallback" aria-hidden="true">{{ fallbackText }}</span>
    
    <span
      v-if="status"
      class="avatar__status"
      :class="`avatar__status--${status}`"
      :aria-label="statusLabel"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  src: String,
  alt: String,
  icon: String,
  size: {
    type: String,
    default: 'md',
    validator: v => ['xs', 'sm', 'md', 'lg', 'xl'].includes(v)
  },
  shape: {
    type: String,
    default: 'circle',
    validator: v => ['circle', 'square'].includes(v)
  },
  status: {
    type: String,
    default: '',
    validator: v => ['', 'online', 'offline', 'busy', 'away'].includes(v)
  },
  fallback: String,
  lazy: { type: Boolean, default: true }
})

const imageError = ref(false)

const sizeMap = {
  xs: 'var(--avatar-size-xs)',
  sm: 'var(--avatar-size-sm)',
  md: 'var(--avatar-size-md)',
  lg: 'var(--avatar-size-lg)',
  xl: 'var(--avatar-size-xl)'
}

const avatarStyles = computed(() => ({
  width: sizeMap[props.size],
  height: sizeMap[props.size],
  fontSize: getFontSize(props.size)
}))

function getFontSize(size) {
  const map = { xs: '10px', sm: '12px', md: '14px', lg: '16px', xl: '20px' }
  return map[size] || '14px'
}

const fallbackText = computed(() => {
  if (props.fallback) return props.fallback
  if (props.alt) return props.alt.slice(0, 2).toUpperCase()
  return '?'
})

const statusLabel = computed(() => {
  const labels = {
    online: '在线',
    offline: '离线',
    busy: '忙碌',
    away: '离开'
  }
  return labels[props.status] || ''
})

function handleError() {
  imageError.value = true
}
</script>

<style scoped>
.avatar {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  background: var(--color-surface-tertiary);
  color: var(--color-text-tertiary);
  font-weight: var(--font-weight-medium);
  vertical-align: middle;
}

.avatar--circle {
  border-radius: 50%;
}

.avatar--square {
  border-radius: var(--radius-md);
}

.avatar__image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 1.2em;
  line-height: 1;
}

.avatar__fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-brand-100);
  color: var(--color-brand-700);
}

.avatar__status {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 25%;
  height: 25%;
  min-width: 8px;
  min-height: 8px;
  border: 2px solid var(--color-surface-primary);
  border-radius: 50%;
}

.avatar--circle .avatar__status {
  border-radius: 50%;
}

.avatar--square .avatar__status {
  border-radius: var(--radius-full);
}

.avatar__status--online { background: var(--color-success-500); }
.avatar__status--offline { background: var(--color-neutral-400); }
.avatar__status--busy { background: var(--color-danger-500); }
.avatar__status--away { background: var(--color-warning-500); }

/* Group overlap */
.avatar-group .avatar + .avatar {
  margin-left: -8px;
  border: 2px solid var(--color-surface-primary);
  box-shadow: var(--shadow-sm);
}

.avatar-group .avatar:first-child {
  z-index: 1;
}
</style>