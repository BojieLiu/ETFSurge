import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api', () => ({
  marketApi: {
    search: vi.fn(),
  },
}))

import { marketApi } from '../api'
import { useMarketSearch } from '../composables/useMarketSearch'

describe('useMarketSearch', () => {
  let composable

  beforeEach(() => {
    vi.clearAllMocks()
    composable = useMarketSearch()
  })

  it('returns initial state correctly', () => {
    expect(composable.searchQuery.value).toBe('')
    expect(composable.searchResults.value).toEqual([])
    expect(composable.showDropdown.value).toBe(false)
    expect(composable.activeIndex.value).toBe(-1)
    expect(composable.completionFull.value).toBe('')
    expect(composable.selectedSearchItem.value).toBeNull()
  })

  it('clears results when search input is empty', () => {
    composable.searchQuery.value = ''
    composable.onSearchInput()
    expect(composable.searchResults.value).toEqual([])
    expect(composable.showDropdown.value).toBe(false)
  })

  it('does not search with very short query on input', () => {
    composable.searchQuery.value = 'a'
    composable.onSearchInput()
    expect(marketApi.search).not.toHaveBeenCalled()
  })

  it('triggers search after input debounce', () => {
    vi.useFakeTimers()
    composable.searchQuery.value = '沪深300'
    composable.onSearchInput()
    expect(marketApi.search).not.toHaveBeenCalled() // not yet, debounced
    vi.advanceTimersByTime(300)
    expect(marketApi.search).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('populates search results from API response', async () => {
    marketApi.search.mockResolvedValue({ data: [
      { symbol: '510300', name: '沪深300ETF' },
    ]})
    composable.searchQuery.value = '510300'
    await composable.doSearch()
    expect(marketApi.search).toHaveBeenCalled()
    expect(composable.searchResults.value.length).toBeGreaterThan(0)
    expect(composable.searchResults.value[0].symbol).toBe('510300')
  })

  it('navigates results with ArrowDown key', () => {
    composable.searchResults.value = [
      { symbol: 'A', name: 'Test A', type: 'ETF' },
      { symbol: 'B', name: 'Test B', type: 'ETF' },
    ]
    composable.showDropdown.value = true
    expect(composable.activeIndex.value).toBe(-1)

    const e = new KeyboardEvent('keydown', { key: 'ArrowDown' })
    vi.spyOn(e, 'preventDefault').mockImplementation(() => {})
    composable.onSearchKeydown(e)
    expect(composable.activeIndex.value).toBe(0)

    const e2 = new KeyboardEvent('keydown', { key: 'ArrowDown' })
    vi.spyOn(e2, 'preventDefault').mockImplementation(() => {})
    composable.onSearchKeydown(e2)
    expect(composable.activeIndex.value).toBe(1)
  })

  it('navigates results with ArrowUp key', () => {
    composable.searchResults.value = [
      { symbol: 'A', name: 'Test A', type: 'ETF' },
      { symbol: 'B', name: 'Test B', type: 'ETF' },
    ]
    composable.showDropdown.value = true
    composable.activeIndex.value = 1

    const e = new KeyboardEvent('keydown', { key: 'ArrowUp' })
    vi.spyOn(e, 'preventDefault').mockImplementation(() => {})
    composable.onSearchKeydown(e)
    expect(composable.activeIndex.value).toBe(0)
  })

  it('selects item with Enter key', () => {
    composable.searchResults.value = [
      { symbol: '510300', name: '沪深300ETF', type: 'ETF' },
    ]
    composable.showDropdown.value = true

    const e = new KeyboardEvent('keydown', { key: 'Enter' })
    vi.spyOn(e, 'preventDefault').mockImplementation(() => {})
    composable.onSearchKeydown(e)
    expect(composable.selectedSearchItem.value).toEqual({
      symbol: '510300',
      name: '沪深300ETF',
      type: 'ETF',
    })
    expect(composable.showDropdown.value).toBe(false)
  })

  it('closes dropdown with Escape key', () => {
    composable.showDropdown.value = true
    composable.searchResults.value = [{ symbol: 'A', name: 'Test', type: 'ETF' }]

    const e = new KeyboardEvent('keydown', { key: 'Escape' })
    vi.spyOn(e, 'preventDefault').mockImplementation(() => {})
    composable.onSearchKeydown(e)
    expect(composable.showDropdown.value).toBe(false)
    expect(composable.activeIndex.value).toBe(-1)
  })

  it('selectSearchItem sets selected and updates query', () => {
    const item = { symbol: '510300', name: '沪深300ETF', type: 'ETF' }
    composable.selectSearchItem(item)
    expect(composable.selectedSearchItem.value).toEqual(item)
    expect(composable.searchQuery.value).toBe('沪深300ETF (510300)')
    expect(composable.showDropdown.value).toBe(false)
  })

  it('clearSearchItem resets all state', () => {
    composable.selectedSearchItem.value = { symbol: 'A', name: 'Test' }
    composable.searchQuery.value = 'Test'
    composable.searchResults.value = [{ symbol: 'A', name: 'Test' }]
    composable.showDropdown.value = true
    composable.activeIndex.value = 0

    composable.clearSearchItem()
    expect(composable.selectedSearchItem.value).toBeNull()
    expect(composable.searchQuery.value).toBe('')
    expect(composable.searchResults.value).toEqual([])
    expect(composable.showDropdown.value).toBe(false)
    expect(composable.activeIndex.value).toBe(-1)
  })

  it('Z29: doSearch passes raw Chinese keyword + include_stocks:true (axios 负责编码)', async () => {
    // 防回归：中文 keyword 必须原样传给 marketApi.search（不预编码、不手拼 URL），
    // include_stocks 显式传递（后端按分支生效）。
    marketApi.search.mockResolvedValue({ data: [{ symbol: '00700', name: '腾讯控股' }] })
    composable.searchQuery.value = '腾讯控股'
    await composable.doSearch()
    expect(marketApi.search).toHaveBeenCalledWith('腾讯控股', { include_stocks: true })
    expect(composable.searchResults.value[0].symbol).toBe('00700')
  })
})
