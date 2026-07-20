<template>
  <section class="card chart-section" v-if="chartOption && !loading">
    <v-chart :option="chartOption" :style="{ height: chartHeight + 'px' }" autoresize />
  </section>
  <section v-if="loading" class="loading-state">
    <div class="loading-spinner" aria-hidden="true"></div>
    <p>正在获取行情数据...</p>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import VChart from 'vue-echarts'

defineProps({ chartOption: Object, loading: Boolean })
const chartHeight = ref(560)
</script>

<style scoped>
.chart-section { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: hidden; padding: var(--space-4); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.loading-spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
