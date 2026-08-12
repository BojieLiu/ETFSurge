/**
 * P0-14 (round16 3.15 R2): 「跟踪指数」列统一为真实指数名。
 *
 * 验收:
 * ① 场内持仓显示真实指数名（tracked_index 后端回填）→ 不显示 '—'；
 * ② 场外持仓经 tracked_index（场内 ETF 代码）反查显示对应指数名（022449→159338→"中证A500"）；
 * ③ 场外反查失败时显示「联接：场内代码」兜底（不伪造）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('./ui/AppCard.vue', () => ({ default: { template: '<div><slot /><slot name="header-action" /></div>' } }))

import PnLDetailTable from '../components/dashboard/PnLDetailTable.vue'

const items = [
  // 场内：tracked_index 已回填真实指数名
  { symbol: '510300', name: '沪深300ETF', short_name: '沪深300', portfolio_type: 'on_exchange', tracked_index: '沪深300', change_pct: 1.0, target_amount: 100000, daily_pnl: 100 },
  { symbol: '159338', name: '中证A500ETF', short_name: '中证A500', portfolio_type: 'on_exchange', tracked_index: '中证A500', change_pct: 0.5, target_amount: 100000, daily_pnl: 50 },
  // 场外：tracked_index 为场内 ETF 代码
  { symbol: '022449', name: '华泰中证A500ETF联接C', short_name: '联接C', portfolio_type: 'off_exchange', tracked_index: '159338', change_pct: 0.5, target_amount: 100000, daily_pnl: 50 },
]

describe('PnLDetailTable — P0-14 跟踪指数列', () => {
  it('场内显示真实指数名，场外经场内反查显示对应指数名', () => {
    const wrapper = mount(PnLDetailTable, {
      props: { items, activeTab: 'combined', pnlTotal: 0, pnlTotalAmount: 0, pnlWeightedChange: 0 },
    })
    const text = wrapper.text()
    // 场内 159338 显示真实指数名 '中证A500'（tracked_index 回填）
    // 且场外 022449→159338 反查成功，同样显示 '中证A500'（不显示 '联接：159338'）
    const a500Count = (text.match(/中证A500/g) || []).length
    expect(a500Count).toBeGreaterThanOrEqual(2)
    expect(text).not.toContain('联接：159338')
  })

  it('场外反查失败时显示「联接：场内代码」兜底', () => {
    const orphan = [{ symbol: '010000', name: '孤儿联接', short_name: '孤儿', portfolio_type: 'off_exchange', tracked_index: '999999', change_pct: 0, target_amount: 1, daily_pnl: 0 }]
    const wrapper = mount(PnLDetailTable, {
      props: { items: orphan, activeTab: 'off_exchange', pnlTotal: 0, pnlTotalAmount: 0, pnlWeightedChange: 0 },
    })
    const text = wrapper.text()
    expect(text).toContain('联接：999999')
  })
})
