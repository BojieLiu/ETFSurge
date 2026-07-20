/**
 * Pure function: render Markdown text to HTML
 * @param {string} md - Markdown text
 * @returns {string} rendered HTML
 */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
}

export function renderMarkdown(md) {
  if (!md) return ''
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  let html = ''
  let inUl = false, inOl = false
  const closeLists = () => {
    if (inUl) { html += '</ul>'; inUl = false }
    if (inOl) { html += '</ol>'; inOl = false }
  }
  const inline = (t) => escapeHtml(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) { closeLists(); continue }
    let m
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      closeLists()
      const lvl = m[1].length
      const htxt = m[2]
      const riskCls = /风险/.test(htxt) ? ' md-h--risk' : ''
      html += `<h${lvl} class="md-h md-h${lvl}${riskCls}">${inline(htxt)}</h${lvl}>`
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      if (!inUl) { closeLists(); html += '<ul class="md-ul">'; inUl = true }
      html += `<li>${inline(m[1])}</li>`
    } else if ((m = line.match(/^\d+\.\s+(.*)$/))) {
      if (!inOl) { closeLists(); html += '<ol class="md-ol">'; inOl = true }
      html += `<li>${inline(m[1])}</li>`
    } else if (/^---+$/.test(line.trim())) {
      closeLists()
      html += '<hr class="md-hr">'
    } else {
      closeLists()
      html += `<p class="md-p">${inline(line)}</p>`
    }
  }
  closeLists()
  return html
}
