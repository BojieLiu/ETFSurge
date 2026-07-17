/**
 * UTC ISO datetime string → 北京时间 (Asia/Shanghai) 显示
 * @param {string|null|undefined} utcStr - ISO 8601 UTC datetime string
 * @returns {string} Formatted date string in Beijing time, or empty string
 */
export function formatDate(utcStr) {
  if (!utcStr) return ''
  try {
    // 确保字符串有时区后缀，否则 JS 会当作本地时间而非 UTC
    // 匹配末尾的 Z 或 ±HH:MM 格式的时区偏移
    const hasTimezone = /[+-]\d{2}:\d{2}$/.test(utcStr) || utcStr.endsWith('Z')
    const normalized = hasTimezone ? utcStr : utcStr + 'Z'
    const d = new Date(normalized)
    // Invalid date check
    if (Number.isNaN(d.getTime())) return utcStr
    return d.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return utcStr
  }
}

/**
 * UTC ISO datetime string → formatted date only (YYYY-MM-DD)
 * @param {string|null|undefined} utcStr
 * @returns {string}
 */
export function formatDateOnly(utcStr) {
  if (!utcStr) return ''
  try {
    const hasTimezone = /[+-]\d{2}:\d{2}$/.test(utcStr) || utcStr.endsWith('Z')
    const normalized = hasTimezone ? utcStr : utcStr + 'Z'
    const d = new Date(normalized)
    if (Number.isNaN(d.getTime())) return utcStr
    return d.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour12: false,
    }).replace(/\//g, '-')
  } catch {
    return utcStr
  }
}
