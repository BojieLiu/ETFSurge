<template>
  <div class="ta-modal-mask" @click.self="close">
    <div class="ta-modal" role="dialog" aria-modal="true" :aria-label="`${symbol} 技术分析`">
      <div class="ta-header">
        <h3 class="ta-title">{{ name || symbol }} 技术分析</h3>
        <button class="ta-close" @click="close" aria-label="关闭">✕</button>
      </div>

      <div v-if="loading" class="ta-loading">指标计算中…</div>
      <div v-else-if="error" class="ta-error">
        {{ error }}
        <button class="ta-retry" @click="load">重试</button>
      </div>
      <div v-else class="ta-body">
        <!-- 综合信号 -->
        <div v-if="signalData" class="ta-signal" :class="`ta-signal--${signalData.signal}`">
          <span class="ta-signal-label">综合信号</span>
          <span class="ta-signal-value">{{ signalText }}</span>
          <span v-if="signalData.score !== undefined" class="ta-signal-score">得分 {{ signalData.score }}</span>
          <p v-if="signalData.reason" class="ta-signal-reason">{{ signalData.reason }}</p>
        </div>

        <!-- 关键指标 -->
        <div class="ta-grid">
          <div class="ta-cell">
            <span class="ta-cell-label">RSI(14)</span>
            <span class="ta-cell-value">{{ fmt(ind.rsi) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MACD</span>
            <span class="ta-cell-value">{{ ind.macd ? `${fmt(ind.macd.dif)} / ${fmt(ind.macd.dea)}` : '—' }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">KDJ</span>
            <span class="ta-cell-value">{{ ind.kdj ? `K ${fmt(ind.kdj.k)} D ${fmt(ind.kdj.d)}` : '—' }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MA20</span>
            <span class="ta-cell-value">{{ fmt(ind.ma20) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MA60</span>
            <span class="ta-cell-value">{{ fmt(ind.ma60) }}</span>
          </div>
        </div>

        <p v-if="ind._stale" class="ta-stale">⚠️ {{ ind._stale_note || '数据为过期缓存' }}</p>

        <div class="ta-footer">
          <button class="ta-ai-btn" @click="goAi">🤖 转 AI 分析</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { marketApi } from '../../api'

const props = defineProps({
  symbol: { type: String, required: true },
  name: { type: String, default: '' },
  assetType: { type: String, default: 'A' },
})
const emit = defineEmits(['close', 'ai'])

const loading = ref(false)
const error = ref('')
const ind = ref({})
const signalData = ref(null)

function fmt(v) {
  return v === undefined || v === null ? '—' : Number(v).toFixed(2)
}

const signalText = {
  buy: '🟢 买入',
  hold: '🟡 持有',
  sell: '🔴 卖出',
}[signalData.value?.signal] || signalData.value?.signal || '—'

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [indRes, sigRes] = await Promise.all([
      marketApi.indicators(props.symbol, props.assetType),
      marketApi.signal(props.symbol, props.assetType),
    ])
    ind.value = indRes.data || {}
    signalData.value = sigRes.data || null
  } catch (e) {
    error.value = '指标加载失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
  }
}

function close() {
  emit('close')
}

function goAi() {
  emit('ai', { symbol: props.symbol, name: props.name })
}

onMounted(load)
</script>

<style scoped>
.ta-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-4);
}
.ta-modal {
  width: 420px;
  max-width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  background: var(--color-surface-primary, #fff);
  border-radius: var(--radius-xl);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
  padding: var(--space-4);
}
.ta-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-3); }
.ta-title { margin: 0; font-size: var(--font-size-base); font-weight: 600; }
.ta-close { background: none; border: none; cursor: pointer; font-size: var(--font-size-base); color: var(--color-text-muted); }
.ta-loading { text-align: center; padding: var(--space-6); color: var(--color-text-secondary); }
.ta-error { color: var(--color-danger-700); text-align: center; padding: var(--space-4); }
.ta-retry { margin-left: var(--space-2); padding: 2px 10px; border: 1px solid var(--color-border); border-radius: var(--radius-md); cursor: pointer; background: var(--color-surface-primary); }
.ta-signal { padding: var(--space-3); border-radius: var(--radius-lg); margin-bottom: var(--space-3); }
.ta-signal--buy { background: rgba(229, 72, 77, 0.08); border: 1px solid rgba(229, 72, 77, 0.3); }
.ta-signal--sell { background: rgba(46, 204, 113, 0.08); border: 1px solid rgba(46, 204, 113, 0.3); }
.ta-signal--hold { background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.3); }
.ta-signal-label { font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.ta-signal-value { font-weight: 600; margin-left: var(--space-2); }
.ta-signal-score { font-size: var(--font-size-xs); color: var(--color-text-secondary); margin-left: var(--space-2); }
.ta-signal-reason { margin: var(--space-1) 0 0; font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.ta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.ta-cell { display: flex; flex-direction: column; gap: 2px; padding: var(--space-2) var(--space-3); background: var(--color-surface-secondary, #f5f5f5); border-radius: var(--radius-md); }
.ta-cell-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.ta-cell-value { font-size: var(--font-size-sm); font-family: var(--font-family-mono); }
.ta-stale { margin-top: var(--space-2); font-size: var(--font-size-xs); color: var(--color-warning); }
.ta-footer { margin-top: var(--space-3); text-align: right; }
.ta-ai-btn { padding: var(--space-1.5) var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-primary); cursor: pointer; font-size: var(--font-size-sm); }
.ta-ai-btn:hover { border-color: var(--color-brand-500); color: var(--color-brand-600); }
</style>
