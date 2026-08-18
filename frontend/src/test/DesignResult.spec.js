/**
 * DesignResult 测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - P2-6：持仓表「因子分」列头 + tooltip 口径（区别于技术信号）
 * - P2-8：degradation 顶部黄色提示条「数据源冷却」
 * - round21 #14：report_quality 部分生成/降级标签
 * - round22 E5：correlation_unchecked「关联度未校验」提示
 * - round25 R41-b：近替代品/未评估相关性告警渲染
 * - P2-V：现金仓位展示；P2-W：涨跌幅缺失显性化
 * - R3：降级态（coarse）权重 5% 档位/因子分强弱分档，exact 保持精确
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignResult from '../components/design/DesignResult.vue'

function makePlan(overrides = {}) {
  return {
    style: 'balanced',
    allocations: [
      { symbol: '510300', name: '沪深300ETF', layer: 'core', target_weight: 0.3, daily_change_pct: 0.5, factor_score: 0.75 },
      { symbol: '159338', name: '中证A500ETF', layer: 'core', target_weight: 0.2, daily_change_pct: null, factor_score: -0.17 },
      { symbol: 'CASH', name: '现金', layer: 'cash', target_weight: 0.25, factor_score: null },
    ],
    ...overrides,
  }
}

async function mountResult(plan, extraProps = {}) {
  const wrapper = mount(DesignResult, {
    props: { plans: [plan], ...extraProps },
    global: {
      mocks: { $t: (s) => s },
      stubs: { AppButton: { template: '<button><slot /></button>' } },
    },
  })
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult P2-6 因子分列', () => {
  it('持仓表含「因子分」列头 + tooltip 注明口径（负向：列头含「综合信号」 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan())
    const head = wrapper.find('.factor-col-head')
    expect(head.exists()).toBe(true)
    expect(head.text()).toBe('因子分')
    expect(head.attributes('title')).toContain('因子综合分')
    expect(head.attributes('title')).toContain('区别于技术信号')
    expect(head.text()).not.toContain('综合信号')
  })

  it('因子分连续值渲染（正负都显示，负向：缺失时不得渲染 0）', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const row510300 = rows.find(r => r.text().includes('510300'))
    expect(row510300.text()).toContain('+0.75')
    const row159338 = rows.find(r => r.text().includes('159338'))
    expect(row159338.text()).toContain('-0.17')
  })

  it('无 factor_score 的行显示「—」（不误显示 0.00）', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const cashRow = rows.find(r => r.text().includes('CASH'))
    expect(cashRow.text()).not.toContain('0.00')
    expect(cashRow.text()).toContain('—')
  })
})

describe('DesignResult P2-8 degradation 提示条', () => {
  it('degradation 存在时显示「数据源冷却」提示（负向：无提示 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'partial_data', pool_degraded: true, reason: '部分候选标的缺因子分' },
    })
    const banner = wrapper.find('.degradation-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('数据源冷却')
    expect(banner.text()).toContain('partial_data')
    expect(banner.text()).toContain('候选池降级')
  })

  it('无 degradation 时不渲染提示条（不误报）', async () => {
    const wrapper = await mountResult(makePlan())
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation 为 null（正常模式）时不渲染提示条', async () => {
    const wrapper = await mountResult(makePlan(), { degradation: null })
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation mode=normal（Z11 正常路径）时不渲染提示条（不误报）', async () => {
    // 后端正常数据管道也返回 degradation={mode:'normal',...}（Z11 设计）——
    // 负向：mode=normal 渲染「数据源冷却」→ FAIL
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'normal', reason: '正常数据管道', pool_degraded: false },
    })
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation pool_degraded=true 时即使 mode=normal 也渲染', async () => {
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'normal', pool_degraded: true, reason: '候选池冷却' },
    })
    expect(wrapper.find('.degradation-banner').exists()).toBe(true)
  })
})

describe('DesignResult round21 #14 report_quality 降级标签', () => {
  it('report_quality=partial 时显示「部分生成」标签（负向：静默展示为完整 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan(), { reportQuality: 'partial', designText: '# 报告' })
    const banner = wrapper.find('.quality-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('部分生成')
    expect(banner.classes()).toContain('quality-warn')
  })

  it('report_quality=fallback 时显示降级标签', async () => {
    const wrapper = await mountResult(makePlan(), { reportQuality: 'fallback', designText: '# 报告' })
    expect(wrapper.find('.quality-banner').exists()).toBe(true)
    expect(wrapper.find('.quality-banner').text()).toContain('降级为方案表格')
  })

  it('report_quality=full 时不渲染降级标签（不误报完整报告）', async () => {
    const wrapper = await mountResult(makePlan(), { reportQuality: 'full', designText: '# 报告' })
    expect(wrapper.find('.quality-banner').exists()).toBe(false)
  })

  it('report_quality=none 时不渲染降级标签', async () => {
    const wrapper = await mountResult(makePlan(), { reportQuality: 'none', designText: '# 报告' })
    expect(wrapper.find('.quality-banner').exists()).toBe(false)
  })
})

describe('DesignResult round22 E5 correlation_unchecked 提示', () => {
  it('plan.risk_metrics.correlation_unchecked=true 时显示「关联度未校验」提示（负向：静默跳过无标注 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan({
      risk_metrics: { correlation_unchecked: true },
    }))
    const note = wrapper.find('.corr-unchecked-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('关联度未校验')
    expect(note.text()).toContain('相关性约束已跳过')
  })

  it('correlation_unchecked 缺失时不渲染提示（不误报已校验）', async () => {
    const wrapper = await mountResult(makePlan({ risk_metrics: { correlation_warning: null } }))
    expect(wrapper.find('.corr-unchecked-note').exists()).toBe(false)
  })

  it('correlation_unchecked=false 时不渲染提示', async () => {
    const wrapper = await mountResult(makePlan({
      risk_metrics: { correlation_unchecked: false },
    }))
    expect(wrapper.find('.corr-unchecked-note').exists()).toBe(false)
  })
})

// round25 R41-b: 近替代品冗余告警——correlation_warnings 中 near_substitute/unevaluated
// 条目必须渲染（旧实现后端有计算、前端完全不渲染 → 死输出）。负向：不渲染 → FAIL。
describe('DesignResult round25 R41-b 近替代品告警', () => {
  it('near_substitute 条目渲染（含族/对信息）', async () => {
    const wrapper = await mountResult(makePlan({
      risk_metrics: {
        correlation_warnings: [
          { type: 'near_substitute', pair: ['588200', '588170'], family: '半导体',
            correlation: 0.12, note: '同主题近替代品（半导体族）：不同发行商同一板块，关联度约束不依赖 K 线相关系数' },
        ],
      },
    }))
    const note = wrapper.find('.corr-substitute-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('半导体')
    expect(note.text()).toContain('近替代品')
  })

  it('unevaluated 条目渲染（r 缺失标注待复算）', async () => {
    const wrapper = await mountResult(makePlan({
      risk_metrics: {
        correlation_warnings: [
          { type: 'unevaluated', pair: ['513120', '159570'], family: '医药生物',
            correlation: null, note: '同主题近替代品（医药生物族）但相关系数缺失（无价格序列/降级），冗余风险未量化——待交易时段复算' },
        ],
      },
    }))
    expect(wrapper.find('.corr-substitute-note').exists()).toBe(true)
    expect(wrapper.find('.corr-substitute-note').text()).toContain('医药生物')
  })

  it('无 correlation_warnings → 不渲染告警条（不误报）', async () => {
    const wrapper = await mountResult(makePlan())
    expect(wrapper.find('.corr-substitute-note').exists()).toBe(false)
  })

  it('concentration 类警告不渲染（仅 near_substitute/unevaluated）', async () => {
    const wrapper = await mountResult(makePlan({
      risk_metrics: {
        correlation_warnings: [
          { type: 'concentration', symbols: ['a', 'b'], avg_correlation: 0.85 },
        ],
      },
    }))
    expect(wrapper.find('.corr-substitute-note').exists()).toBe(false)
  })
})

// ── 来源: DesignResult.p2vw.spec.js（P2-V 现金仓位 + P2-W 涨跌幅缺失显性化）──

function makePlanP2VW(overrides = {}) {
  return {
    style: 'balanced',
    allocations: [
      { symbol: '510300', name: '沪深300ETF', layer: 'core', target_weight: 0.3, daily_change_pct: 0.5 },
      { symbol: '159338', name: '中证A500ETF', layer: 'core', target_weight: 0.2, daily_change_pct: null },
      { symbol: 'CASH', name: '现金', layer: 'cash', target_weight: 0.25 },
    ],
    ...overrides,
  }
}

async function mountResultP2VW(plan) {
  const wrapper = mount(DesignResult, {
    props: { plans: [plan] },
    global: {
      mocks: { $t: (s) => s },
      stubs: { AppButton: { template: '<button><slot /></button>' } },
    },
  })
  // plan-detail 需 expandedPlan === style 才渲染 → 点击卡片展开 + 等渲染
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult P2-V 现金仓位', () => {
  it('header 显示「现金 25%」', async () => {
    const wrapper = await mountResultP2VW(makePlanP2VW())
    const stats = wrapper.find('.plan-stats').text()
    expect(stats).toContain('现金 25%')
  })

  it('ETF 计数排除 CASH（负向：CASH 计入时计数错误）', async () => {
    const wrapper = await mountResultP2VW(makePlanP2VW())
    const stats = wrapper.find('.plan-stats').text()
    expect(stats).toContain('2 只 ETF')
    expect(stats).not.toContain('3 只 ETF')
  })

  it('无 CASH 时不显示现金项', async () => {
    const plan = makePlanP2VW({ allocations: makePlanP2VW().allocations.filter(a => a.symbol !== 'CASH') })
    const wrapper = await mountResultP2VW(plan)
    expect(wrapper.find('.plan-stats').text()).not.toContain('现金')
  })
})

describe('DesignResult P2-W 涨跌幅缺失显性化', () => {
  it('dcp=null 渲染「数据源不可用」（负向：不得渲染「—」或「0%」）', async () => {
    const wrapper = await mountResultP2VW(makePlanP2VW())
    const text = wrapper.text()
    expect(text).toContain('数据源不可用')
    const rows = wrapper.findAll('tbody tr')
    const row159338 = rows.find(r => r.text().includes('159338'))
    expect(row159338.text()).toContain('数据源不可用')
    expect(row159338.text()).not.toContain('0.00%')
  })

  it('CASH 行不显示「数据源不可用」（现金无涨跌幅语义）', async () => {
    const wrapper = await mountResultP2VW(makePlanP2VW())
    const rows = wrapper.findAll('tbody tr')
    const cashRow = rows.find(r => r.text().includes('CASH'))
    expect(cashRow.text()).not.toContain('数据源不可用')
  })

  it('dcp 有值时显示红涨绿跌 class', async () => {
    const wrapper = await mountResultP2VW(makePlanP2VW())
    const rows = wrapper.findAll('tbody tr')
    const row510300 = rows.find(r => r.text().includes('510300'))
    expect(row510300.text()).toContain('+0.50%')
    expect(row510300.find('.text-up').exists()).toBe(true)
  })
})

// ── 来源: DesignResult.r3precision.spec.js（R3 降级态精度治理）──

function makePlanR3() {
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

async function mountResultR3(dataPrecision) {
  const wrapper = mount(DesignResult, {
    props: { plans: [makePlanR3()], dataPrecision },
    global: { stubs: { AppButton: { template: '<button><slot /></button>' } } },
  })
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult R3 降级态精度治理', () => {
  it('coarse 态显示红字缺失百分比横幅', async () => {
    const wrapper = await mountResultR3(COARSE)
    const banner = wrapper.find('.precision-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('因子数据缺失 100%')
  })

  it('coarse 态权重为 5% 档位，不出现精确 1% 值（核心验收）', async () => {
    const wrapper = await mountResultR3(COARSE)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('≈20%')
    expect(row.text()).not.toContain('21.0%')
  })

  it('coarse 态小权重不被抹成 0%（5.2% → ≈5%）', async () => {
    const wrapper = await mountResultR3(COARSE)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('518880'))
    expect(row.text()).toContain('≈5%')
    expect(row.text()).not.toContain('≈0%')
  })

  it('coarse 态因子分为强弱分档，不出现两位小数', async () => {
    const wrapper = await mountResultR3(COARSE)
    const rows = wrapper.findAll('tbody tr')
    const weak = rows.find(r => r.text().includes('510300'))
    const strong = rows.find(r => r.text().includes('518880'))
    expect(weak.text()).toContain('偏弱')
    expect(weak.text()).not.toContain('-0.96')
    expect(strong.text()).toContain('偏强')
    expect(strong.text()).not.toContain('0.72')
  })

  it('exact 态保持精确权重与因子分（负向：不得误报降级）', async () => {
    const wrapper = await mountResultR3(EXACT)
    expect(wrapper.find('.precision-banner').exists()).toBe(false)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('21.0%')
    expect(row.text()).toContain('-0.96')
    expect(row.text()).not.toContain('≈')
  })

  it('dataPrecision 缺失（历史设计）按 exact 渲染', async () => {
    const wrapper = await mountResultR3(null)
    expect(wrapper.find('.precision-banner').exists()).toBe(false)
    const row = wrapper.findAll('tbody tr').find(r => r.text().includes('510300'))
    expect(row.text()).toContain('21.0%')
    expect(row.text()).toContain('-0.96')
  })
})
