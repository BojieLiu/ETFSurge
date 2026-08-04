import { ref, onUnmounted } from 'vue'
import { marketApi } from '../api'

/**
 * Composable for market search with debounce, keyboard nav, completion
 *
 * F17 (round6 §16.5): 支持 market 选项——A 场景只搜 A（短路后端 global 分支，
 * 不再并发拉 HK/US spot 列表）。
 */
export function useMarketSearch(options = {}) {
  const marketFilter = options.market || ''
  // O30 (round7 §7 P30①): kind 透传——sector/index 模式复用同一下拉（后端 /search kind 参数）
  const kindFilter = options.kind || 'all'
  const searchQuery = ref('')
  const searchResults = ref([])
  const showDropdown = ref(false)
  const activeIndex = ref(-1)
  const completionFull = ref('')
  const selectedSearchItem = ref(null)
  const searchRef = ref(null)
  let searchTimer = null

  // R5 搜索提速：
  // 1) debounce 300ms → 200ms（后端 search 实测 4-14ms，300ms 等待无必要）
  // 2) AbortController 取消过期请求（快速输入时只保留最后一次的网络）
  // 3) seq 守卫丢弃乱序响应（防慢请求覆盖新结果）
  // 4) 60s 结果缓存（instruments 表低频变化，重复关键词直接命中）
  const SEARCH_DEBOUNCE_MS = 200
  const SEARCH_CACHE_TTL = 60_000
  const searchCache = new Map() // `${include_stocks}:${q}` -> { ts, results }
  let searchSeq = 0
  let searchAbort = null

  function applyResults(results) {
    searchResults.value = results
    activeIndex.value = -1
    updateCompletion()
    showDropdown.value = results.length > 0
  }

  function updateCompletion() {
    const top = searchResults.value[0]
    // 补全预览：代码 + 名称（如 "510300 沪深300ETF"），代码前置便于快速识别
    completionFull.value = top ? `${top.symbol} ${top.name}` : ''
  }

  function acceptCompletion() {
    const top = searchResults.value[0]
    if (!top) return
    searchQuery.value = `${top.symbol} ${top.name}`
    activeIndex.value = 0
    completionFull.value = ''
    showDropdown.value = true
  }

  async function doSearch() {
    const q = searchQuery.value.trim()
    if (!q) return
    const cacheKey = `stocks:${q}`
    const hit = searchCache.get(cacheKey)
    if (hit && Date.now() - hit.ts < SEARCH_CACHE_TTL) {
      applyResults(hit.results)
      return
    }
    const seq = ++searchSeq
    if (searchAbort) searchAbort.abort()
    searchAbort = new AbortController()
    try {
      // O30: kind 透传——symbol 模式默认 all（含板块/指数尾部段），
      // sector/index 模式传对应 kind（后端只查对应表）
      const kind = kindFilter === 'all' ? 'all' : kindFilter
      const res = await marketApi.search(
        q,
        { include_stocks: true, kind, ...(marketFilter && kind === 'all' ? { market: marketFilter } : {}) },
        { signal: searchAbort.signal },
      )
      if (seq !== searchSeq) return // 过期响应丢弃
      const results = (res.data || []).slice(0, 20)
      searchCache.set(cacheKey, { ts: Date.now(), results })
      applyResults(results)
    } catch (e) {
      if (e?.name === 'AbortError' || seq !== searchSeq) return
      searchResults.value = []
      completionFull.value = ''
    }
  }

  function onSearchInput() {
    clearTimeout(searchTimer)
    activeIndex.value = -1
    completionFull.value = ''
    if (!searchQuery.value || searchQuery.value.length < 1) {
      searchResults.value = []
      showDropdown.value = false
      return
    }
    searchTimer = setTimeout(doSearch, SEARCH_DEBOUNCE_MS)
  }

  function onSearchFocus() {
    if (searchResults.value.length) showDropdown.value = true
  }

  function onSearchBlur() {
    setTimeout(() => { showDropdown.value = false }, 200)
  }

  function onSearchKeydown(e) {
    const list = searchResults.value
    if (e.key === 'Tab' && completionFull.value) {
      e.preventDefault()
      acceptCompletion()
      return
    }
    if (!showDropdown.value || !list.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      activeIndex.value = (activeIndex.value + 1) % list.length
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      activeIndex.value = (activeIndex.value - 1 + list.length) % list.length
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = list[activeIndex.value] || list[0]
      if (item) selectSearchItem(item)
    } else if (e.key === 'Escape') {
      showDropdown.value = false
      activeIndex.value = -1
    }
  }

  function selectSearchItem(item) {
    selectedSearchItem.value = item
    showDropdown.value = false
    activeIndex.value = -1
    completionFull.value = ''
    searchQuery.value = `${item.name} (${item.symbol})`
  }

  function clearSearchItem() {
    selectedSearchItem.value = null
    searchQuery.value = ''
    searchResults.value = []
    showDropdown.value = false
    activeIndex.value = -1
    completionFull.value = ''
  }

  onUnmounted(() => { clearTimeout(searchTimer) })

  return { searchQuery, searchResults, showDropdown, activeIndex, completionFull, selectedSearchItem, searchRef, doSearch, onSearchInput, onSearchFocus, onSearchBlur, onSearchKeydown, selectSearchItem, clearSearchItem }
}
