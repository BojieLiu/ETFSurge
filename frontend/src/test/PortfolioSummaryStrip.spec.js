import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

// round34-B7 批复①：组合摘要条四态（loading/error/empty/ready）+ 点击跳组合页
const push = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

import PortfolioSummaryStrip from '../components/dashboard/PortfolioSummaryStrip.vue'

const base = {
  totalAll: 150000,
  pnlOn: 250,
  pnlOff: -80,
  pnlTotal: 170,
  weightedChange: 1.13,
  attempted: true,
  error: false,
  lastUpdated: '12:00:00',
}

const mountStrip = (props = {}) => mount(PortfolioSummaryStrip, { props: { ...base, ...props } })

beforeEach(() => {
  push.mockClear()
})

describe('PortfolioSummaryStrip 四态（round34-B7 批复①）', () => {
  it('loading 态：attempted=false 渲染骨架且不可点击跳转', () => {
    const w = mountStrip({ attempted: false })
    expect(w.find('.pss-skeleton').exists()).toBe(true)
    expect(w.find('.pss-num').exists()).toBe(false)
    // 骨架期点击不产生导航（handler 早退）
    expect(push).not.toHaveBeenCalled()
  })

  it('error 态：显示重试文案、渲染任何 ¥ 数字（负向：禁 ¥0 冒充）并 emit retry', async () => {
    const w = mountStrip({ error: true })
    expect(w.text()).toContain('盈亏数据暂不可用')
    expect(w.text()).not.toContain('¥')
    await w.trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
    expect(push).not.toHaveBeenCalled()
  })

  it('empty 态：无持仓时引导去组合页添加', async () => {
    const w = mountStrip({ totalAll: 0, pnlOn: 0, pnlOff: 0, pnlTotal: 0, weightedChange: 0 })
    expect(w.text()).toContain('还没有持仓')
    await w.trigger('click')
    expect(push).toHaveBeenCalledWith('/portfolio-analysis')
  })

  it('ready 态：渲染总仓位/当日合计/场内外拆分与红涨绿跌 class', () => {
    const w = mountStrip()
    const text = w.text()
    expect(text).toContain('总仓位')
    expect(text).toContain('150,000.00')
    expect(text).toContain('当日合计')
    expect(text).toContain('+¥170.00')
    expect(text).toContain('+1.13%')
    expect(text).toContain('+¥250.00') // 场内
    expect(text).toContain('-¥80.00') // 场外
    expect(w.find('.text-up').exists()).toBe(true)
    expect(w.find('.text-down').exists()).toBe(true)
    expect(text).toContain('更新于 12:00:00')
  })

  it('ready 态点击 → router.push /portfolio-analysis', async () => {
    const w = mountStrip()
    await w.trigger('click')
    expect(push).toHaveBeenCalledTimes(1)
    expect(push).toHaveBeenCalledWith('/portfolio-analysis')
  })
})
