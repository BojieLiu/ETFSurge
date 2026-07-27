import { ref, watch, computed, onMounted } from 'vue'
import { fetchJson } from '../utils/fetchJson'

export function useSectorAnalysis(marketTab) {
  const sectorTypes = [
    { value: 'industry', label: '行业板块' },
    { value: 'concept', label: '概念板块' }
  ]
  const sectorType = ref('industry')
  const sectorList = ref([])
  const selectedSectorCode = ref('')
  const selectedSectorName = ref('')
  const sectorLoadingList = ref(false)
  const sectorReport = ref('')
  const sectorLoading = ref(false)
  const sectorError = ref('')
  const sectorQuery = ref('')
  const sectorDropdownOpen = ref(false)
  const sectorActiveIndex = ref(-1)
  const sectorComboRef = ref(null)
  // Manual input fallback — when API returns empty or user prefers direct typing
  const manualMode = ref(false)
  const sectorFetchError = ref('')

  const filteredSectors = computed(() => {
    const q = sectorQuery.value.trim().toLowerCase()
    if (!q) return sectorList.value
    return sectorList.value
      .filter(s => (s.sector_name || s.plate_name || '').toLowerCase().includes(q))
      .slice(0, 50)
  })

  async function fetchSectorList() {
    sectorLoadingList.value = true
    sectorFetchError.value = ''
    sectorList.value = []
    try {
      const url = sectorType.value === 'industry'
        ? `/api/v1/market/sectors/industry?limit=200${marketTab.value && marketTab.value !== 'global' ? '&market=' + marketTab.value : ''}`
        : `/api/v1/market/sectors/concept?limit=200${marketTab.value && marketTab.value !== 'global' ? '&market=' + marketTab.value : ''}`
      const data = await fetchJson(url)
      sectorList.value = Array.isArray(data) ? data : []
      if (!sectorList.value.length) {
        sectorFetchError.value = '列表为空，可切换至手动输入'
        manualMode.value = true
      }
    } catch (e) {
      sectorList.value = []
      sectorFetchError.value = '加载失败: ' + (e?.message || '网络错误')
      manualMode.value = true
    }
    sectorLoadingList.value = false
  }

  async function onSectorTypeChange() {
    selectedSectorCode.value = ''
    selectedSectorName.value = ''
    sectorQuery.value = ''
    sectorDropdownOpen.value = false
    sectorActiveIndex.value = -1
    sectorReport.value = ''
    manualMode.value = false
    sectorFetchError.value = ''
    await fetchSectorList()
  }

  function onSectorFocus() {
    if (sectorList.value.length) sectorDropdownOpen.value = true
  }

  function onSectorBlur() {
    setTimeout(() => { sectorDropdownOpen.value = false }, 200)
  }

  function selectSector(s) {
    const code = s.sector_code || s.plate_code
    selectedSectorCode.value = code
    selectedSectorName.value = s.sector_name || s.plate_name || ''
    sectorQuery.value = selectedSectorName.value
    sectorDropdownOpen.value = false
    sectorActiveIndex.value = -1
    manualMode.value = false
  }

  function clearSector() {
    selectedSectorCode.value = ''
    selectedSectorName.value = ''
    sectorQuery.value = ''
    sectorDropdownOpen.value = false
    sectorActiveIndex.value = -1
  }

  function onSectorKeydown(e) {
    const list = filteredSectors.value
    if (!sectorDropdownOpen.value || !list.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      sectorActiveIndex.value = (sectorActiveIndex.value + 1) % list.length
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      sectorActiveIndex.value = (sectorActiveIndex.value - 1 + list.length) % list.length
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = list[sectorActiveIndex.value] || list[0]
      if (item) selectSector(item)
    } else if (e.key === 'Escape') {
      sectorDropdownOpen.value = false
      sectorActiveIndex.value = -1
    }
  }

  // Manual input: use query value directly as sector code
  function useManualInput() {
    const q = sectorQuery.value.trim()
    if (!q) return
    selectedSectorCode.value = q
    selectedSectorName.value = q
    sectorDropdownOpen.value = false
  }

  // Watch marketTab changes to reload sectors
  watch(marketTab, () => { onSectorTypeChange() })

  // Auto-load on mount
  onMounted(() => { fetchSectorList() })

  return {
    sectorTypes, sectorType, sectorList, selectedSectorCode, selectedSectorName,
    sectorLoadingList, sectorReport, sectorLoading, sectorError,
    sectorQuery, sectorDropdownOpen, sectorActiveIndex, sectorComboRef,
    filteredSectors, sectorFetchError, manualMode,
    fetchSectorList, onSectorTypeChange,
    onSectorFocus, onSectorBlur, selectSector, clearSector, onSectorKeydown,
    useManualInput,
  }
}


export function getChangeClass(pct) {
  if (pct === undefined || pct === null) return ''
  return pct >= 0 ? 'text-up' : 'text-down'
}

export function formatChange(pct) {
  if (pct === undefined || pct === null) return ''
  const prefix = pct > 0 ? '+' : ''
  return prefix + pct.toFixed(2) + '%'
}
