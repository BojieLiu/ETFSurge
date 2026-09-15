// useSharePoster — zero-dep canvas poster (A-route, frontend-only).
// Draws 750px share image: header(logo text + ETFSurge) / title / modelLine / body / footer.
// Preview flow (Jinshi-style): renderPosterCanvas -> canvasToBlob -> preview URL,
// then modal offers copy-to-clipboard / download.
function wrapText(ctx, text, maxWidth) {
  const lines = []
  const paras = String(text ?? '').split('\n')
  for (const p of paras) {
    if (!p) { lines.push(''); continue }
    let line = ''
    for (const ch of p) {
      const t = line + ch
      if (ctx.measureText(t).width > maxWidth && line) {
        lines.push(line)
        line = ch
      } else {
        line = t
      }
    }
    lines.push(line)
  }
  return lines
}

export function formatPosterTime(d) {
  try {
    const t = d instanceof Date ? d : new Date()
    const p = (n) => String(n).padStart(2, '0')
    return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:${p(t.getMinutes())}`
  } catch {
    return ''
  }
}

export function renderPosterCanvas(opts) {
  const { title, modelLine, body, disclaimer } = opts || {}
  if (typeof document === 'undefined') return null
  const W = 750
  const PAD = 36
  const canvas = document.createElement('canvas')
  canvas.width = W
  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  const titleFont = '600 30px sans-serif'
  const metaFont = '400 22px sans-serif'
  const bodyFont = '400 24px sans-serif'
  const footFont = '400 20px sans-serif'
  const maxW = W - PAD * 2

  ctx.font = titleFont
  const titleLines = wrapText(ctx, title || 'ETFSurge 分享', maxW)
  ctx.font = bodyFont
  const rawBody = String(body ?? '').slice(0, 2000)
  const bodyLines = wrapText(ctx, rawBody, maxW)
  ctx.font = footFont
  const footLines = wrapText(ctx, disclaimer || '', maxW)

  const headerH = 110
  const titleH = titleLines.length * 42
  const metaH = 40
  const bodyH = bodyLines.length * 36
  const footH = footLines.length * 30
  const H = headerH + titleH + metaH + 24 + bodyH + 32 + footH + 60
  canvas.height = Math.min(Math.max(H, 420), 4000)

  // bg
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, W, canvas.height)
  // header bar
  ctx.fillStyle = '#1e40af'
  ctx.fillRect(0, 0, W, headerH)
  ctx.fillStyle = '#ffffff'
  ctx.font = '700 34px sans-serif'
  ctx.fillText('⚡ ETFSurge', PAD, 62)
  ctx.font = '400 20px sans-serif'
  ctx.fillStyle = '#bfdbfe'
  const ts = formatPosterTime(new Date())
  ctx.fillText(ts, W - PAD - ctx.measureText(ts).width, 62)

  let y = headerH + 44
  // title
  ctx.fillStyle = '#111827'
  ctx.font = titleFont
  for (const l of titleLines) { ctx.fillText(l, PAD, y); y += 42 }
  // model line pill
  y += 6
  const m = String(modelLine || '模型未知')
  ctx.font = metaFont
  const pillW = Math.min(ctx.measureText(m).width + 28, maxW)
  ctx.fillStyle = '#eff6ff'
  ctx.fillRect(PAD, y - 28, pillW, 36)
  ctx.fillStyle = '#1d4ed8'
  ctx.fillText(m, PAD + 14, y)
  y += 34
  // divider
  ctx.fillStyle = '#e5e7eb'
  ctx.fillRect(PAD, y, maxW, 2)
  y += 34
  // body
  ctx.fillStyle = '#1f2937'
  ctx.font = bodyFont
  for (const l of bodyLines) {
    if (y > canvas.height - 90) break
    ctx.fillText(l, PAD, y)
    y += 36
  }
  // footer
  ctx.fillStyle = '#6b7280'
  ctx.font = footFont
  for (const l of footLines) { ctx.fillText(l, PAD, y); y += 30 }

  return canvas
}

export function canvasToBlob(canvas) {
  return new Promise((resolve) => {
    try {
      if (!canvas || !canvas.toBlob) { resolve(null); return }
      canvas.toBlob((b) => {
        if (b) { resolve(b); return }
        // Fallback: toBlob returned null — use toDataURL + fetch
        try {
          const dataUrl = canvas.toDataURL('image/png')
          fetch(dataUrl).then(r => r.blob()).then(blob => resolve(blob)).catch(() => resolve(null))
        } catch { resolve(null) }
      }, 'image/png')
    } catch {
      resolve(null)
    }
  })
}

export function downloadBlob(blob, filename) {
  try {
    if (!blob || typeof document === 'undefined' || typeof URL === 'undefined') return false
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename || `etfsurge-share-${Date.now()}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 4000)
    return true
  } catch {
    return false
  }
}

// Copy PNG to system clipboard (Chromium ClipboardItem path).
// Returns true on success, false when unsupported/denied (caller toasts).
export async function copyCanvasToClipboard(canvas) {
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return false
    const Ctor = typeof ClipboardItem !== 'undefined' ? ClipboardItem : (typeof window !== 'undefined' ? window.ClipboardItem : undefined)
    if (!Ctor || typeof navigator.clipboard.write !== 'function') return false
    const blob = await canvasToBlob(canvas)
    if (!blob) return false
    await navigator.clipboard.write([new Ctor({ 'image/png': blob })])
    return true
  } catch {
    return false
  }
}

// Compat: direct-download path kept for callers not yet on preview flow.
export async function exportPoster(opts) {
  const { filename } = opts || {}
  try {
    const canvas = renderPosterCanvas(opts)
    if (!canvas) return false
    const blob = await canvasToBlob(canvas)
    if (!blob) return false
    return downloadBlob(blob, filename)
  } catch {
    return false
  }
}

export function useSharePoster() {
  return { exportPoster, renderPosterCanvas, canvasToBlob, downloadBlob, copyCanvasToClipboard, formatPosterTime }
}
