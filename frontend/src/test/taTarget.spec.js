/**
 * R5-2-11: resolveTaTarget 场外基金技术分析目标解析。
 *
 * - 场外 tracked_index 为场内 ETF 代码（513120/159545/159338）→ { sym, assetType: 'A' }
 * - tracked_index 为真实指数代码（000300/399001/HSI）→ { sym, assetType: 'index' }
 * - 无 tracked_index（场内 ETF）→ { sym: symbol, assetType: 'A' }
 */
import { describe, it, expect } from 'vitest'
import { resolveTaTarget, _isEtfCode, _isIndexCode } from '../utils/taTarget'

describe('resolveTaTarget (R5-2-11)', () => {
  it('场外标的 tracked_index 为场内 ETF 代码 → assetType=A 且 sym=tracked_index', () => {
    // 019671→513120、021458→159545、022449→159338（DB 实测映射）
    for (const [off, etfCode] of [['019671', '513120'], ['021458', '159545'], ['022449', '159338']]) {
      const r = resolveTaTarget({ symbol: off, tracked_index: etfCode })
      expect(r).toEqual({ sym: etfCode, assetType: 'A' })
    }
  })

  it('tracked_index 为真实指数代码 → assetType=index', () => {
    for (const idx of ['000300', '399001', '000905', 'HSI', '^GSPC']) {
      const r = resolveTaTarget({ symbol: '019671', tracked_index: idx })
      expect(r).toEqual({ sym: idx, assetType: 'index' })
    }
  })

  it('场内 ETF（tracked_index 缺失）→ 原路径 assetType=A 且 sym=symbol', () => {
    const r = resolveTaTarget({ symbol: '510300' })
    expect(r).toEqual({ sym: '510300', assetType: 'A' })
  })

  it('前缀判定：51/52/15/16/56/58/59 为场内 ETF 代码', () => {
    for (const c of ['513120', '159545', '159338', '560600', '588000', '512480', '516160']) {
      expect(_isEtfCode(c)).toBe(true)
    }
    expect(_isEtfCode('000300')).toBe(false)
    expect(_isEtfCode('399001')).toBe(false)
    expect(_isEtfCode('HSI')).toBe(false)
  })

  it('指数代码判定：000xxx/399xxx/HSI/HSTECH/^ 前缀', () => {
    for (const c of ['000300', '000905', '399001', 'HSI', 'HSTECH', '^GSPC']) {
      expect(_isIndexCode(c)).toBe(true)
    }
    expect(_isIndexCode('513120')).toBe(false)
    expect(_isIndexCode('159545')).toBe(false)
  })
})
