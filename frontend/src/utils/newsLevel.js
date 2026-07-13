// Maps a backend news `level` (1-5) to display metadata used by the UI:
// - color: drives the title/badge font color
// - stars: ★ characters rendered as the star rating
// - label: short Chinese label for the importance
export function mapNewsLevel(level) {
  const lvl = Number(level) || 0
  if (lvl >= 4) return { color: 'red', stars: '★★★★', label: '重要' }
  if (lvl === 3) return { color: 'orange', stars: '★★★', label: '关注' }
  if (lvl === 2) return { color: 'blue', stars: '★★', label: '一般' }
  return { color: 'gray', stars: '★', label: '普通' }
}

// An item is "important" when its level is 4 or higher. Important items
// are pushed in real time and trigger a toast reminder on page entry.
export function isImportant(level) {
  return (Number(level) || 0) >= 4
}
