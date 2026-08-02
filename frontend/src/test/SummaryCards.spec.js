/**
 * F18 R66/R67: SummaryCards 累计盈亏估算标注。
 * - R66: summary/by_type 含 estimated_ratio>0 → 显示"含估算成本 X%（按目标权重估算）"
 * - R67: has_cost_basis_data=False → "需输入成本"（全空 avg_cost）
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryCards from '../components/dashboard/SummaryCards.vue'

function mountCards(pnlHistory, pnlHistoryLoading = false) {
  return mount(SummaryCards, {
    props: {
      activeTab: 'combined',
      totalAll: 100000,
      pnlOn: 100,
      pnlOff: -50,
      pnlTotal: 50,
      pnlHistory,
      pnlHistoryLoading,
      loading: false,
    },
  })
}

// 后端返回结构: { summary: {...}, holdings: [...], daily_series: [...] }
const summaryWithEstimate = {
  summary: {
    has_cost_basis_data: true,
    total_cumulative_pnl: 7500,
    total_cumulative_pnl_pct: 33.33,
    estimated_ratio: 0.92,
    by_type: {
      on_exchange: { cumulative_pnl: 7500, cumulative_pnl_pct: 33.33, estimated_ratio: 0.92 },
      off_exchange: { cumulative_pnl: 0, cumulative_pnl_pct: 0, estimated_ratio: 0 },
    },
  },
  holdings: [],
  daily_series: [],
}

const summaryNoCost = {
  summary: {
    has_cost_basis_data: false,
    total_cumulative_pnl: 0,
    total_cumulative_pnl_pct: 0,
    estimated_ratio: 0,
    by_type: {
      on_exchange: { cumulative_pnl: 0, cumulative_pnl_pct: 0, estimated_ratio: 0 },
      off_exchange: { cumulative_pnl: 0, cumulative_pnl_pct: 0, estimated_ratio: 0 },
    },
  },
  holdings: [],
  daily_series: [],
}

describe('SummaryCards 累计盈亏估算标注 (R66/R67)', () => {
  it('R66: estimated_ratio > 0 → 显示"含估算成本"标注', () => {
    const wrapper = mountCards(summaryWithEstimate)
    const hints = wrapper.findAll('.estimate-hint')
    expect(hints.length).toBeGreaterThanOrEqual(2) // 场内 + 总览
    const totalHint = hints[hints.length - 1].text()
    expect(totalHint).toContain('含估算成本')
    expect(totalHint).toContain('92%')
    expect(totalHint).toContain('按目标权重估算')
  })

  it('R66: 显示估算后的累计盈亏金额（非 0）', () => {
    const wrapper = mountCards(summaryWithEstimate)
    expect(wrapper.text()).toContain('7,500.00')
  })

  it('R67: has_cost_basis_data=False → 需输入成本', () => {
    const wrapper = mountCards(summaryNoCost)
    expect(wrapper.text()).toContain('需输入成本')
    expect(wrapper.findAll('.estimate-hint').length).toBe(0)
  })

  it('R66: estimated_ratio=0 全真实 → 无估算标注', () => {
    const summaryReal = {
      summary: {
        has_cost_basis_data: true,
        total_cumulative_pnl: -1234.5,
        total_cumulative_pnl_pct: -5.0,
        estimated_ratio: 0,
        by_type: {
          on_exchange: { cumulative_pnl: -1234.5, cumulative_pnl_pct: -5.0, estimated_ratio: 0 },
          off_exchange: { cumulative_pnl: 0, cumulative_pnl_pct: 0, estimated_ratio: 0 },
        },
      },
      holdings: [],
      daily_series: [],
    }
    const wrapper = mountCards(summaryReal)
    expect(wrapper.findAll('.estimate-hint').length).toBe(0)
    // has_cost_basis_data 是 summary 级全局字段：全真实数据 → 各卡显示盈亏且无估算标注
    expect(wrapper.text()).toContain('1,234.50')
    expect(wrapper.text()).not.toContain('含估算成本')
  })
})
