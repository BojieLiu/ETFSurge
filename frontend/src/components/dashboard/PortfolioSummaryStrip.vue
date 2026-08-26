<template>
  <component
    :is="interactive ? 'button' : 'div'"
    class="pss"
    :class="{ 'pss--clickable': interactive }"
    :aria-busy="loading"
    :aria-label="ariaLabel"
    @click="onClick"
  >
    <!-- loading（首次拉取未完成）：骨架行，固定高度防 CLS -->
    <template v-if="!attempted">
      <span class="pss-skeleton pss-skeleton--label" aria-hidden="true"></span>
      <span class="pss-skeleton" aria-hidden="true"></span>
      <span class="pss-skeleton pss-skeleton--sm" aria-hidden="true"></span>
    </template>

    <!-- error：诚实降级，禁止 ¥0 冒充成功 -->
    <template v-else-if="error">
      <span class="pss-icon" aria-hidden="true">⚠️</span>
      <span class="pss-msg">盈亏数据暂不可用 · 点击重试</span>
    </template>

    <!-- empty：两仓均无持仓 -->
    <template v-else-if="empty">
      <span class="pss-icon" aria-hidden="true">📊</span>
      <span class="pss-msg">还没有持仓 · 去组合页添加</span>
      <span class="pss-arrow" aria-hidden="true">›</span>
    </template>

    <!-- ready -->
    <template v-else>
      <span class="pss-icon" aria-hidden="true">💰</span>
      <span class="pss-item">总仓位 <b class="pss-num">¥{{ formatNum(totalAll) }}</b></span>
      <span class="pss-sep" aria-hidden="true"></span>
      <span class="pss-item">当日合计
        <b class="pss-num" :class="pnlTotal > 0 ? 'text-up' : pnlTotal < 0 ? 'text-down' : ''">
          {{ signed(pnlTotal) }}¥{{ formatNum(Math.abs(pnlTotal)) }}
        </b>
        <b v-if="weightedChange" class="pss-pct" :class="weightedChange > 0 ? 'text-up' : 'text-down'">
          {{ signed(weightedChange) }}{{ Math.abs(weightedChange).toFixed(2) }}%
        </b>
      </span>
      <span class="pss-sep" aria-hidden="true"></span>
      <span class="pss-item pss-sub">场内
        <b class="pss-num-sm" :class="pnlOn > 0 ? 'text-up' : pnlOn < 0 ? 'text-down' : ''">
          {{ signed(pnlOn) }}¥{{ formatNum(Math.abs(pnlOn)) }}
        </b>
      </span>
      <span class="pss-item pss-sub">场外
        <b class="pss-num-sm" :class="pnlOff > 0 ? 'text-up' : pnlOff < 0 ? 'text-down' : ''">
          {{ signed(pnlOff) }}¥{{ formatNum(Math.abs(pnlOff)) }}
        </b>
      </span>
      <span v-if="lastUpdated" class="pss-updated">更新于 {{ lastUpdated }}</span>
      <span class="pss-arrow" aria-hidden="true">›</span>
    </template>
  </component>
</template>

<script setup>
// round34-B7 批复①：一行式组合摘要条（总资产/当日盈亏聚合只读，点击跳组合页）。
// 单根约束：根节点前不得放 HTML 注释——多根 fragment 会使 test-utils 点击绑定到注释节点。
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  totalAll: { type: Number, default: 0 },
  pnlOn: { type: Number, default: 0 },
  pnlOff: { type: Number, default: 0 },
  pnlTotal: { type: Number, default: 0 },
  weightedChange: { type: Number, default: 0 },
  /** 首次请求是否已完成（success 或 failure） */
  attempted: { type: Boolean, default: false },
  /** daily-pnl 拉取失败（useDashboardData.pnlError） */
  error: { type: Boolean, default: false },
  lastUpdated: { type: String, default: null },
})

const emit = defineEmits(['retry'])
const router = useRouter()

const loading = computed(() => !props.attempted)
const empty = computed(() => props.attempted && !props.error && props.totalAll === 0)
const interactive = computed(() => !loading.value)

const ariaLabel = computed(() => {
  if (loading.value) return '组合摘要加载中'
  if (props.error) return '盈亏数据不可用，点击重试'
  if (empty.value) return '暂无持仓，点击前往组合页添加'
  return `总仓位 ${props.totalAll} 元，当日盈亏 ${props.pnlTotal} 元，点击查看组合详情`
})

function onClick() {
  if (loading.value) return
  if (props.error) {
    emit('retry')
    return
  }
  // error 态外的所有点击都导向组合页（ready 看明细 / empty 去添加）
  router.push('/portfolio-analysis')
}

function formatNum(n) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

// 正负号：颜色之外的第二编码通道（色弱友好）。0 不加符号。
function signed(n) {
  if (!n) return ''
  return n > 0 ? '+' : '-'
}
</script>

<style scoped>
.pss {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  font: var(--text-body-sm);
  color: var(--color-text-primary);
  text-align: left;
  cursor: default;
}
.pss--clickable {
  cursor: pointer;
  transition: var(--transition-fast);
}
.pss--clickable:hover {
  border-color: var(--color-border-medium);
}
.pss:focus-visible {
  outline: 2px solid var(--color-brand-600);
  outline-offset: 1px;
}
.pss-icon { flex-shrink: 0; }
.pss-item { display: inline-flex; align-items: baseline; gap: var(--space-1); white-space: nowrap; }
.pss-sub { color: var(--color-text-secondary); }
.pss-sep { width: 1px; height: 14px; background: var(--color-border-light); flex-shrink: 0; }
.pss-num { font-family: var(--font-family-mono); font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); }
.pss-num-sm { font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); }
.pss-pct { font-size: var(--font-size-xs); }
.pss-updated { margin-left: auto; font-size: var(--font-size-xs); color: var(--color-text-tertiary); white-space: nowrap; }
.pss-arrow { color: var(--color-text-tertiary); flex-shrink: 0; }
.pss-msg { color: var(--color-text-secondary); }

/* 骨架：高度恒定，替换零重排 */
.pss-skeleton {
  display: inline-block;
  height: 1rem;
  width: 160px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-surface-tertiary) 25%, var(--color-surface-secondary) 50%, var(--color-surface-tertiary) 75%);
  background-size: 200% 100%;
  animation: pss-shimmer 1.5s ease-in-out infinite;
}
.pss-skeleton--label { width: 72px; }
.pss-skeleton--sm { width: 96px; margin-left: auto; }
@keyframes pss-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .pss-skeleton { animation: none; }
}
@media (max-width: 640px) {
  .pss-sub, .pss-updated { display: none; }
}
</style>
