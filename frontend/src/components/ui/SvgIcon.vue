<template>
  <span class="svg-icon" aria-hidden="true" v-html="iconHtml" :style="iconStyle"></span>
</template>

<script setup>
import { computed } from 'vue'
import { icon } from '../utils/icons.js'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [String, Number], default: 20 },
  color: { type: String, default: '' },
})

const iconHtml = computed(() => icon(props.name))
const iconStyle = computed(() => ({
  width: typeof props.size === 'number' ? props.size + 'px' : props.size,
  height: typeof props.size === 'number' ? props.size + 'px' : props.size,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: props.color || 'inherit',
}))
</script>

<style scoped>
.svg-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  line-height: 0;
}
.svg-icon :deep(svg) {
  width: 100%;
  height: 100%;
  fill: currentColor ?? none;
  stroke: currentColor;
}
</style>
