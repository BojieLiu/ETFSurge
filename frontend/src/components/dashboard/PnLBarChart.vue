<template>
  <AppCard variant="default" :padding="false" class="pnl-bar-chart">
    <template #header>
      <h2 class="card__title">
        <span class="card-title-icon" aria-hidden="true">📈</span>
        当日盈亏分布
      </h2>
    </template>

    <AppSkeleton v-if="loading" type="chart" height="350" />

    <div v-else-if="items.length === 0" class="empty-chart">
      暂无盈亏数据
    </div>

    <VChart
      v-else
      :option="chartOption"
      :style="{ height: '350px' }"
      autoresize
    />
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, XAxisComponent, YAxisComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { AppCard, AppSkeleton } from '@/components'

use([BarChart, TitleComponent, TooltipComponent, GridComponent, XAxisComponent, YAxisComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: true }
})

const chartOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  xAxis: {
    type: 'category',
    data: props.items.map(i => i.short_name || i.name),
    axisLabel: { interval: 0, rotate: 30, color: 'var(--color-text-secondary)', fontSize: 11 },
    axisLine: { lineStyle: { color: 'var(--color-border-light)' } },
    axisTick: { show: false }
  },
  yAxis: {
    type: 'value',
    name: '盈亏 (元)',
    nameTextStyle: { color: 'var(--color-text-tertiary)', fontSize: 11, padding: [0, 0, 10, 0] },
    axisLabel: { color: 'var(--color-text-tertiary)', fontSize: 11 },
    axisLine: { lineStyle: { color: 'var(--color-border-light)' } },
    splitLine: { lineStyle: { color: 'var(--color-border-light)', type: 'dashed' } }
  },
  series: [{
    name: '当日盈亏',
    type: 'bar',
    data: props.items.map(i => i.daily_pnl || 0),
    itemStyle: {
      color: (params) => params.value >= 0 ? 'var(--color-danger-500)' : 'var(--color-success-500)',
      borderRadius: [4, 4, 0, 0]
    },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
    barWidth: '60%'
  }]
}))
</script>

<style scoped>
.pnl-bar-chart {
  /* AppCard handles layout */
}

.empty-chart {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* ECharts theme override */
:deep(.echarts-for-renderer) {
  font-family: var(--font-family-sans);
}
</style>