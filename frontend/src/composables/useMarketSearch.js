import { ref, onUnmounted } from 'vue'
import { fetchJson } from '../utils/fetchJson'

/**
 * Composable for market search with debounce, keyboard nav, completion
 */
export function useMarketSearch() {
  const searchQuery = ref('')
  const searchResults = ref([])
  const showDropdown = ref(false)
  const activeIndex = ref(-1)
  const completionFull = ref('')
  const selectedSearchItem = ref(null)
  const searchRef = ref(null)
  let searchTimer = null

  function updateCompletion() {
    const top = searchResults.value[0]
    completionFull.value = top ? `${top.name} (${top.symbol})` : ''
  }

  function acceptCompletion() {
    const top = searchResults.value[0]
    if (!top) return
    searchQuery.value = `${top.name} (${top.symbol})`
    activeIndex.value = 0
    completionFull.value = ''
    showDropdown.value = true
  }

  async function doSearch() {
    const q = searchQuery.value.trim()
    if (!q) return
    try {
      const [etfRes, stockRes] = await Promise.all([
        fetchJson(`/api/v1/market/search?keyword=${encodeURIComponent(q)}`),
        fetchJson(`/api/v1/market/search/stocks?keyword=${encodeURIComponent(q)}`)
      ])
      const etfs = (Array.isArray(etfRes) ? etfRes : (etfRes.data || etfRes.results || [])).map(r => ({ symbol: r.symbol, name: r.name, type: 'ETF' }))
      const stocks = (Array.isArray(stockRes) ? stockRes : (stockRes.data || stockRes.results || [])).map(r => ({ symbol: r.symbol, name: r.name, type: '股票' }))
      searchResults.value = [...etfs, ...stocks].slice(0, 20)
      activeIndex.value = -1
      updateCompletion()
      showDropdown.value = searchResults.value.length > 0
    } catch {
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
    searchTimer = setTimeout(doSearch, 300)
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
