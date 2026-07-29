import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api', () => ({
  marketApi: {
    getSectors: vi.fn(),
  },
}))

import { marketApi } from '../api'
import { useSectorAnalysis } from '../composables/useSectorAnalysis'

describe('useSectorAnalysis', () => {
  let composable
  let marketTab

  beforeEach(() => {
    vi.clearAllMocks()
    marketApi.getSectors.mockResolvedValue({ data: [] })
    marketTab = { value: 'A' }
    composable = useSectorAnalysis(marketTab)
  })

  it('returns initial state correctly', () => {
    expect(composable.sectorType.value).toBe('industry')
    expect(composable.sectorList.value).toEqual([])
    expect(composable.selectedSectorCode.value).toBe('')
    expect(composable.selectedSectorName.value).toBe('')
    expect(composable.sectorLoadingList.value).toBe(false)
    expect(composable.sectorQuery.value).toBe('')
    expect(composable.sectorDropdownOpen.value).toBe(false)
    expect(composable.sectorActiveIndex.value).toBe(-1)
    expect(composable.manualMode.value).toBe(false)
  })

  it('fetchSectorList fetches industry sectors', async () => {
    marketApi.getSectors.mockClear()
    await composable.fetchSectorList()
    expect(marketApi.getSectors).toHaveBeenCalled()
    expect(marketApi.getSectors.mock.calls[0][0]).toEqual({
      type: 'industry', limit: 200, market: 'A'
    })
  })

  it('switches to concept sector type and fetches', async () => {
    marketApi.getSectors.mockClear()
    composable.sectorType.value = 'concept'
    await composable.onSectorTypeChange()
    expect(marketApi.getSectors).toHaveBeenCalled()
    expect(marketApi.getSectors.mock.calls[0][0]).toEqual({
      type: 'concept', limit: 200, market: 'A'
    })
  })

  it('selectSector sets selected values and closes dropdown', () => {
    const sector = { sector_code: 'BK001', sector_name: '金融' }
    composable.selectSector(sector)
    expect(composable.selectedSectorCode.value).toBe('BK001')
    expect(composable.selectedSectorName.value).toBe('金融')
    expect(composable.sectorQuery.value).toBe('金融')
    expect(composable.sectorDropdownOpen.value).toBe(false)
    expect(composable.manualMode.value).toBe(false)
  })

  it('clearSector resets selection', () => {
    composable.selectedSectorCode.value = 'BK001'
    composable.selectedSectorName.value = '金融'
    composable.sectorQuery.value = '金融'

    composable.clearSector()
    expect(composable.selectedSectorCode.value).toBe('')
    expect(composable.selectedSectorName.value).toBe('')
    expect(composable.sectorQuery.value).toBe('')
    expect(composable.sectorDropdownOpen.value).toBe(false)
  })

  it('onSectorFocus opens dropdown when list is populated', () => {
    composable.sectorList.value = [{ sector_code: 'BK001', sector_name: '金融' }]
    composable.onSectorFocus()
    expect(composable.sectorDropdownOpen.value).toBe(true)
  })

  it('onSectorBlur closes dropdown after delay', () => {
    vi.useFakeTimers()
    composable.sectorDropdownOpen.value = true
    composable.onSectorBlur()
    vi.advanceTimersByTime(200)
    expect(composable.sectorDropdownOpen.value).toBe(false)
    vi.useRealTimers()
  })

  it('useManualInput sets code from query', () => {
    composable.sectorQuery.value = 'BK001'
    composable.useManualInput()
    expect(composable.selectedSectorCode.value).toBe('BK001')
    expect(composable.selectedSectorName.value).toBe('BK001')
    expect(composable.sectorDropdownOpen.value).toBe(false)
  })

  it('filteredSectors filters by query', async () => {
    composable.sectorList.value = [
      { sector_code: 'BK001', sector_name: '金融' },
      { sector_code: 'BK002', sector_name: '科技' },
      { sector_code: 'BK003', sector_name: '消费' },
    ]
    composable.sectorQuery.value = '金'
    expect(composable.filteredSectors.value.length).toBe(1)
    expect(composable.filteredSectors.value[0].sector_name).toBe('金融')
  })

  it('filteredSectors returns all when no query', () => {
    composable.sectorList.value = [
      { sector_code: 'BK001', sector_name: '金融' },
      { sector_code: 'BK002', sector_name: '科技' },
    ]
    composable.sectorQuery.value = ''
    expect(composable.filteredSectors.value.length).toBe(2)
  })
})
