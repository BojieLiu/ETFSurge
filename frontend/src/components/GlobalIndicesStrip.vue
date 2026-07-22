<template>
  <section class="card global-indices-compact">
    <div class="card-header-compact">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">🌐</span>
        全球主流指数
      </h2>
      <div class="card-actions-compact">
        <span class="status-badge" aria-live="polite">
          <span class="status-dot" aria-hidden="true"></span>
          自动刷新
        </span>
      </div>
    </div>

    <div v-if="hasIndices" class="indices-scroll">
      <div
        class="index-card-compact"
        v-for="idx in flatIndices"
        :key="idx.symbol"
        :class="{ unavailable: !idx.available, stale: !idx.available && idx.price != null }"
      >
        <span class="index-name-compact">{{ idx.name }}<span v-if="!idx.available && idx.price != null" class="index-stale-badge">已收盘</span></span>
        <span class="index-price-compact" v-if="idx.price != null">{{ formatPrice(idx.price) }}</span>
        <span class="index-price-compact muted" v-else>—</span>
        <span class="index-change-compact" v-if="idx.change_pct != null" :class="changeClass(idx.change_pct)">
          {{ formatChange(idx.change_pct) }}
        </span>
        <span class="index-change-compact muted" v-else>暂无</span>
      </div>
    </div>
    <div v-else class="indices-empty-compact">
      暂无数据，点击刷新获取
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { changeClass } from '../utils/changeClass'
// AppButton removed — component is now pure display, parent manages auto-refresh

// 纯展示组件：数据由父组件（Dashboard）通过 prop 传入，
// 不再自己拉取。避免与父组件 composable 产生两个不同步的数据源。
const props = defineProps({
  globalIndices: {
    type: Object,
    default: () => ({}),
  },
})

const hasIndices = computed(() => Object.keys(props.globalIndices).length > 0)
const flatIndices = computed(() => Object.values(props.globalIndices).flat())

function formatPrice(v) { return v != null ? v.toFixed(2) : '—' }
function formatChange(pct) { return pct != null ? (pct > 0 ? '+' : '') + pct.toFixed(2) + '%' : '—' }
</script>
