<template>
  <AppCard :title="title" icon="🥧">
    <v-chart :option="chartOption" :style="{ height: '280px' }" autoresize />
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import AppCard from '../ui/AppCard.vue'

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
      name: `${a.name} (${(a.target_weight * 100).toFixed(1)}%)`
    }))
  }],
  color: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#eab308']
}))
</script>

<style scoped>
/* Chart card provided by AppCard - no custom styles needed */
</style>