import { ref, watch, computed } from 'vue'
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

  const filteredSectors = computed(() => {
    const q = sectorQuery.value.trim().toLowerCase()
    if (!q) return sectorList.value
    return sectorList.value
      .filter(s => (s.sector_name || s.plate_name || '').toLowerCase().includes(q))
      .slice(0, 50)
  })

  async function fetchSectorList() {
    sectorLoadingList.value = true
    sectorList.value = []
    try {
      const url = sectorType.value === 'industry'
        ? `/api/v1/market/sectors/industry?limit=200${marketTab.value && marketTab.value !== 'global' ? '&market=' + marketTab.value : ''}`
        : `/api/v1/market/sectors/concept?limit=200${marketTab.value && marketTab.value !== 'global' ? '&market=' + marketTab.value : ''}`
      const data = await fetchJson(url)
      sectorList.value = Array.isArray(data) ? data : []
    } catch {
      sectorList.value = []
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

  // Watch marketTab changes to reload sectors
  watch(marketTab, () => { onSectorTypeChange() })

  return { sectorTypes, sectorType, sectorList, selectedSectorCode, selectedSectorName,
    sectorLoadingList, sectorReport, sectorLoading, sectorError,
    sectorQuery, sectorDropdownOpen, sectorActiveIndex, sectorComboRef,
    filteredSectors, fetchSectorList, onSectorTypeChange,
    onSectorFocus, onSectorBlur, selectSector, clearSector, onSectorKeydown }
}
