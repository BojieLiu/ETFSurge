/**
 * round24 R3：降级态不得呈现精确数字（契约 api-contracts/portfolio/design-precision.md）。
 *
 * 问题（round24 §2.1 实证）：design 570 `factor_data_quality.valid_rate=0.0%` +
 * 「方案仅供参考」横幅，但表格仍显示 21.0% 权重与 -0.96 因子分 —— 降级诚实了、
 * 数字没诚实，专业投资者无法分辨可信边界。
 *
 * - coarse：权重按 5% 档位（≈20%）、因子分按强弱分档（偏弱）、红字缺失百分比
 * - exact / 缺字段：保持精确呈现（负向断言，防误报降级）
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignResult from '../components/design/DesignResult.vue'

function makePlan() {
  return {
    style: 'balanced',
    allocations: [
      { symbol: '510300', name: '沪深300ETF', layer: 'core', target_weight: 0.21, daily_change_pct: 0.5, factor_score: -0.96 },
      { symbol: '518880', name: '黄金ETF', layer: 'defense', target_weight: 0.052, daily_change_pct: 1.2, factor_score: 0.72 },
      { symbol: 'CASH', name: '现金', layer: 'cash', target_weight: 0.1 },
    ],
  }
}

const COARSE = {
  mode: 'coarse',
  factor_valid_rate: 0.0,
  factor_missing_pct: 100.0,
  weight_display: 'coarse',
  weight_step_pct: 5.0,
  factor_score_display: 'bucket',
  note: '因子数据缺失 100%：权重按 5% 档位粗略呈现、因子分仅显示强弱分档，不代表精确配置',
}

const EXACT = {
  mode: 'exact',
  factor_valid_rate: 0.82,
  factor_missing_pct: 18.0,
  weight_display: 'exact',
  weight_step_pct: null,
  factor_score_display: 'exact',
  note: '因子数据完整性正常（valid 率 82%），权重与因子分为精确值',
}

async function mountResult(dataPrecision) {
  const wrapper = mount(DesignResult, {
    props: { plans: [makePlan()], dataPrecision },
    global: { stubs: { AppButton: { template: '<button><slot /></button>' } } },
  })
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult R3 降级态精度治理', () => {
  it('coarse 态显示红字缺失百分比横幅', async () => {
    const wrapper = await mountResult(COARSE)
    const banner = wrapper.find('.precision-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('因子数据缺失 100%')
  })

  it('coarse 态权重为 5% 档位，不出现精确 1% 值（核心验收）', async () => {
    const wrapper = await mountResult(COARSE)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('≈20%')
    expect(row.text()).not.toContain('21.0%')
  })

  it('coarse 态小权重不被抹成 0%（5.2% → ≈5%）', async () => {
    const wrapper = await mountResult(COARSE)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('518880'))
    expect(row.text()).toContain('≈5%')
    expect(row.text()).not.toContain('≈0%')
  })

  it('coarse 态因子分为强弱分档，不出现两位小数', async () => {
    const wrapper = await mountResult(COARSE)
    const rows = wrapper.findAll('tbody tr')
    const weak = rows.find(r => r.text().includes('510300'))
    const strong = rows.find(r => r.text().includes('518880'))
    expect(weak.text()).toContain('偏弱')
    expect(weak.text()).not.toContain('-0.96')
    expect(strong.text()).toContain('偏强')
    expect(strong.text()).not.toContain('0.72')
  })

  it('exact 态保持精确权重与因子分（负向：不得误报降级）', async () => {
    const wrapper = await mountResult(EXACT)
    expect(wrapper.find('.precision-banner').exists()).toBe(false)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('21.0%')
    expect(row.text()).toContain('-0.96')
    expect(row.text()).not.toContain('≈')
  })

  it('dataPrecision 缺失（历史设计）按 exact 渲染', async () => {
    const wrapper = await mountResult(null)
    expect(wrapper.find('.precision-banner').exists()).toBe(false)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('21.0%')
    expect(row.text()).toContain('-0.96')
  })
})
