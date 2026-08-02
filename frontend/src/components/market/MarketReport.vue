<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">📊 市场综合研判</h2>
      <p class="section-desc">基于实时行情与宏观数据的 AI 市场环境分析</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="action-area">
          <button class="btn-report" @click="generate" :disabled="loading">
            <span v-if="!loading" class="btn-icon">🤖</span>
            <span v-else class="btn-spinner"></span>
            <span>{{ loading ? 'AI 分析中...' : (report ? '重新生成研判' : `生成${marketLabel}研判`) }}</span>
          </button>
          <p v-if="!loading && !report && !error" class="action-hint">点击按钮，AI 将综合分析当前市场环境生成报告</p>
        </div>

        <div v-if="loading" class="loading-bar">
          <div class="loading-bar-inner"></div>
        </div>

        <div v-if="error" class="error">{{ error }}</div>

        <div v-if="report" class="report" v-html="renderMarkdown(report)"></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const report = ref('')
const loading = ref(false)
const error = ref('')

const marketLabels = { A: 'A股', HK: '港股', US: '美股' }
const marketLabel = computed(() => marketLabels[props.marketTab] || props.marketTab || '市场')

const { start: startStream, stop: stopStream } = useLLMStream()

// R4-28: 序号守卫——快速切换 tab 时丢弃过期市场流的 token/状态，
// 避免旧流回调覆盖新市场报告或错乱 loading 状态
let genSeq = 0

async function generate() {
  const seq = ++genSeq
  loading.value = true
  report.value = ''
  error.value = ''
  try {
    // Z31: 发送 market 参数，后端按 marketTab 采集对应市场数据
    await startStream('/llm-report/stream', { symbols: null, market: props.marketTab }, (token) => {
      if (seq !== genSeq) return // 过期市场流 token 丢弃
      report.value += token
    })
  } catch (e) {
    if (e?.name === 'AbortError') return
    if (seq !== genSeq) return
    error.value = '生成失败：' + (e?.message || '网络错误')
  } finally {
    if (seq === genSeq) loading.value = false
  }
}

// R4-28: 切换市场 tab → 取消进行中的旧流、清空旧报告（避免停留港股等旧市场内容）、
// 自动为当前市场重新生成研判
watch(() => props.marketTab, () => {
  stopStream()
  genSeq++ // 使旧 generate 的后续回调失效
  report.value = ''
  error.value = ''
  generate()
})
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-body { padding: var(--space-6); }

.action-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6) 0;
}

.btn-report {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-8);
  font: var(--text-h4);
  color: white;
  background: linear-gradient(135deg, var(--color-brand-600), var(--color-brand-700));
  border: none;
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.btn-report:hover {
  background: linear-gradient(135deg, var(--color-brand-700), var(--color-brand-800));
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  transform: translateY(-1px);
}

.btn-report:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-icon { font-size: var(--font-size-xl); line-height: 1; }

.btn-spinner {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.action-hint {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  text-align: center;
}

.loading-bar {
  height: 3px;
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.loading-bar-inner {
  height: 100%;
  width: 30%;
  background: var(--color-brand-500);
  border-radius: var(--radius-full);
  animation: loadingSlide 1.5s ease-in-out infinite;
}

@keyframes loadingSlide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.error { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.report { margin-top: var(--space-4); line-height: 1.8; }
</style>
