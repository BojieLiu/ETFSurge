<template>
  <section class="card chart-card">
    <div class="card-header">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">🥧</span>
        {{ title }}
      </h2>
    </div>
    <v-chart :option="chartOption" :style="{ height: '280px' }" autoresize />
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'

use([PieChart, TitleComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
  title: { type: String, required: true }
})

const chartOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { orient: 'vertical', left: 'left', top: 'middle', itemWidth: 12, itemHeight: 12 },
  series: [{
    name: '分配',
    type: 'pie',
    radius: ['40%', '70%'],
    avoidLabelOverlap: false,
    label: { show: false, position: 'center' },
    emphasis: { label: { show: true, fontSize: '18', fontWeight: 'bold' } },
    labelLine: { show: false },
    data: (props.items || []).map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    }))
  }],
  color: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#eab308']
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
</style>
