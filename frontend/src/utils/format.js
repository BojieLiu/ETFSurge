// round11 P1-6: 统一格式化工具——从 AllocationTable/PnLDetailTable/SummaryCards/
// PortfolioManager/SectorHeatMap/TechnicalAnalysisModal/WatchlistPanel/AnalysisView
// 抽取的重复实现归拢为单一模块。

/**
 * 千分位 + 固定两位小数（zh-CN 语义）。带 try/catch 回退（浏览器差异防护）。
 */
export function formatNum(n, digits = 2) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  } catch {
    return v.toFixed(digits).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

/** 涨跌幅格式化：非数字显示 '—'，否则带符号两位小数；isAmount 时不带 %。 */
export function formatChange(pct, isAmount = false) {
  if (pct == null || Number.isNaN(Number(pct))) return '—'
  const v = Number(pct)
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}${isAmount ? '' : '%'}`
}

/** 货币/成交额缩写：亿/万（>=1e8 → x.xx 亿，>=1e4 → x.xx 万）。 */
export function formatAmount(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)} 万`
  return formatNum(n, 0)
}

/** 带 +/- 符号的百分比（如 +1.23% / -0.5%）。 */
export function signedPct(pct, digits = 2) {
  if (pct == null || Number.isNaN(Number(pct))) return '—'
  const v = Number(pct)
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
}

/** 补零（时间/日期字段统一 pad(2)）。 */
export function pad(n, width = 2) {
  return String(n).padStart(width, '0')
}

/** 价格格式化：null → '—'，否则两位小数。 */
export function formatPrice(v) {
  return v != null ? Number(v).toFixed(2) : '—'
}