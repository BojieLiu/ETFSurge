// useCopy — clipboard with execCommand fallback (jsdom-safe)
import { ref } from 'vue'

export function useCopy() {
  const copied = ref(false)

  async function copyText(text) {
    const s = String(text ?? '')
    if (!s) return false
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(s)
        copied.value = true
        return true
      }
    } catch {
      // fall through to execCommand
    }
    try {
      if (typeof document === 'undefined') return false
      const ta = document.createElement('textarea')
      ta.value = s
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand ? document.execCommand('copy') : false
      document.body.removeChild(ta)
      copied.value = !!ok
      return !!ok
    } catch {
      return false
    }
  }

  return { copied, copyText }
}

export function buildLLMCopyText(content, modelLine) {
  const body = String(content ?? '').trim()
  const m = String(modelLine ?? '').trim()
  return m ? `${body}\n\n${m}` : body
}

export function buildNewsCopyText(item) {
  const parts = []
  if (item && item.title) parts.push(String(item.title))
  if (item && (item.content || item.ai_summary)) {
    const c = String(item.content || item.ai_summary)
    parts.push(c.length > 300 ? c.slice(0, 300) + '…' : c)
  }
  const meta = []
  if (item && item.source) meta.push(`来源：${item.source}`)
  if (item && item.time) meta.push(String(item.time))
  if (item && item.url) meta.push(String(item.url))
  if (meta.length) parts.push(meta.join(' | '))
  return parts.join('\n')
}
