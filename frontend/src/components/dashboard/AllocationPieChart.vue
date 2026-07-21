<template>
  <AppCard variant="default" :padding="false" class="allocation-pie-chart">
    <template #header>
      <h2 class="card__title">
        <span class="card-title-icon" aria-hidden="true">🥧</span>
        {{ title }}
      </h2>
    </template>

    <div class="chart-container" ref="chartRef" style="height: 280px"></div>

    <template #footer v-if="items.length">
      <div class="chart-legend">
        <span
          v-for="(item, index) in items"
          :key="item.symbol"
          class="legend-item"
        >
          <span
            class="legend-color"
            :style="{ backgroundColor: legendColors[index] }"
          ></span>
          <span class="legend-label">
            {{ item.symbol }} ({{ (item.target_weight * 100).toFixed(1) }}%)
          </span>
        </span>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { AppCard } from '@/components'

echarts.use([PieChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
  title: { type: String, required: true }
})

const chartRef = ref(null)
let chartInstance = null

const legendColors = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
  'var(--chart-7)',
  'var(--chart-8)'
]

const chartOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} ({d}%)',
    backgroundColor: 'var(--color-surface-primary)',
    borderColor: 'var(--color-border-light)',
    borderWidth: 1,
    textStyle: {
      color: 'var(--color-text-primary)'
    }
  },
  legend: {
    show: false
  },
  series: [{
    name: '分配',
    type: 'pie',
    radius: ['40%', '70%'],
    avoidLabelOverlap: false,
    label: { show: false, position: 'center' },
    emphasis: { label: { show: true, fontSize: '18', fontWeight: 'bold', color: 'var(--color-text-primary)' } },
    labelLine: { show: false },
    data: (props.items || []).map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    }))
  }],
  color: legendColors
}))

onMounted(() => {
  if (chartRef.value) {
    chartInstance = echarts.init(chartRef.value)
    chartInstance.setOption(chartOption.value)
  }
})

onUnmounted(() => {
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

watch(chartOption, (newOption) => {
  if (chartInstance) {
    chartInstance.setOption(newOption)
  }
}, { deep: true })
</script>

<style scoped>
.allocation-pie-chart {
  /* AppCard handles layout */
}

.chart-container {
  width: 100%;
  height: 280px;
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-4);
  padding: var(--space-3) var(--card-padding);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.legend-color {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}
</style>