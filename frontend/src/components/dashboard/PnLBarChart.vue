<template>
  <section class="card chart-card">
    <div class="card-header">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">📈</span>
        当日盈亏分布
      </h2>
    </div>
    <v-chart v-if="items.length" :option="chartOption" :style="{ height: '350px' }" autoresize />
    <div v-else class="empty-chart" v-show="!loading">暂无盈亏数据</div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import VChart from 'vue-echarts'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: true }
})

const chartOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: { type: 'category', data: props.items.map(i => i.short_name || i.name), axisLabel: { interval: 0, rotate: 30 } },
  yAxis: { type: 'value', name: '盈亏 (元)' },
  series: [{
    name: '当日盈亏',
    type: 'bar',
    data: props.items.map(i => i.daily_pnl || 0),
    itemStyle: {
      color: (params) => params.value >= 0 ? '#ef4444' : '#22c55e'
    },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
  }]
}))
</script>

<style scoped>
.chart-card {
  display: flex;
  flex-direction: column;
}
.chart-card .card-header {
  flex-shrink: 0;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}
.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}
.card-title-icon {
  font-size: var(--font-size-xl);
  line-height: 1;
}
.empty-chart {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}
</style>
