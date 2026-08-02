/**
 * F18 R66/R67: SummaryCards 累计盈亏估算标注。
 * - R66: summary/by_type 含 estimated_ratio>0 → 显示"估算 X%"（tooltip 含完整说明）
 * - R67: has_cost_basis_data=False → "需输入成本"（全空 avg_cost）
 * R5 UI 优化：正负号（+/-）、逻辑分组标签（当日盈亏/累计盈亏）、更新时间指示器。
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

describe('SummaryCards UI 优化 (R5)', () => {
  it('正负号：正数带 +，负数带 -，0 不带符号', () => {
    const wrapper = mountCards(null)
    const text = wrapper.text()
    // totalAll=100000（正，无符号）、pnlOn=100（+）、pnlOff=-50（-）
    expect(text).toContain('¥100,000.00')
    expect(text).toContain('+100.00')
    expect(text).toContain('-50.00')
    // 累计无 pnlHistory → 不渲染累计卡，也不含任何裸负号格式
  })

  it('累计盈亏正负号与百分比符号', () => {
    const wrapper = mountCards({
      summary: {
        has_cost_basis_data: true,
        total_cumulative_pnl: -1234.5,
        total_cumulative_pnl_pct: -5.0,
        estimated_ratio: 0,
        by_type: {
          on_exchange: { cumulative_pnl: 7500, cumulative_pnl_pct: 33.33, estimated_ratio: 0 },
          off_exchange: { cumulative_pnl: -50.5, cumulative_pnl_pct: -1.2, estimated_ratio: 0 },
        },
      },
      holdings: [],
      daily_series: [],
    })
    const text = wrapper.text()
    expect(text).toContain('+7,500.00')
    expect(text).toContain('(+33.33%)')
    expect(text).toContain('-50.50')
    expect(text).toContain('(-1.20%)')
    expect(text).toContain('-1,234.50')
  })

  it('逻辑分组标签：当日盈亏 / 累计盈亏', () => {
    const wrapper = mountCards(null)
    const labels = wrapper.findAll('.summary-group-label')
    expect(labels.length).toBe(2)
    expect(labels[0].text()).toBe('当日盈亏')
    expect(labels[1].text()).toBe('累计盈亏')
  })

  it('总仓位卡独占一行（summary-card--total）', () => {
    const wrapper = mountCards(null)
    expect(wrapper.find('.summary-card--total').exists()).toBe(true)
  })

  it('更新时间指示器：常驻占位（零 CLS），有值显示时间', () => {
    const wrapper = mountCards(null)
    const el = wrapper.find('.summary-updated')
    expect(el.exists()).toBe(true)
    expect(el.text()).toContain('更新于 --:--:--')
    const w2 = mount(SummaryCards, {
      props: {
        activeTab: 'combined',
        totalAll: 100000,
        pnlOn: 100,
        pnlOff: -50,
        pnlTotal: 50,
        loading: false,
        lastUpdated: '10:30:00',
      },
    })
    expect(w2.find('.summary-updated').text()).toContain('更新于 10:30:00')
  })
})
