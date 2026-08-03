/**
 * R5-2-11: 场外基金技术分析目标解析——tracked_index 为场内 ETF 代码时
 * 查 ETF 自身 K 线（assetType='A'），仅真实指数代码才用 'index'。
 *
 * 背景：场外联接基金 tracked_index 存的是场内 ETF 代码（019671→513120、
 * 021458→159545、022449→159338）→ fetch_index_history('513120') 用 ETF 代码
 * 查指数：多数返回空（"暂无数据"），个别碰巧 akshare 容错返回 ETF 数据（不可靠）。
 */
// 场内 ETF 代码前缀（与后端 _is_etf_code 对齐）
const _ETF_PREFIXES = ['51', '52', '15', '16', '56', '58', '59']

function _isEtfCode(code) {
  return _ETF_PREFIXES.some((p) => String(code).startsWith(p))
}

// 真实指数代码：000xxx/399xxx（A 股指数）、HSI/HSTECH（港股）、^XXX（国际）等
function _isIndexCode(code) {
  const s = String(code)
  return (
    /^0\d{5}$/.test(s) ||
    /^399\d{3}$/.test(s) ||
    /^HSI$/i.test(s) ||
    /^HSTECH$/i.test(s) ||
    /^\^/.test(s) ||
    /^\d{5}\.HK$/i.test(s)
  )
}

/**
 * 解析技术分析的目标标的。
 * @param {Object} etf 标的（含 symbol / tracked_index）
 * @returns {{ sym: string, assetType: string }}
 *   - tracked_index 为场内 ETF 代码 → { sym: tracked_index, assetType: 'A' }
 *   - tracked_index 为真实指数代码 → { sym: tracked_index, assetType: 'index' }
 *   - 无 tracked_index → { sym: symbol, assetType: 'A' }（场内 ETF 原路径）
 */
export function resolveTaTarget(etf) {
  const tidx = etf && etf.tracked_index
  if (tidx) {
    if (_isEtfCode(tidx)) return { sym: tidx, assetType: 'A' }
    if (_isIndexCode(tidx)) return { sym: tidx, assetType: 'index' }
    // 未知形态：默认按指数查（旧行为，向前兼容）
    return { sym: tidx, assetType: 'index' }
  }
  return { sym: etf && etf.symbol, assetType: 'A' }
}

export { _isEtfCode, _isIndexCode }
