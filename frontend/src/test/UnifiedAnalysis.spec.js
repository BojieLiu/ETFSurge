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
// 用真实 ref 包装搜索状态——修改后才触发模板重渲染（与真实 useMarketSearch 行为一致）
const searchState = vi.hoisted(() => {
  const { ref } = require('vue')
  return {
    searchQuery: ref(''),
    searchResults: ref([]),
    showDropdown: ref(false),
    activeIndex: ref(-1),
    completionFull: ref(''),
    selectedSearchItem: ref(null),
    searchRef: ref(null),
  }
})

vi.mock('../composables/useMarketSearch', () => ({
  useMarketSearch: () => ({
    searchQuery: searchState.searchQuery,
    searchResults: searchState.searchResults,
    showDropdown: searchState.showDropdown,
    activeIndex: searchState.activeIndex,
    completionFull: searchState.completionFull,
    selectedSearchItem: searchState.selectedSearchItem,
    searchRef: searchState.searchRef,
    doSearch: vi.fn(),
    onSearchInput: vi.fn(),
    onSearchFocus: vi.fn(),
    onSearchBlur: vi.fn(),
    onSearchKeydown: vi.fn(),
    selectSearchItem: vi.fn(),
    clearSearchItem: vi.fn(),
  }),
}))

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
    searchState.searchQuery.value = ''
    searchState.searchResults.value = []
    searchState.showDropdown.value = false
    searchState.activeIndex.value = -1
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
    wrapper.vm.query = '000001'
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
    wrapper.vm.query = '999999'
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
    searchState.searchQuery.value = '沪深300ETF'
    await wrapper.vm.doAnalyze()
    const body = startMock.mock.calls[0][1]
    expect(searchApiMock).toHaveBeenCalledWith('沪深300ETF', { include_stocks: true })
    expect(body.symbol).toBe('510300')
    expect(body.name).toBe('沪深300ETF')
  })

  it('F7 R18: symbol 模式输入显示自动补全下拉', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'symbol'
    searchState.searchResults.value = [
      { symbol: '510050', name: '上证50ETF', market: 'A' },
    ]
    searchState.showDropdown.value = true
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
    expect(searchState.searchQuery.value).toBe('5100')
  })

  it('R5: 非 symbol 模式输入写入 query（不触发补全）', async () => {
    const wrapper = mounted()
    wrapper.vm.activeMode = 'sector'
    const input = wrapper.find('input.text-input')
    await input.setValue('BK0477')
    expect(wrapper.vm.query).toBe('BK0477')
    expect(searchState.searchQuery.value).toBe('') // 补全输入未被污染
  })
})
