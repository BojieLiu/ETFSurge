<template>
  <div class="page-container" :class="containerClasses">
    <slot />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: {
    type: String,
    default: 'xl',
    validator: v => ['xs', 'sm', 'md', 'lg', 'xl', '2xl', 'full', 'narrow', 'wide'].includes(v)
  },
  padded: { type: Boolean, default: true },
  tag: { type: String, default: 'div' }
})

const containerClasses = computed(() => [
  'page-container',
  `page-container--${props.size}`,
  { 'page-container--padded': props.padded }
])
</script>

<style scoped>
.page-container {
  width: 100%;
  margin: 0 auto;
}

.page-container--padded {
  padding: 0 var(--space-padding-md);
}

@media (min-width: 1024px) {
  .page-container--padded {
    padding: 0 var(--space-padding-lg);
  }
}

.page-container--xs { max-width: var(--container-max-xs); }
.page-container--sm { max-width: var(--container-max-sm); }
.page-container--md { max-width: var(--container-max-md); }
.page-container--lg { max-width: var(--container-max-lg); }
.page-container--xl { max-width: var(--container-max-xl); }
.page-container--2xl { max-width: var(--container-max-2xl); }
.page-container--full { max-width: var(--container-max-full); padding: 0; }
.page-container--narrow { max-width: var(--container-max-lg); }
.page-container--wide { max-width: var(--container-max-2xl); }
</style>