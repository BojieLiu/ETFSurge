/**
 * Chart color constants — single source of truth for ECharts color values.
 * Matches CSS variables --chart-1 through --chart-8 defined in theme.css.
 *
 * Usage:
 *   import { CHART_COLORS, chartColor, maColors, candleColors } from '../utils/chartColors'
 *   series.color = CHART_COLORS[0]
 *   series.lineStyle.color = chartColor('ma5')
 */

// Chart palette (matches theme.css --chart-1..--chart-8)
export const CHART_COLORS = [
  '#4f46e5', // brand-500  (--chart-1)
  '#22c55e', // success-500 (--chart-2)
  '#f59e0b', // warning-500 (--chart-3)
  '#ef4444', // danger-500  (--chart-4)
  '#8b5cf6', // purple     (--chart-5)
  '#06b6d4', // cyan       (--chart-6)
  '#f97316', // orange     (--chart-7)
  '#ec4899', // pink       (--chart-8)
]

// Named chart color map
const CHART_COLOR_MAP = {
  ma5: CHART_COLORS[2],   // #f59e0b
  ma10: CHART_COLORS[0],  // #4f46e5
  ma20: CHART_COLORS[4],  // #8b5cf6
  ma60: CHART_COLORS[1],  // #22c55e
  bollUpper: '#94a3b8',
  bollMiddle: '#1e293b',
  bollLower: '#94a3b8',
  macdDif: CHART_COLORS[0],   // #4f46e5
  macdDea: CHART_COLORS[2],   // #f59e0b
  kdjK: CHART_COLORS[0],      // #4f46e5
  kdjD: CHART_COLORS[2],      // #f59e0b
  kdjJ: CHART_COLORS[4],      // #8b5cf6
  rsi: CHART_COLORS[3],       // #ef4444
  splitLine: '#e2e8f0',
}

// Candle colors (red-up / green-down = Chinese convention)
export const CANDLE_UP = '#ef4444'    // red for up
export const CANDLE_DOWN = '#22c55e'  // green for down

/**
 * Resolve a named chart color
 * @param {string} name — key from CHART_COLOR_MAP
 * @returns {string} hex color
 */
export function chartColor(name) {
  return CHART_COLOR_MAP[name] || CHART_COLORS[0]
}

/**
 * Resolve chart palette color by index
 * @param {number} index — 0-based index into CHART_COLORS
 * @returns {string} hex color
 */
export function getChartColor(index) {
  return CHART_COLORS[index % CHART_COLORS.length]
}

/**
 * Get histogram bar color based on value sign
 * @param {number} value — MACD histogram value
 * @returns {string} hex color
 */
export function histogramColor(value) {
  return (value || 0) >= 0 ? CANDLE_UP : CANDLE_DOWN
}
