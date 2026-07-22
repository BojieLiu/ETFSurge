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

    <div v-if="hasIndices">
      <div class="region-row" v-for="(items, region) in groupedIndices" :key="region">
        <div class="region-label" :class="'label-' + regionClass(items[0] && items[0].region)">{{ region }}</div>
        <div class="indices-grid">
          <div
            class="index-card"
            v-for="idx in items"
            :key="idx.symbol"
            :class="[
              regionClass(idx.region),
              { stale: !idx.available && idx.price != null }
            ]"
          >
            <div class="card-top">
              <span class="cd-dot" :class="regionClass(idx.region)"></span>
              <span class="cd-name">{{ idx.name }}</span>
              <span v-if="!idx.available && idx.price != null" class="cd-stale">已收盘</span>
            </div>
            <div class="card-body">
              <span class="cd-price" v-if="idx.price != null">{{ formatPrice(idx.price) }}</span>
              <span class="cd-price muted" v-else>—</span>
              <span class="cd-change" v-if="idx.change_pct != null" :class="changeClass(idx.change_pct)">
                <span class="ca" v-if="idx.change_pct > 0">▲</span>
                <span class="ca" v-else-if="idx.change_pct < 0">▼</span>
                {{ formatChange(idx.change_pct) }}
              </span>
              <span class="cd-change muted" v-else-if="idx.price != null">上日收盘</span>
              <span class="cd-change muted" v-else>—</span>
            </div>
          </div>
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

const regionOrder = ['A股', '港股', '日经', '韩国', '澳洲', '美股', '欧洲']

const hasIndices = computed(() => Object.keys(props.globalIndices).length > 0)
const groupedIndices = computed(() => {
  const groups = {}
  for (const r of regionOrder) {
    if (props.globalIndices[r]) {
      groups[r] = props.globalIndices[r]
    }
  }
  return groups
})

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

/* ── Region row: label + cards ── */
.region-row { margin-bottom: 10px; }

.region-label {
  font-size: 11px;
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
  margin-bottom: 6px;
  padding: 0 2px;
}
.region-label.label-region-a { color: #e53935; }
.region-label.label-region-hk { color: #8e24aa; }
.region-label.label-region-jp { color: #f57c00; }
.region-label.label-region-kr { color: #43a047; }
.region-label.label-region-au { color: #1e88e5; }
.region-label.label-region-us { color: #fbc02d; }
.region-label.label-region-eu { color: #00acc1; }

/* ── Card grid: wrap, generous spacing ── */
.indices-grid {
  display: flex;
  flex-wrap: wrap;
  column-gap: 14px;
  row-gap: 16px;
  padding: var(--space-2) 0;
}

.index-card {
  flex: 1 1 145px;
  max-width: 185px;
  min-width: 135px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-xl, 10px);
  background: var(--color-surface-secondary);
  border-left: 3px solid var(--color-neutral-300);
  transition: box-shadow 0.15s;
  cursor: default;
}

.index-card:hover {
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08));
}

.index-card.stale { opacity: 0.75; }

/* ── Region color accent ── */
.cd-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
.region-a .cd-dot { background: #e53935; } .region-a { border-left-color: #e53935; }
.region-hk .cd-dot { background: #8e24aa; } .region-hk { border-left-color: #8e24aa; }
.region-jp .cd-dot { background: #f57c00; } .region-jp { border-left-color: #f57c00; }
.region-kr .cd-dot { background: #43a047; } .region-kr { border-left-color: #43a047; }
.region-au .cd-dot { background: #1e88e5; } .region-au { border-left-color: #1e88e5; }
.region-us .cd-dot { background: #fbc02d; } .region-us { border-left-color: #fbc02d; }
.region-eu .cd-dot { background: #00acc1; } .region-eu { border-left-color: #00acc1; }
.region-default .cd-dot { background: var(--color-neutral-400); }

/* ── Card content ── */
.card-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cd-name { font-size: 12px; font-weight: var(--font-weight-medium); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cd-stale { font-size: 9px; color: var(--color-text-tertiary); background: var(--color-neutral-200); padding: 1px 5px; border-radius: 3px; line-height: 1.4; }

.card-body { display: flex; flex-direction: column; gap: 4px; }
.cd-price { font-size: 15px; font-weight: var(--font-weight-semibold); color: var(--color-text-primary); font-family: var(--font-family-mono); line-height: 1.2; }
.cd-price.muted { color: var(--color-text-tertiary); }
.cd-change { font-size: 12px; font-weight: var(--font-weight-medium); font-family: var(--font-family-mono); }
.cd-change.muted { color: var(--color-text-tertiary); }
.ca { font-size: 8px; line-height: 1; }

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
