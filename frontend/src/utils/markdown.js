import { marked } from 'marked'

// Configure marked for safety and consistency
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
})

/**
 * Pure function: render Markdown text to HTML
 * Uses the `marked` library for full GFM support (tables, fenced code blocks, etc.)
 * @param {string} md - Markdown text
 * @returns {string} rendered HTML
 */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
}

export function renderMarkdown(md) {
  if (!md) return ''
  try {
    return marked.parse(md)
  } catch (e) {
    console.warn('[markdown] marked parse failed, falling back to raw text:', e)
    return `<pre>${escapeHtml(md)}</pre>`
  }
}
