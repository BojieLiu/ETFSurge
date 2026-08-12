import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SectorHeatMap from '../components/market/SectorHeatMap.vue'
import TechnicalAnalysisModal from '../components/market/TechnicalAnalysisModal.vue'

// O20: ECharts 在 jsdom 下无 canvas → stub VChart 为普通组件（可读 option prop）
vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    template: '<div data-testid="vchart"><slot /></div>',
    props: { option: Object, autoresize: Boolean },
  },
}))
vi.mock('echarts/core', () => ({ use: vi.fn() }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('echarts/charts', () => ({ CandlestickChart: {}, BarChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  TitleComponent: {}, TooltipComponent: {}, GridComponent: {}, LegendComponent: {}, DataZoomComponent: {},
}))

vi.mock('../api', () => ({
  marketApi: {
    getHotPlates: vi.fn(),
    getSectorHeat: vi.fn(),
    getStockHotRank: vi.fn(),
    indicators: vi.fn(),
    signal: vi.fn(),
    // O28②: 资金流端点（技术分析弹窗 load 并行调用）
    fundFlow: vi.fn().mockResolvedValue({ data: { available: false, main_net_inflow: null } }),
    chart: vi.fn().mockResolvedValue({ data: { closes: [] } }),
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

  // ── O19 (round8 §7 §5.1D): change_pct=null 不崩溃、卡片正常渲染 ──────────
  it('O19: sector heat with change_pct=null renders without TypeError', async () => {
    // 财联社板块热度无涨跌幅字段 → change_pct 恒 null；旧 `!== undefined` 守卫
    // 不挡 null → null.toFixed 抛 TypeError → data-row 渲染中断 → 卡片消失。
    marketApi.getSectorHeat.mockResolvedValue({
      data: {
        items: [{
          rank: 1, name: '半导体', heat_index: 13501.4, rank_change: 5,
          is_new: 0, change_pct: null,
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
    expect(wrapper.find('.data-row').exists()).toBe(true)
    // 无涨跌幅渲染，但不抛错、卡片保留
    expect(wrapper.find('.row-change').exists()).toBe(false)
    expect(wrapper.text()).toContain('热度')
  })

  it('O19: stock row with change_pct=null renders without TypeError', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{ name: '海光信息', symbol: '688825', change_pct: null, price: 108.5 }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.data-row').exists()).toBe(true)
    expect(wrapper.text()).toContain('海光信息')
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
    // P0-18: heat 行双按钮（技术在前），AI 按钮是 [1]
    const aiBtn = wrapper.findAll('.row-action')[1]
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
    await flushPromises()
    const techBtn = wrapper.findAll('.row-action')[0]
    await techBtn.trigger('click')
    expect(wrapper.findComponent(TechnicalAnalysisModal).exists()).toBe(true)
    expect(marketApi.indicators).toHaveBeenCalledWith('688825', 'A')
    expect(marketApi.signal).toHaveBeenCalledWith('688825', 'A')
  })

  // ── O20 (round8 §7 §5.1E): 弹窗 K 线图渲染（数据已拉、此前未画图）─────
  it('O20: technical modal renders kline chart from chart payload', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{ name: '海光信息', symbol: '688825', change_pct: 5.2 }],
    })
    marketApi.indicators.mockResolvedValue({ data: { rsi: 43.4 } })
    marketApi.signal.mockResolvedValue({ data: { signal: 'hold' } })
    marketApi.chart.mockResolvedValue({
      data: {
        dates: ['2026-08-01', '2026-08-04', '2026-08-05'],
        opens: [10, 10.1, 10.2], closes: [10.1, 10.2, 10.3],
        highs: [10.2, 10.3, 10.4], lows: [9.9, 10.0, 10.1],
        volumes: [100, 120, 140], ma5: [10, 10.1, 10.2], ma10: [], ma20: [],
      },
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await flushPromises()
    await wrapper.findAll('.row-action')[0].trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const modal = wrapper.findComponent(TechnicalAnalysisModal)
    expect(modal.vm.klineOption).toBeTruthy()
    expect(modal.vm.klineOption.series || []).toBeTruthy()
    // candlestick 主序列存在 + 量能副图
    const types = modal.vm.klineOption.series.map((s) => s.type)
    expect(types).toContain('candlestick')
    expect(types).toContain('bar')
    // 今日涨跌与 K 线一致（close[-1] vs close[-2]）
    expect(modal.text()).toContain('+0.98%')
    expect(modal.find('.ta-kline').exists()).toBe(true)
  })

  it('R4-25: 技术信号文本随响应动态渲染（非静态空值）', async () => {
    marketApi.getStockHotRank.mockResolvedValue({
      data: [{ name: '海光信息', symbol: '688825', change_pct: 5.2 }],
    })
    marketApi.indicators.mockResolvedValue({ data: { rsi: 56.75, ma5: 4.2, ma20: 4.14 } })
    marketApi.signal.mockResolvedValue({
      data: { signal: 'buy', score: 1.5, reasons: ['MACD偏多', 'MA5>MA20 多头排列'] },
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[2].trigger('click')
    await flushPromises()
    await wrapper.findAll('.row-action')[0].trigger('click')
    await wrapper.vm.$nextTick()
    const modal = wrapper.findComponent(TechnicalAnalysisModal)
    expect(modal.find('.ta-signal-value').text()).toContain('买入')
    expect(modal.find('.ta-signal-score').text()).toContain('1.5')
    expect(modal.text()).toContain('MACD偏多')
    expect(modal.text()).toContain('多头排列')
  })

  it('F16: marketTab=HK 时请求带 market=HK（热点不再固定 A 股）', async () => {
    marketApi.getHotPlates.mockResolvedValue({
      data: [{ name: '专业服务', change_pct: 0.3, market: 'HK' }],
    })
    const wrapper = mount(SectorHeatMap, { props: { marketTab: 'HK' } })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(marketApi.getHotPlates).toHaveBeenCalledWith(15, 'HK')
    expect(wrapper.text()).toContain('专业服务')
  })

  it('F16: marketTab=US 时请求带 market=US（后端返回空列表）', async () => {
    marketApi.getHotPlates.mockResolvedValue({ data: [] })
    const wrapper = mount(SectorHeatMap, { props: { marketTab: 'US' } })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(marketApi.getHotPlates).toHaveBeenCalledWith(15, 'US')
  })

  it('P0-18: heat 条目技术按钮点击 → 请求领涨股 K 线（非 undefined）', async () => {
    // sectors/heat 条目自身无 symbol，但带 lead_stocks[].symbol（EM 源）——旧实现
    // openTechnical 用 item.symbol||item.code=undefined → /market/chart/undefined 404
    marketApi.getSectorHeat.mockResolvedValue({
      data: [{
        rank: 1, name: '半导体', heat_index: 13501.4, rank_change: 5, is_new: 0,
        change_pct: 2.3,
        lead_stocks: [{ symbol: '688825', name: '海光信息', change_pct: 5.1 }],
      }],
    })
    marketApi.indicators.mockResolvedValue({ data: { rsi: 43.4 } })
    marketApi.signal.mockResolvedValue({ data: { signal: 'hold' } })
    marketApi.chart.mockResolvedValue({ data: { closes: [] } })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await flushPromises()
    const techBtn = wrapper.findAll('.row-action')[0]
    await techBtn.trigger('click')
    await flushPromises()
    // 负向：undefined symbol 不得发请求
    expect(marketApi.indicators).toHaveBeenCalledWith('688825', 'A')
    expect(marketApi.signal).toHaveBeenCalledWith('688825', 'A')
    expect(marketApi.indicators.mock.calls[0][0]).not.toBe('undefined')
  })

  it('P0-18: 无领涨股条目技术按钮禁用（不发 undefined 请求）', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: [{
        rank: 1, name: '无领涨板块', heat_index: 100, rank_change: 0, is_new: 0,
        change_pct: 0, lead_stocks: [],
      }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await flushPromises()
    const techBtn = wrapper.findAll('.row-action')[0]
    expect(techBtn.attributes('disabled')).toBeDefined()
    // 点击被禁用按钮不触发请求
    await techBtn.trigger('click')
    expect(marketApi.indicators).not.toHaveBeenCalled()
  })

  // ── P2-8 (round17): sectors/heat degraded 标记前端消费 ──────────────
  it('P2-8: heat 响应 degraded=true 显示冷却提示（负向：无提示 → FAIL）', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: { items: [{ rank: 1, name: '半导体', change_pct: 0 }], total: 1, degraded: true },
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await flushPromises()
    const banner = wrapper.find('.degraded-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('数据源冷却')
  })

  it('P2-8: degraded=false 不显示提示（不误报）', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: { items: [{ rank: 1, name: '半导体', change_pct: 2.3 }], total: 1, degraded: false },
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.degraded-banner').exists()).toBe(false)
  })

  it('P2-8: 数组响应（旧格式，无 degraded 字段）不显示提示', async () => {
    marketApi.getSectorHeat.mockResolvedValue({
      data: [{ rank: 1, name: '半导体', change_pct: 2.3 }],
    })
    const wrapper = mount(SectorHeatMap)
    const tabs = wrapper.findAll('.tab-btn')
    await tabs[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.degraded-banner').exists()).toBe(false)
  })
})
