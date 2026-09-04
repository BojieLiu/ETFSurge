// Maps a backend news item to display metadata used by the UI.
//
// Two orthogonal dimensions (round23 F22/F23):
//   - `level`    (1-5): importance/severity. Drives push + min-importance filter.
//   - `category` (string): polarity/type. Drives coloring.
//
// Coloring follows A-share convention (红涨绿跌):
//   positive (利好) → red (good/up), negative (利空) → green (bad/down),
//   major (重大/紧急) → deep red, risk (地缘/军事/制裁) → orange (warning, NOT 利好 red),
//   neutral (提醒) → blue, other → gray.

const CATEGORY_META = {
  major:    { color: '#c0392b', label: '重大', starLabel: '重大' },
  positive: { color: '#e64545', label: '利好', starLabel: '利好' },
  negative: { color: '#1aa260', label: '利空', starLabel: '利空' },
  risk:     { color: '#f59e0b', label: '风险', starLabel: '风险' },
  neutral:  { color: '#3b82f6', label: '提醒', starLabel: '提醒' },
  other:    { color: '#9ca3af', label: '其他', starLabel: '其他' },
}

// Legacy: level-only metadata (kept for importance stars/label fallback).
export function mapNewsLevel(level) {
  const lvl = Number(level) || 0
  if (lvl >= 4) return { color: 'red', stars: '★★★★', label: '重要' }
  if (lvl === 3) return { color: 'orange', stars: '★★★', label: '关注' }
  if (lvl === 2) return { color: 'blue', stars: '★★', label: '一般' }
  return { color: 'gray', stars: '★', label: '普通' }
}

// F22: color + label by polarity category (falls back to level-based when absent).
export function mapNewsCategory(category, level) {
  const meta = CATEGORY_META[category] || mapNewsLevel(level)
  return meta
}

// An item is "important" when its importance level is 4 or higher.
// F22 fix: 利空/风险 with level>=4 now push (previously only level>=4 利好 pushed
// because level also encoded polarity). Filter/push is purely importance-driven.
export function isImportant(level) {
  return (Number(level) || 0) >= 4
}

// Map category → CSS class name (border-left color) and hex (inline color).
const CATEGORY_CLASS = {
  major: 'red',
  positive: 'red',
  negative: 'green',
  risk: 'orange',
  neutral: 'blue',
  other: 'gray',
}

// F22: hex follows A-share 红涨绿跌 — 利好红(好)、利空绿(坏)、重大深红、风险橙(警告非利好)、提醒蓝、其他灰。
export function categoryColor(category, level) {
  const meta = CATEGORY_META[category]
  if (meta) return meta.color
  return LEVEL_COLORS_FALLBACK[mapNewsLevel(level).color] || '#9ca3af'
}

// R178 (round52 §9.2 方案B-1): 重要等级星级——新星编码 level（重要度，1-5），
// 与 R83 移除的旧星区分：旧星编码 stars（新鲜度，与相对时间重复）。语义不重复。
// 全量显示（other 类也显示——用户诉求「每条都有地方体现」）。
export function mapLevelStars(level) {
  const n = Math.min(5, Math.max(1, Math.round(Number(level) || 1)))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

export function categoryColorClass(category, level) {
  if (CATEGORY_CLASS[category]) return CATEGORY_CLASS[category]
  const lv = mapNewsLevel(level).color
  return lv === 'orange' ? 'orange' : (lv === 'blue' ? 'blue' : (lv === 'red' ? 'red' : 'gray'))
}

const LEVEL_COLORS_FALLBACK = {
  red: '#e5484d',
  orange: '#f5901e',
  blue: '#3b82f6',
  gray: '#8a8f98',
}
