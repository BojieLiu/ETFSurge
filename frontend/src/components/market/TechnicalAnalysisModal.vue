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
          <ul v-if="signalData.reasons?.length" class="ta-signal-reasons">
            <li v-for="(r, i) in signalData.reasons" :key="i">{{ r }}</li>
          </ul>
          <p v-else-if="signalData.reason" class="ta-signal-reason">{{ signalData.reason }}</p>
        </div>

        <!-- 关键指标 -->
        <div class="ta-grid">
          <div class="ta-cell">
            <span class="ta-cell-label">RSI(14)</span>
            <span class="ta-cell-value">{{ fmt(ind.rsi) }}</span>
            <span v-if="ind.rsi != null" class="ta-cell-note">{{ rsiText(ind.rsi) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MACD</span>
            <span class="ta-cell-value">{{ ind.macd ? `${fmt(ind.macd.dif)} / ${fmt(ind.macd.dea)}` : '—' }}</span>
            <span v-if="ind.macd" class="ta-cell-note">{{ macdText(ind.macd) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">KDJ</span>
            <span class="ta-cell-value">{{ ind.kdj ? `K ${fmt(ind.kdj.k)} D ${fmt(ind.kdj.d)}` : '—' }}</span>
            <span v-if="ind.kdj && ind.kdj.j != null" class="ta-cell-note">{{ kdjText(ind.kdj) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MA5 / MA20</span>
            <span class="ta-cell-value">{{ fmt(ind.ma5) }} / {{ fmt(ind.ma20) }}</span>
            <span v-if="ind.ma5 != null && ind.ma20 != null" class="ta-cell-note">{{ maText(ind.ma5, ind.ma20) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">MA10 / MA60</span>
            <span class="ta-cell-value">{{ fmt(ind.ma10) }} / {{ fmt(ind.ma60) }}</span>
            <span v-if="ind.ma10 != null && ind.ma60 != null" class="ta-cell-note">{{ maText(ind.ma10, ind.ma60) }}</span>
          </div>
          <div class="ta-cell">
            <span class="ta-cell-label">BOLL 支撑 / 压力</span>
            <span class="ta-cell-value">{{ ind.bollinger ? `${fmt(ind.bollinger.lower)} / ${fmt(ind.bollinger.upper)}` : '—' }}</span>
            <span v-if="ind.bollinger" class="ta-cell-note">{{ bollText(ind.bollinger) }}</span>
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
import { ref, computed, onMounted } from 'vue'
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

// R4-25: signalText 从静态 const 改为 computed —— 旧实现 setup 时求值一次
// （signalData 尚为 null），导致「综合信号」永远显示「—」。
const signalText = computed(() => {
  const s = signalData.value?.signal
  return ({ buy: '🟢 买入', hold: '🟡 持有', sell: '🔴 卖出' })[s] || s || '—'
})

// R4-25: 指标方向解读 —— 每个数值附一行可读结论，辅助投资决策
function rsiText(v) {
  if (v == null) return ''
  if (v < 30) return '超卖区'
  if (v < 40) return '偏弱'
  if (v < 60) return '中性'
  if (v < 70) return '偏强'
  return '超买区'
}
function macdText(m) {
  if (!m || m.dif == null || m.dea == null) return ''
  if (m.dif > m.dea) return m.dif > 0 ? '金叉·多头' : '金叉·偏多'
  return m.dif < 0 ? '死叉·空头' : '死叉·偏空'
}
function kdjText(k) {
  if (!k || k.k == null || k.d == null) return ''
  const j = k.j
  if (j != null && j > 100) return `${k.k > k.d ? '金叉' : '死叉'}·J超买`
  if (j != null && j < 0) return `${k.k > k.d ? '金叉' : '死叉'}·J超卖`
  return k.k > k.d ? '金叉' : '死叉'
}
function maText(short, long) {
  if (short == null || long == null) return ''
  const diff = Math.abs((short - long) / long)
  return short > long ? `多头排列（短>长 ${(diff * 100).toFixed(1)}%）` : `空头排列（短<长 ${(diff * 100).toFixed(1)}%）`
}
function bollText(b) {
  if (!b || b.upper == null || b.lower == null) return ''
  return `支撑 ${fmt(b.lower)} / 压力 ${fmt(b.upper)}`
}

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
.ta-signal-reasons { margin: var(--space-1) 0 0; padding-left: var(--space-4); font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.ta-signal-reasons li { margin: 2px 0; }
.ta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
.ta-cell { display: flex; flex-direction: column; gap: 2px; padding: var(--space-2) var(--space-3); background: var(--color-surface-secondary, #f5f5f5); border-radius: var(--radius-md); }
.ta-cell-note { font-size: var(--font-size-2xs); color: var(--color-text-tertiary); }
.ta-cell-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.ta-cell-value { font-size: var(--font-size-sm); font-family: var(--font-family-mono); }
.ta-stale { margin-top: var(--space-2); font-size: var(--font-size-xs); color: var(--color-warning); }
.ta-footer { margin-top: var(--space-3); text-align: right; }
.ta-ai-btn { padding: var(--space-1.5) var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-primary); cursor: pointer; font-size: var(--font-size-sm); }
.ta-ai-btn:hover { border-color: var(--color-brand-500); color: var(--color-brand-600); }
</style>
