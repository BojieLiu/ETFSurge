import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SectorHeatMap from '../components/market/SectorHeatMap.vue'
import TechnicalAnalysisModal from '../components/market/TechnicalAnalysisModal.vue'

vi.mock('../api', () => ({
  marketApi: {
    getHotPlates: vi.fn(),
    getSectorHeat: vi.fn(),
    getStockHotRank: vi.fn(),
    indicators: vi.fn(),
    signal: vi.fn(),
  },
}))

import { marketApi } from '../api'

describe('SectorHeatMap (F2-6/F2-7 §9.8)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders hot plates with normalized fields (name/reason/lead stocks)', async () => {
    marketApi.getHotPlates.mockResolvedValue({
      data: [{
        name: 'AI智能体', reason: '大模型催化', stock_count: 6,
        lead_stocks: [{ secu_name: '海光信息' }, { secu_name: '寒武纪' }],
      }],
    })
    const wrapper = mount(SectorHeatMap)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('AI智能体')
    expect(wrapper.text()).toContain('大模型催化')
    expect(wrapper.text()).toContain('海光信息')
    expect(wrapper.text()).toContain('寒武纪')
  })

  it('renders sector heat with heat_index and rank_change', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: [{
        rank: 1, name: '半导体', heat_index: 13501.4, rank_change: 5, is_new: 0,
      }],
    })
    const wrapper = mount(SectorHeatMap)
    // 切到 heat tab
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('半导体')
    expect(wrapper.text()).toContain('1.35万')
    expect(wrapper.text()).toContain('↑5')
  })

  it('renders sector heat with {items,total} contract shape (F6 R15)', async () => {
    // 真实后端返回 {items, total}（hot-plates 契约 v2.0）——旧代码 Array.isArray
    // 判定恒空 → 页面空白；F6 R14 双兼容后必须正常渲染
    marketApi.getSectorHeat.mockResolvedValue({
      data: {
        items: [{
          rank: 1, name: '半导体', heat_index: 13501.4, rank_change: 5, is_new: 0,
        }],
        total: 20,
      },
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('半导体')
    expect(wrapper.text()).toContain('1.35万')
  })

  it('renders stock row with price/sector/turnover/concept chips', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{
        name: '海光信息', symbol: '688825', change_pct: 5.2,
        price: 108.5, sector: '半导体', turnover: 123456789,
        concept_tags: ['国产替代', 'AI芯片', '信创'],
      }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const text = wrapper.text()
    expect(text).toContain('108.50')
    expect(text).toContain('半导体')
    expect(text).toContain('1.23亿')
    expect(text).toContain('国产替代')
    expect(text).toContain('AI芯片')
    expect(text).toContain('+5.20%')
  })

  it('emits analyze with symbol mode when AI clicked on stock row', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{ name: '海光信息', symbol: '688825', change_pct: 5.2 }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const aiBtns = wrapper.findAll('.row-action')
    await aiBtns[aiBtns.length - 1].trigger('click')
    const emitted = wrapper.emitted('analyze')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toMatchObject({ mode: 'symbol', query: '688825' })
  })

  it('emits analyze with sector mode when AI clicked on heat row', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: [{ rank: 1, name: 'AI智能体', heat_index: 13501.4, plate_code: 'cls82558' }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const aiBtn = wrapper.findAll('.row-action')[0]
    await aiBtn.trigger('click')
    const emitted = wrapper.emitted('analyze')
    expect(emitted[0][0]).toMatchObject({ mode: 'sector', query: 'cls82558', name: 'AI智能体' })
  })

  it('opens technical analysis modal and requests indicators/signal', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{ name: '海光信息', symbol: '688825', change_pct: 5.2 }],
    })
    marketApi.indicators.mockResolvedValue({ data: { rsi: 43.4, macd: { dif: 1, dea: 0.5 }, ma20: 100 } })
    marketApi.signal.mockResolvedValue({ data: { signal: 'buy', score: 2, reason: 'RSI 超卖' } })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const techBtn = wrapper.findAll('.row-action')[0]
    await techBtn.trigger('click')
    expect(wrapper.findComponent(TechnicalAnalysisModal).exists()).toBe(true)
    expect(marketApi.indicators).toHaveBeenCalledWith('688825', 'A')
    expect(marketApi.signal).toHaveBeenCalledWith('688825', 'A')
  })
})
