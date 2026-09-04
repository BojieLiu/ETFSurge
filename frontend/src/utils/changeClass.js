export function changeClass(val) {
  // R175 (round52 §7.3 方案C): null/undefined = 行情暂不可用（estimate_source="unavailable"），
  // 返回空串走默认色——不得把不可用当作涨（红）或跌（绿）渲染。
  if (val == null || Number.isNaN(Number(val))) return ''
  return val >= 0 ? 'text-up' : 'text-down'
}
