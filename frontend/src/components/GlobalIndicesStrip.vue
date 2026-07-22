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
        :class="[
          regionClass(idx.region),
          { unavailable: !idx.available, stale: !idx.available && idx.price != null }
        ]"
      >
        <span class="region-dot" :class="regionClass(idx.region)"></span>
        <div class="index-info">
          <span class="index-name-compact">{{ idx.name }}</span>
          <span v-if="!idx.available && idx.price != null" class="index-stale-badge">已收盘</span>
        </div>
        <div class="index-data">
          <span class="index-price-compact" v-if="idx.price != null">{{ formatPrice(idx.price) }}</span>
          <span class="index-price-compact muted" v-else>—</span>
          <span class="index-change-compact" v-if="idx.change_pct != null" :class="changeClass(idx.change_pct)">
            <span class="change-arrow" v-if="idx.change_pct > 0">▲</span>
            <span class="change-arrow" v-else-if="idx.change_pct < 0">▼</span>
            {{ formatChange(idx.change_pct) }}
          </span>
          <span class="index-change-compact muted" v-else>暂无</span>
        </div>
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

function regionClass(region) {
  const map = {
    'A股': 'region-a',
    '港股': 'region-hk',
    '日经': 'region-jp',
    '韩国': 'region-kr',
    '澳洲': 'region-au',
    '美股': 'region-us',
    '欧洲': 'region-eu',
  }
  return map[region] || 'region-default'
}
</script>

<style scoped>
.global-indices-compact {
  background: var(--color-neutral-0);
  border-radius: var(--radius-xl, 12px);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.05));
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
}

.card-header-compact {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}

.card-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.card-title-icon { font-size: 1rem; }
.card-actions-compact { display: flex; align-items: center; gap: var(--space-2); }

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  background: var(--color-bg-secondary);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full, 999px);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success-500);
  display: inline-block;
}

/* ── Scrollable card row ── */
.indices-scroll {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  padding-bottom: var(--space-1);
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
}

.indices-scroll::-webkit-scrollbar { height: 4px; }
.indices-scroll::-webkit-scrollbar-track { background: transparent; }
.indices-scroll::-webkit-scrollbar-thumb { background: var(--color-neutral-300); border-radius: 4px; }

/* ── Individual index card ── */
.index-card-compact {
  flex: 0 0 160px;
  scroll-snap-align: start;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-lg, 8px);
  background: var(--color-surface-secondary);
  border-left: 3px solid var(--color-neutral-300);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  cursor: default;
  position: relative;
}

.index-card-compact:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md, 0 4px 6px rgba(0,0,0,0.07));
}

/* ── Region color dots + border accents ── */
.region-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

/* A股 red */
.region-a { --region-color: #e53935; border-left-color: var(--region-color); }
.region-a .region-dot { background: var(--region-color); }

/* 港股 purple */
.region-hk { --region-color: #8e24aa; border-left-color: var(--region-color); }
.region-hk .region-dot { background: var(--region-color); }

/* 日经 orange */
.region-jp { --region-color: #f57c00; border-left-color: var(--region-color); }
.region-jp .region-dot { background: var(--region-color); }

/* 韩国 green */
.region-kr { --region-color: #43a047; border-left-color: var(--region-color); }
.region-kr .region-dot { background: var(--region-color); }

/* 澳洲 blue */
.region-au { --region-color: #1e88e5; border-left-color: var(--region-color); }
.region-au .region-dot { background: var(--region-color); }

/* 美股 gold */
.region-us { --region-color: #fbc02d; border-left-color: var(--region-color); }
.region-us .region-dot { background: var(--region-color); }

/* 欧洲 cyan */
.region-eu { --region-color: #00acc1; border-left-color: var(--region-color); }
.region-eu .region-dot { background: var(--region-color); }

.region-default { --region-color: var(--color-neutral-400); border-left-color: var(--region-color); }
.region-default .region-dot { background: var(--region-color); }

/* ── Stale / unavailable ── */
.index-card-compact.stale {
  opacity: 0.75;
}

.index-card-compact.unavailable {
  opacity: 0.5;
}

/* ── Card content ── */
.index-info {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.index-name-compact {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.index-stale-badge {
  font-size: 10px;
  color: var(--color-text-tertiary);
  background: var(--color-neutral-200);
  padding: 0 4px;
  border-radius: 3px;
  white-space: nowrap;
}

.index-data {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.index-price-compact {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-family: var(--font-family-mono);
}

.index-price-compact.muted {
  color: var(--color-text-tertiary);
}

.index-change-compact {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  font-family: var(--font-family-mono);
  display: flex;
  align-items: center;
  gap: 2px;
}

.index-change-compact.muted {
  color: var(--color-text-tertiary);
}

.change-arrow {
  font-size: 9px;
  line-height: 1;
}

/* ── Empty state ── */
.indices-empty-compact {
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* ── Red up / green down ── */
:deep(.text-up) { color: var(--color-text-up, #c62828); }
:deep(.text-down) { color: var(--color-text-down, #2e7d32); }
</style>
