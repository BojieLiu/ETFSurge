import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'

const stopMock = vi.fn()
const startMock = vi.fn().mockResolvedValue({ fullText: 'ok' })

vi.mock('../composables/useLLMStream', () => ({
  useLLMStream: () => ({ start: startMock, stop: stopMock }),
}))

vi.mock('../utils/markdown', () => ({ renderMarkdown: (s) => s }))

const { searchApiMock } = vi.hoisted(() => ({ searchApiMock: vi.fn().mockResolvedValue({ data: [] }) }))
// R5-3-1: 不再 mock useMarketSearch——改用真实 composable，只 mock api 层（axios）。
// 断言模式：input 事件 → searchQuery 写回 → debounce → api.search 调用参数 全链路。

vi.mock('../api', () => ({
  marketApi: {
    indicesMeta: vi.fn().mockResolvedValue({ data: [
      { symbol: '000300', name: '沪深300', market: 'A' },
      { symbol: '000001', name: '上证指数', market: 'A' },
    ] }),
    search: searchApiMock,
  },
}))

import UnifiedAnalysis from '../components/market/UnifiedAnalysis.vue'

function mounted() {
  return mount(UnifiedAnalysis, {
    props: { marketTab: 'A' },
    global: {
      mocks: { $t: (s) => s },
    },
  })
}

describe('UnifiedAnalysis R40 (tab 切换重置)', () => {
  beforeEach(() => {
    stopMock.mockClear()
    startMock.mockClear()
    searchApiMock.mockClear()
    searchApiMock.mockResolvedValue({ data: [] })
  })

  it('switchMode 中止在途请求并重置全部状态', async () => {
    const wrapper = mounted()
    wrapper.vm.query = '510050'
    wrapper.vm.symbol = '510050'
    wrapper.vm.result = '已有分析结果'
    wrapper.vm.error = ''
    wrapper.vm.loading = true
    wrapper.vm.lastAnalyzed = '510050'

    wrapper.vm.switchMode('sector')
    await nextTick()

    expect(stopMock).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.activeMode).toBe('sector')
    expect(wrapper.vm.query).toBe('')
    expect(wrapper.vm.symbol).toBe('')
    expect(wrapper.vm.result).toBe('')
    expect(wrapper.vm.error).toBe('')
    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.lastAnalyzed).toBe('')
  })

  it('点击当前 tab 不重置（stopStream 不调用）', async () => {
    const wrapper = mounted()
    wrapper.vm.query = '000001'
    wrapper.vm.switchMode('symbol') // 当前就是 symbol
    await nextTick()
    expect(stopMock).not.toHaveBeenCalled()
    expect(wrapper.vm.query).toBe('000001')
  })

  it('模板 tab 按钮触发 switchMode', async () => {
    const wrapper = mounted()
    const tabs = wrapper.findAll('.analysis-tab')
    expect(tabs.length).toBeGreaterThanOrEqual(3)
    await tabs[1].trigger('click') // sector
    await nextTick()
    expect(wrapper.vm.activeMode).toBe('sector')
    expect(stopMock).toHaveBeenCalled()
  })

  it('R42/R43: index 模式中文/代码解析真实名称与 symbol', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'index'
    // O30: sector/index 模式输入源 = activeSearch.searchQuery（三模式统一自动补全框）
    wrapper.vm.activeSearch.searchQuery.value = '000001'
    await wrapper.vm.doAnalyze()
    const body = startMock.mock.calls[0][1]
    expect(body.asset_type).toBe('index')
    // R42: 解析命中 → symbol 真实代码 + 真实名称（标题显示"名称 (代码)"）
    expect(body.symbol).toBe('000001')
    expect(body.name).toBe('上证指数')
  })

  it('R42/R43: index 模式未命中解析 → 代码直传 name 置空（后端 realtime 回填）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'index'
    wrapper.vm.activeSearch.searchQuery.value = '999999'
    await wrapper.vm.doAnalyze()
    const body = startMock.mock.calls[0][1]
    expect(body.asset_type).toBe('index')
    expect(body.symbol).toBe('999999')
    expect(body.name).toBe('')
  })

  it('F7 R19: symbol 模式中文名 → 搜索解析 symbol + name', async () => {
    searchApiMock.mockResolvedValueOnce({ data: [
      { symbol: '510300', name: '沪深300ETF', market: 'A' },
    ] })
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '沪深300ETF'
    await wrapper.vm.doAnalyze()
    const body = startMock.mock.calls[0][1]
    expect(searchApiMock).toHaveBeenCalledWith('沪深300ETF', { include_stocks: true })
    expect(body.symbol).toBe('510300')
    expect(body.name).toBe('沪深300ETF')
  })

  it('F7 R18: symbol 模式输入显示自动补全下拉', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchResults.value = [
      { symbol: '510050', name: '上证50ETF', market: 'A' },
    ]
    wrapper.vm.search.showDropdown.value = true
    await nextTick()
    const opts = wrapper.findAll('.search-option')
    expect(opts.length).toBe(1)
    expect(wrapper.find('.search-dropdown').exists()).toBe(true)
  })

  it('R5: symbol 模式输入写回 searchQuery（旧 bug：只调 onSearchInput 不写回 → 补全永不触发）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    const input = wrapper.find('input.text-input')
    await input.setValue('5100')
    expect(wrapper.vm.search.searchQuery.value).toBe('5100')
  })

  it('R5: 非 symbol 模式输入写入对应 search 实例（O30: sector/index 也走自动补全）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'sector'
    const input = wrapper.find('input.text-input')
    await input.setValue('BK0477')
    // O30: sector 模式输入写入 sectorSearch.searchQuery（触发板块补全）
    expect(wrapper.vm.activeSearch.searchQuery.value).toBe('BK0477')
    // symbol 补全实例不被污染
    expect(wrapper.vm.search.searchQuery.value).toBe('')
  })

  it('O23: 补全选中后输入框显示「名称 (代码)」且 doAnalyze 解析混合串', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    const item = { symbol: '510050', name: '上证50ETF', market: 'A' }
    startMock.mockResolvedValue({ fullText: '## 报告' })
    wrapper.vm.pickSearchItem(item)
    // O23: 输入框显示「名称 (代码)」（旧断言固化 bug：只显示纯代码）
    expect(wrapper.vm.search.searchQuery.value).toBe('上证50ETF (510050)')
    expect(wrapper.vm.symbol).toBe('510050')
    // query 反映用户输入（混合串），doAnalyze 从混合串正确取 symbol
    expect(wrapper.vm.query).toBe('上证50ETF (510050)')
    // doAnalyze 对混合串正确取 symbol
    const body = startMock.mock.calls[0][1]
    expect(body.symbol).toBe('510050')
    expect(body.name).toBe('上证50ETF')
  })

  it('R5: 空输入点分析给出提示（旧实现静默无动作）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = ''
    wrapper.vm.doAnalyze()
    expect(wrapper.vm.error).toContain('请输入标的代码或名称')
  })

  it('R5: 切换 marketTab 清空旧市场的结果/输入（A→US 不残留 A 股分析）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.result = '## A股标的分析报告'
    wrapper.vm.query = '510050'
    wrapper.vm.symbol = '510050'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.search.searchResults.value = [{ symbol: '510050' }]
    wrapper.vm.search.showDropdown.value = true
    await wrapper.setProps({ marketTab: 'US' })
    await nextTick()
    expect(wrapper.vm.result).toBe('') // 旧报告清空
    expect(wrapper.vm.query).toBe('')
    expect(wrapper.vm.symbol).toBe('')
    expect(wrapper.vm.search.searchQuery.value).toBe('')
    expect(wrapper.vm.search.searchResults.value).toEqual([])
    expect(wrapper.vm.search.showDropdown.value).toBe(false)
  })
})

// ── F18 (round6 §16.6): Enter/mousedown 统一触发 + SSE 错误态 ─────────────
describe('UnifiedAnalysis F18 (交互一致性 + 错误态)', () => {
  beforeEach(() => {
    stopMock.mockClear()
    startMock.mockClear()
    searchApiMock.mockClear()
    searchApiMock.mockResolvedValue({ data: [] })
  })

  it('F18: 键盘 Enter（选中下拉项）统一触发 doAnalyze', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.search.searchResults.value = [
      { symbol: '510050', name: '上证50ETF', market: 'A' },
    ]
    wrapper.vm.search.showDropdown.value = true
    startMock.mockResolvedValue({ fullText: '## 报告' })

    // 模拟输入框 Enter → onEnterKeydown → 下拉 Enter 分支消费 → doAnalyze
    const input = wrapper.find('input.text-input')
    await input.trigger('keydown.enter')
    await nextTick()
    await nextTick()
    await nextTick()
    expect(startMock).toHaveBeenCalled()
  })

  it('F18: SSE 返回空 fullText → 显示错误态（非"已选择"静默）', async () => {
    startMock.mockResolvedValue({ fullText: '' })
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('分析失败')
    // 不落入"已选择"静默分支（result 空 + error 非空）
    expect(wrapper.vm.result).toBe('')
  })

  it('F18: "已选择"态有"点击分析"引导按钮', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.symbol = '510050'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.result = ''
    wrapper.vm.error = ''
    await nextTick()
    expect(wrapper.find('.result-area .btn-primary').exists()).toBe(true)
  })

  // ── O24 (round8 §7 §5.1K): SSE 空/异常 → 失败分类 + 重试入口 ──────────
  it('O24: SSE 空 → 失败态显示错误 + 重试按钮', async () => {
    startMock.mockResolvedValue({ fullText: '' })
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('分析失败')
    expect(wrapper.find('.btn-retry').exists()).toBe(true)
  })

  it('O24: 429 场景显示「请求过于频繁」分类文案（非笼统网络错误）', async () => {
    startMock.mockRejectedValue(new Error('429 Too Many Requests'))
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('请求过于频繁')
    expect(wrapper.vm.error).not.toContain('网络错误')
  })

  it('O24: timeout 场景显示「数据源无响应」分类文案', async () => {
    startMock.mockRejectedValue(new Error('[timeout] connection timed out'))
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('数据源无响应')
  })

  it('O24: DATA_UNAVAILABLE（sh688981 前缀失败）显示「数据源暂不可用」', async () => {
    startMock.mockRejectedValue(new Error('数据源暂不可用'))
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = 'sh688981'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('数据源暂不可用')
  })

  it('O24: 失败后点「重试」重新发起分析（同输入）', async () => {
    startMock.mockResolvedValueOnce({ fullText: '' }).mockResolvedValueOnce({ fullText: '## 报告' })
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    wrapper.vm.search.searchQuery.value = '510050'
    wrapper.vm.doAnalyze()
    await nextTick()
    await nextTick()
    expect(wrapper.vm.error).toContain('分析失败')
    await wrapper.find('.btn-retry').trigger('click')
    await nextTick()
    await nextTick()
    expect(startMock).toHaveBeenCalledTimes(2)
    expect(wrapper.vm.error).toBe('')
    expect(wrapper.vm.result).toBe('## 报告')
  })
})
