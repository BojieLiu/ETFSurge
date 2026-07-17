<template>
  <section class="card global-indices-compact">
    <div class="card-header-compact">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">🌐</span>
        全球主流指数
      </h2>
      <div class="card-actions-compact">
        <span class="status-badge" v-if="timer" aria-live="polite">
          <span class="status-dot" aria-hidden="true"></span>
          自动刷新
        </span>
        <AppButton variant="ghost" size="xs" @click="fetchIndices" :loading="loading">
          刷新
        </AppButton>
      </div>
    </div>

    <div v-if="hasIndices" class="indices-scroll">
      <div
        class="index-card-compact"
        v-for="idx in flatIndices"
        :key="idx.symbol"
        :class="{ unavailable: !idx.available }"
      >
        <span class="index-name-compact">{{ idx.name }}</span>
        <span class="index-price-compact" v-if="idx.available">{{ formatPrice(idx.price) }}</span>
        <span class="index-price-compact muted" v-else>—</span>
        <span class="index-change-compact" v-if="idx.available" :class="changeClass(idx.change_pct)">
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { marketApi } from '../api'
import { changeClass } from '../utils/changeClass'
import AppButton from './ui/AppButton.vue'

const emit = defineEmits(['fetch'])

const globalIndices = ref({})
const loading = ref(false)
const timer = ref(null)

const hasIndices = computed(() => Object.keys(globalIndices.value).length > 0)
const flatIndices = computed(() => Object.values(globalIndices.value).flat())

function formatPrice(v) { return v != null ? v.toFixed(2) : '—' }
function formatChange(pct) { return pct != null ? (pct > 0 ? '+' : '') + pct.toFixed(2) + '%' : '—' }

async function fetchIndices() {
  loading.value = true
  try {
    const res = await marketApi.fetchAll()
    globalIndices.value = res.data || {}
    emit('fetch', res.data)
  } catch (e) {
    globalIndices.value = {}
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchIndices()
  timer.value = setInterval(fetchIndices, 60000)
})

onUnmounted(() => {
  if (timer.value) clearInterval(timer.value)
})
</script>
