<template>
  <AppCard title="当日盈亏分布" icon="📈">
    <v-chart v-if="items.length" :option="chartOption" :style="{ height: '350px' }" autoresize />
    <div v-else class="empty-chart" v-show="!loading">暂无盈亏数据</div>
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import VChart from 'vue-echarts'
import AppCard from '../ui/AppCard.vue'

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
      /* 美化轮: 红涨绿跌对齐 theme 语义色（#ef4444→danger-500 系，#22c55e→success-500 系）——
         与页面 text-up/text-down 数字同色系，硬编码色值不再漂移 */
      color: (params) => params.value >= 0 ? '#dc2626' : '#16a34a'
    },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
  }]
}))
</script>

<style scoped>
.empty-chart {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}
</style>