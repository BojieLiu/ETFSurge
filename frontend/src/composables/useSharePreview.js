// useSharePreview — Jinshi-style preview state for poster images.
// openPreview(posterOpts) renders canvas -> blob -> objectURL and shows modal.
// Modal buttons: copy to clipboard (ClipboardItem PNG) / download / close.
import { ref } from 'vue'
import { renderPosterCanvas, canvasToBlob, downloadBlob, copyCanvasToClipboard } from './useSharePoster'

export function useSharePreview() {
  const visible = ref(false)
  const imageUrl = ref('')
  const generating = ref(false)
  const copyState = ref('') // '' | 'ok' | 'fail' | 'unsupported'
  const title = ref('')
  let _blob = null
  let _canvas = null
  let _url = ''

  function _revoke() {
    try {
      if (_url && typeof URL !== 'undefined' && URL.revokeObjectURL) URL.revokeObjectURL(_url)
    } catch { /* noop */ }
    _url = ''
  }

  async function openPreview(posterOpts) {
    generating.value = true
    copyState.value = ''
    title.value = (posterOpts && posterOpts.title) || '分享预览'
    try {
      const canvas = renderPosterCanvas(posterOpts || {})
      if (!canvas) { generating.value = false; return false }
      const blob = await canvasToBlob(canvas)
      if (!blob) { generating.value = false; return false }
      _revoke()
      _blob = blob
      _canvas = canvas
      _url = URL.createObjectURL(blob)
      imageUrl.value = _url
      visible.value = true
      generating.value = false
      return true
    } catch {
      generating.value = false
      return false
    }
  }

  async function copyImage() {
    if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.write !== 'function') {
      copyState.value = 'unsupported'
      return false
    }
    const ok = await copyCanvasToClipboard(_canvas)
    copyState.value = ok ? 'ok' : 'fail'
    return ok
  }

  function downloadImage() {
    if (!_blob) return false
    return downloadBlob(_blob, `etfsurge-share-${Date.now()}.png`)
  }

  function close() {
    visible.value = false
    copyState.value = ''
  }

  return { visible, imageUrl, generating, copyState, title, openPreview, copyImage, downloadImage, close }
}
