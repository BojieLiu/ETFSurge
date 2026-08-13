<template>
  <!-- F24 (round6 §17.4): 容器内容驱动（无 340px 定高）——CLS 由卡片级等高骨架屏保障 -->
  <div class="summary-grid">
    <!-- 总仓位（独占一行，突出显示） -->
    <AppCard v-if="activeTab === 'combined'" layout="horizontal" icon="💰" class="summary-card summary-card--total" bordered padded hoverable>
      <p class="summary-label">总仓位</p>
      <p class="summary-value summary-value--total" :class="loading ? 'skeleton' : ''" aria-live="polite">
        <span v-if="loading" class="value-skeleton" aria-hidden="true"></span>
        <span v-else>¥{{ formatNum(totalAll) }}</span>
      </p>
    </AppCard>

    <!-- 当日盈亏组 -->
    <p class="summary-group-label">当日盈亏</p>

    <!-- 场内当日盈亏 -->
    <AppCard v-if="activeTab !== 'off_exchange'" layout="horizontal"
      :icon="pnlOn >= 0 ? '📈' : '📉'"
      :style="pnlOn >= 0 ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : { '--app-card-icon-bg': 'var(--color-bg-danger-subtle)' }"
      class="summary-card" bordered padded hoverable
    >
      <p class="summary-label">场内当日盈亏</p>
      <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOn >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
        <span v-if="loading" class="value-skeleton" aria-hidden="true"></span>
        <span v-else>¥{{ signed(pnlOn) }}{{ formatNum(Math.abs(pnlOn)) }}</span>
      </p>
    </AppCard>

    <!-- 场外当日盈亏 -->
    <AppCard v-if="activeTab !== 'on_exchange'" layout="horizontal"
      :icon="pnlOff >= 0 ? '📈' : '📉'"
      :style="pnlOff >= 0 ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : { '--app-card-icon-bg': 'var(--color-bg-danger-subtle)' }"
      class="summary-card" bordered padded hoverable
    >
      <p class="summary-label">场外当日盈亏</p>
      <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOff >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
        <span v-if="loading" class="value-skeleton" aria-hidden="true"></span>
        <span v-else>¥{{ signed(pnlOff) }}{{ formatNum(Math.abs(pnlOff)) }}</span>
      </p>
    </AppCard>

    <!-- 累计盈亏组 -->
    <p class="summary-group-label">累计盈亏</p>

    <!-- Cumulative P&L loading skeletons -->
    <template v-if="pnlHistoryLoading">
      <AppCard v-if="activeTab !== 'off_exchange'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <span class="value-skeleton" aria-hidden="true"></span>
          <!-- F24: 等高骨架——与完成态 estimate-hint 行同构占位 -->
          <p class="estimate-hint"><span class="value-skeleton value-skeleton--sm" aria-hidden="true"></span></p>
        </div>
      </AppCard>
      <AppCard v-if="activeTab !== 'on_exchange'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <span class="value-skeleton" aria-hidden="true"></span>
          <p class="estimate-hint"><span class="value-skeleton value-skeleton--sm" aria-hidden="true"></span></p>
        </div>
      </AppCard>
      <AppCard v-if="activeTab === 'combined'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <span class="value-skeleton" aria-hidden="true"></span>
          <p class="estimate-hint"><span class="value-skeleton value-skeleton--sm" aria-hidden="true"></span></p>
        </div>
      </AppCard>
    </template>

    <!-- Cumulative P&L cards -->
    <template v-else>
      <AppCard v-if="activeTab !== 'off_exchange' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">场内累计盈亏</p>
        <p class="summary-value" :class="findCumulativePnl('on_exchange') >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ signed(findCumulativePnl('on_exchange')) }}{{ formatNum(Math.abs(findCumulativePnl('on_exchange'))) }}
            <span class="pnl-pct">({{ signedPct(findCumulativePnlPct('on_exchange')) }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
        <!-- R66: 含估算份额 → tooltip 标注估算成本占比 -->
        <p v-if="estimatedRatio('on_exchange') > 0" class="estimate-hint">
          <AppTooltip placement="bottom-start" :content="`含估算成本 ${Math.round(estimatedRatio('on_exchange') * 100)}%（按目标权重估算）`">
            估算 {{ Math.round(estimatedRatio('on_exchange') * 100) }}%
          </AppTooltip>
        </p>
      </AppCard>

      <AppCard v-if="activeTab !== 'on_exchange' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">场外累计盈亏</p>
        <p class="summary-value" :class="findCumulativePnl('off_exchange') >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ signed(findCumulativePnl('off_exchange')) }}{{ formatNum(Math.abs(findCumulativePnl('off_exchange'))) }}
            <span class="pnl-pct">({{ signedPct(findCumulativePnlPct('off_exchange')) }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
        <!-- R66: 含估算份额 → tooltip 标注估算成本占比 -->
        <p v-if="estimatedRatio('off_exchange') > 0" class="estimate-hint">
          <AppTooltip placement="bottom-start" :content="`含估算成本 ${Math.round(estimatedRatio('off_exchange') * 100)}%（按目标权重估算）`">
            估算 {{ Math.round(estimatedRatio('off_exchange') * 100) }}%
          </AppTooltip>
        </p>
      </AppCard>

      <AppCard v-if="activeTab === 'combined' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">总累计盈亏</p>
        <p class="summary-value" :class="pnlHistory.summary.total_cumulative_pnl >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ signed(pnlHistory.summary.total_cumulative_pnl) }}{{ formatNum(Math.abs(pnlHistory.summary.total_cumulative_pnl)) }}
            <span class="pnl-pct">({{ signedPct(pnlHistory.summary.total_cumulative_pnl_pct) }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
        <!-- R66: 总览含估算份额 → tooltip 标注 -->
        <p v-if="(pnlHistory.summary.estimated_ratio || 0) > 0" class="estimate-hint">
          <AppTooltip placement="bottom-start" :content="`含估算成本 ${Math.round(pnlHistory.summary.estimated_ratio * 100)}%（按目标权重估算）`">
            估算 {{ Math.round(pnlHistory.summary.estimated_ratio * 100) }}%
          </AppTooltip>
        </p>
      </AppCard>
    </template>

    <!-- 数据刷新指示器（常驻占位，零 CLS：数据加载不新增行） -->
    <p class="summary-updated">更新于 {{ lastUpdated || '--:--:--' }}</p>
  </div>
</template>

<script setup>
import AppCard from '../ui/AppCard.vue'
import AppTooltip from '../ui/AppTooltip.vue'

const props = defineProps({
  activeTab: { type: String, required: true },
  totalAll: { type: Number, required: true },
  pnlOn: { type: Number, required: true },
  pnlOff: { type: Number, required: true },
  pnlTotal: { type: Number, required: true },
  pnlHistory: { type: Object, default: null },
  pnlHistoryLoading: { type: Boolean, default: false },
  loading: { type: Boolean, default: true },
  lastUpdated: { type: String, default: null }
})

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

// 百分比字符串（toFixed(2) 产物）加正负号：'+33.33%' / '-33.33%' / '0.00%'
function signedPct(pctStr) {
  const v = parseFloat(pctStr) || 0
  if (v === 0) return '0.00'
  return (v > 0 ? '+' : '-') + Math.abs(v).toFixed(2)
}

function findCumulativePnl(type) {
  // Uses backend summary.by_type (Sprint 2.3)
  const h = props.pnlHistory?.summary?.by_type?.[type]
  return h?.cumulative_pnl ?? 0
}

function findCumulativePnlPct(type) {
  // Uses backend summary.by_type (Sprint 2.3)
  const h = props.pnlHistory?.summary?.by_type?.[type]
  return (h?.cumulative_pnl_pct || 0).toFixed(2)
}

// R66: by_type 估算占比（后端 R65 新增 estimated_ratio 字段）
function estimatedRatio(type) {
  return props.pnlHistory?.summary?.by_type?.[type]?.estimated_ratio || 0
}

// F24 (round6 §17.4): 移除容器级定高 GRID_MIN_HEIGHT='340px'——
// 旧实现容器定高 + 数据注入后内容超高 → CLS 0.189。
// 现改为内容驱动：卡片 min-height + 加载/完成两态等高骨架（见 .estimate-hint 占位行）。
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}

.summary-card {
  /* P0-4 (R4-19) + F24: 卡片固定最小高度——加载态（单行骨架 + 估算占位行）与完成态
     （数字 + 估算提示）高度一致，消除首屏数据到达时的布局偏移（CLS）。 */
  min-height: 110px;
  transition: var(--transition-fast);
}

/* 总仓位卡独占一行（突出主数字） */
.summary-card--total {
  grid-column: 1 / -1;
}

/* 逻辑分组标签（当日盈亏 / 累计盈亏） */
.summary-group-label {
  grid-column: 1 / -1;
  margin: var(--space-2) 0 0;
  font: var(--text-body-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}

.summary-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.summary-value {
  min-height: 1.5rem;
}

.summary-value.skeleton { color: transparent; }

/* P0-4: 单行骨架占位——高度与 text-h2 数字行严格一致，替换时零重排 */
.value-skeleton {
  display: inline-block;
  width: 120px;
  height: 1.5rem;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--color-surface-tertiary) 25%,
    var(--color-surface-secondary) 50%,
    var(--color-surface-tertiary) 75%
  );
  background-size: 200% 100%;
  animation: summary-shimmer 1.5s ease-in-out infinite;
}

@keyframes summary-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .value-skeleton { animation: none; }
}

.summary-label {
  margin: 0 0 var(--space-1);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
}

.summary-value {
  margin: 0;
  font-family: var(--font-family-mono);
  font: var(--text-h2);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
  white-space: normal;
  overflow-wrap: anywhere;
}

/* round14 P1-K: 盈亏数字红涨绿跌——scoped `.summary-value` (0,2,0) 覆盖全局
   `.text-up/.text-down` (0,1,0)，此处用更高特异性 (0,3,0) 组合选择器恢复
   红涨绿跌（docs/archived/round14 §2.9/§5 P1-K；删本规则即测试失败）。 */
.summary-value.text-up { color: var(--color-text-up); }
.summary-value.text-down { color: var(--color-text-down); }

/* 总仓位主数字放大一档（--text-h2 → --text-h1）；须定义在 .summary-value 之后才能覆盖其 font shorthand */
.summary-value--total {
  font: var(--text-h1);
}

.pnl-pct {
  font: var(--text-body-sm);
}

.estimate-hint {
  margin: var(--space-1) 0 0;
  font: var(--text-body-xs);
  color: var(--color-text-secondary);
  min-height: 1rem; /* F24: 占位行恒有高度（加载骨架/完成文本同高） */
}

/* F24: 小号骨架——estimate-hint 占位行使用 */
.value-skeleton--sm {
  width: 80px;
  height: 0.9rem;
}

/* 数据刷新指示器（常驻渲染，占位高度固定 → 加载完成零布局偏移） */
.summary-updated {
  grid-column: 1 / -1;
  min-height: 1rem;
  margin: var(--space-1) 0 0;
  font: var(--text-body-xs);
  color: var(--color-text-tertiary);
  text-align: right;
}


@media (max-width: 480px) {
  .summary-grid { grid-template-columns: 1fr; }
  .summary-value { font-size: var(--font-size-lg); }
}
</style>
