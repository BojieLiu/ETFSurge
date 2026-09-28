// useSharePoster — zero-dep canvas poster (A-route, frontend-only).
// Draws 750px share image: header(logo text + ETFSurge) / title / modelLine / body / footer.
// Preview flow (Jinshi-style): renderPosterCanvas -> canvasToBlob -> preview URL,
// then modal offers copy-to-clipboard / download.
//
// Body pipeline (B-route, structured Markdown rendering):
//   raw markdown -> parseBodyBlocks -> wrapSegments -> drawRichLine
// so that `##` / `**` / `-` / `---` never leak onto the canvas as literal text
// (previously wrapText drew the raw source verbatim).
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

// ── Markdown -> blocks (pure, unit-tested) ──────────────────────────────
// Block kinds: heading | bullet | divider | quote | para | blank
//   bullet: { marker } — '• ' for unordered, 'N. ' for ordered (marker kept out
//     of the wrapped segments; drawn at PAD with hanging indent for the text).
function _cleanInlineText(s) {
  return String(s ?? '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(`{1,3})([^`]*?)\1/g, '$2')
}

function _stripMdChars(s) {
  return String(s ?? '')
    .replace(/\*\*/g, '')
    .replace(/__/g, '')
    .replace(/~~/g, '')
    .replace(/`/g, '')
}

export function parseInlineSegments(text) {
  const src = _cleanInlineText(text)
  const segs = []
  const re = /(\*\*.+?\*\*|__.*?__)/g
  let last = 0
  let m
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) {
      const t = _stripMdChars(src.slice(last, m.index))
      if (t) segs.push({ t, bold: false })
    }
    const inner = _stripMdChars(m[0].slice(2, -2))
    if (inner) segs.push({ t: inner, bold: true })
    last = m.index + m[0].length
    // Guard against zero-length match loops (should not happen with .+? but be safe)
    if (m[0].length === 0) re.lastIndex += 1
  }
  if (last < src.length) {
    const t = _stripMdChars(src.slice(last))
    if (t) segs.push({ t, bold: false })
  }
  return segs
}

export function parseBodyBlocks(text) {
  const raws = String(text ?? '').split('\n')
  const blocks = []
  for (const raw of raws) {
    const line = String(raw).replace(/\s+$/, '')
    if (!line.trim()) { blocks.push({ kind: 'blank' }); continue }
    const t = line.trim()
    if (/^(---|\*\*\*|___)\s*$/.test(t)) { blocks.push({ kind: 'divider' }); continue }
    let m = t.match(/^(#{1,4})\s+(.*)$/)
    if (m) {
      blocks.push({ kind: 'heading', level: m[1].length, segments: parseInlineSegments(m[2]) })
      continue
    }
    m = t.match(/^>\s?(.*)$/)
    if (m) {
      blocks.push({ kind: 'quote', segments: parseInlineSegments(m[1]) })
      continue
    }
    m = t.match(/^(\d+)[.)、．]\s+(.*)$/)
    if (m) {
      blocks.push({ kind: 'bullet', marker: `${m[1]}. `, segments: parseInlineSegments(m[2]) })
      continue
    }
    m = t.match(/^([-*•·＋+])\s+(.*)$/)
    if (m) {
      blocks.push({ kind: 'bullet', marker: '• ', segments: parseInlineSegments(m[2]) })
      continue
    }
    // Tolerant: "-**bold…**" without a space after the dash (seen in LLM output)
    m = t.match(/^([-*•·])(\*\*.+)$/)
    if (m) {
      blocks.push({ kind: 'bullet', marker: '• ', segments: parseInlineSegments(m[2]) })
      continue
    }
    blocks.push({ kind: 'para', segments: parseInlineSegments(t) })
  }
  // Collapse 3+ consecutive blanks to at most 2 (avoid hole-punching long reports)
  const out = []
  let blanks = 0
  for (const b of blocks) {
    if (b.kind === 'blank') {
      blanks += 1
      if (blanks <= 2) out.push(b)
    } else {
      blanks = 0
      out.push(b)
    }
  }
  // Drop leading/trailing blanks for tighter top/bottom rhythm
  while (out.length && out[0].kind === 'blank') out.shift()
  while (out.length && out[out.length - 1].kind === 'blank') out.pop()
  return out
}

// ── Wrapping / drawing (needs a canvas 2d ctx for measureText) ──────────
function _charWidth(ctx, ch, bold, fontNormal, fontBold) {
  ctx.font = bold ? fontBold : fontNormal
  return ctx.measureText(ch).width
}

// Greedy char-level wrap that preserves bold runs. Returns lines, each line is
// an array of { t, bold } runs. Empty input -> [[]] (caller filters).
export function wrapSegments(ctx, segs, maxWidth, fontNormal, fontBold) {
  const lines = []
  let cur = []
  let curW = 0
  const pushCur = () => {
    if (cur.length) lines.push(cur)
    cur = []
    curW = 0
  }
  for (const s of segs || []) {
    if (!s || !s.t) continue
    let buf = ''
    let bufW = 0
    const flush = () => {
      if (buf) { cur.push({ t: buf, bold: !!s.bold }); curW += bufW; buf = ''; bufW = 0 }
    }
    for (const ch of String(s.t)) {
      const w = _charWidth(ctx, ch, !!s.bold, fontNormal, fontBold)
      if (curW + bufW + w > maxWidth && (cur.length || buf)) {
        flush()
        pushCur()
      }
      buf += ch
      bufW += w
    }
    flush()
  }
  pushCur()
  return lines.length ? lines : [[]]
}

function drawRichLine(ctx, line, x, y, fontNormal, fontBold, colorNormal, colorBold) {
  let cx = x
  for (const s of line) {
    ctx.font = s.bold ? fontBold : fontNormal
    ctx.fillStyle = s.bold ? colorBold : colorNormal
    ctx.fillText(s.t, cx, y)
    cx += ctx.measureText(s.t).width
  }
  return cx
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

  // Fonts — body 22px (was 24: too cramped at 750px after CJK wrapping)
  const titleFont = '600 30px sans-serif'
  const metaFont = '400 22px sans-serif'
  const bodyFont = '400 22px sans-serif'
  const bodyBoldFont = '600 22px sans-serif'
  const h1Font = '700 30px sans-serif'
  const h2Font = '700 27px sans-serif'
  const h3Font = '700 24px sans-serif'
  const footFont = '400 20px sans-serif'
  const BODY_LH = 36
  const H_LH = 40
  const BULLET_INDENT = 30
  const maxW = W - PAD * 2

  const TEXT = '#1f2937'
  const STRONG = '#111827'
  const MUTED = '#4b5563'

  ctx.font = titleFont
  const titleLines = wrapText(ctx, title || 'ETFSurge 分享', maxW)
  ctx.font = footFont
  const footLines = wrapText(ctx, disclaimer || '', maxW)

  // Layout pass: blocks -> wrapped lines (measure only, no drawing yet)
  const rawBody = String(body ?? '').slice(0, 2000)
  const blocks = parseBodyBlocks(rawBody)
  // op: { kind, lines, font, marker?, h }
  const ops = []
  let hasContent = false
  for (const b of blocks) {
    if (b.kind === 'blank') { ops.push({ kind: 'blank', lines: [], h: 12 }); continue }
    if (b.kind === 'divider') { ops.push({ kind: 'divider', lines: [], h: 30 }); continue }
    if (b.kind === 'heading') {
      const font = b.level <= 1 ? h1Font : b.level === 2 ? h2Font : h3Font
      const lines = wrapSegments(ctx, b.segments, maxW, font, font).filter((l) => l.length)
      if (!lines.length) continue
      hasContent = true
      ops.push({ kind: 'heading', lines, font, h: 10 + lines.length * H_LH + 4 })
      continue
    }
    if (b.kind === 'bullet') {
      const lines = wrapSegments(ctx, b.segments, maxW - BULLET_INDENT, bodyFont, bodyBoldFont)
        .filter((l) => l.length)
      if (!lines.length) continue
      hasContent = true
      ops.push({ kind: 'bullet', marker: b.marker, lines, h: lines.length * BODY_LH + 8 })
      continue
    }
    // para | quote
    const lines = wrapSegments(ctx, b.segments, maxW - (b.kind === 'quote' ? 14 : 0), bodyFont, bodyBoldFont)
      .filter((l) => l.length)
    if (!lines.length) { ops.push({ kind: 'blank', lines: [], h: 12 }); continue }
    hasContent = true
    ops.push({ kind: b.kind, lines, h: lines.length * BODY_LH + 10 })
  }
  if (!hasContent) {
    ops.push({
      kind: 'para',
      lines: [[{ t: '（暂无内容）', bold: false }]],
      h: BODY_LH + 10,
    })
  }
  const bodyH = ops.reduce((a, o) => a + o.h, 0)

  const headerH = 110
  const titleH = titleLines.length * 42
  const metaH = 40
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
  // body (structured)
  let truncated = false
  const overflowAt = () => y > canvas.height - 90
  for (const op of ops) {
    if (truncated) break
    if (op.kind === 'blank') { y += op.h; continue }
    if (op.kind === 'divider') {
      if (!overflowAt()) {
        ctx.fillStyle = '#e5e7eb'
        ctx.fillRect(PAD, y + 8, maxW, 2)
      }
      y += op.h
      continue
    }
    if (op.kind === 'heading') {
      y += 10
      for (const line of op.lines) {
        if (overflowAt()) { truncated = true; break }
        ctx.fillStyle = STRONG
        drawRichLine(ctx, line, PAD, y, op.font, op.font, STRONG, STRONG)
        y += H_LH
      }
      y += 4
      continue
    }
    if (op.kind === 'bullet') {
      const isOrdered = /^\d/.test(op.marker || '')
      for (let i = 0; i < op.lines.length; i += 1) {
        if (overflowAt()) { truncated = true; break }
        if (i === 0) {
          ctx.font = bodyBoldFont
          ctx.fillStyle = isOrdered ? '#374151' : '#1d4ed8'
          ctx.fillText(op.marker || '• ', PAD, y)
        }
        drawRichLine(ctx, op.lines[i], PAD + BULLET_INDENT, y, bodyFont, bodyBoldFont, TEXT, STRONG)
        y += BODY_LH
      }
      y += 8
      continue
    }
    // para | quote
    if (op.kind === 'quote') {
      const blockH = op.lines.length * BODY_LH
      ctx.fillStyle = '#93c5fd'
      ctx.fillRect(PAD, y - 24, 4, blockH - 4)
    }
    const qx = op.kind === 'quote' ? PAD + 14 : PAD
    for (const line of op.lines) {
      if (overflowAt()) { truncated = true; break }
      const cN = op.kind === 'quote' ? MUTED : TEXT
      drawRichLine(ctx, line, qx, y, bodyFont, bodyBoldFont, cN, STRONG)
      y += BODY_LH
    }
    y += 10
  }
  if (truncated) {
    ctx.font = footFont
    ctx.fillStyle = '#9ca3af'
    const note = '…（内容较长，已截断，仅展示前半部分）'
    if (y <= canvas.height - 60) ctx.fillText(note, PAD, y)
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
