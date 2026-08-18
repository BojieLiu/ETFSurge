import { describe, it, expect } from 'vitest'
import { formatDate, formatDateOnly } from '../utils/formatDate'

describe('formatDate', () => {
  it('converts UTC to Beijing time correctly', () => {
    // 2026-07-17 10:30:00 UTC = 2026-07-17 18:30:00 CST (Asia/Shanghai)
    const result = formatDate('2026-07-17T10:30:00Z')
    expect(result).toContain('2026')
    expect(result).toContain('07')
    expect(result).toContain('17')
    expect(result).toContain('18')
    expect(result).toContain('30')
  })

  it('handles UTC+8:00 date crossing correctly', () => {
    // 2026-07-17 23:00:00 UTC = 2026-07-18 07:00:00 CST
    const result = formatDate('2026-07-17T23:00:00Z')
    expect(result).toContain('18')  // date should cross to next day
    expect(result).toContain('07')
    expect(result).toContain('00')
  })

  it('handles midnight UTC (8am Beijing)', () => {
    // 2026-01-01 00:00:00 UTC = 2026-01-01 08:00:00 CST
    const result = formatDate('2026-01-01T00:00:00Z')
    expect(result).toContain('01')
    expect(result).toContain('08')
    expect(result).toContain('00')
  })

  it('returns empty string for null input', () => {
    expect(formatDate(null)).toBe('')
  })

  it('returns empty string for undefined input', () => {
    expect(formatDate(undefined)).toBe('')
  })

  it('returns empty string for empty string input', () => {
    expect(formatDate('')).toBe('')
  })

  it('returns input string for invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('handles ISO string without Z suffix (auto-appends Z for UTC parsing)', () => {
    // Backend returns "2026-07-17T10:30:00" (no Z suffix)
    // formatDate now appends Z automatically
    const result = formatDate('2026-07-17T10:30:00')
    expect(result).toContain('2026')
    expect(result).toContain('07')
    expect(result).toContain('17')
    expect(result).toContain('18')  // UTC 10:30 → CST 18:30
    expect(result).toContain('30')
  })

  it('does not double-append Z to already timezone-aware strings', () => {
    const result = formatDate('2026-07-17T10:30:00+05:00')
    // +05:00 = 5h ahead of UTC, so UTC = 05:30, CST = 13:30
    expect(result).toContain('13')
    expect(result).toContain('30')
  })
})

describe('formatDateOnly', () => {
  it('returns date part only in YYYY-MM-DD format (Beijing time)', () => {
    const result = formatDateOnly('2026-07-17T20:00:00Z')
    // 2026-07-17 20:00 UTC = 2026-07-18 04:00 CST
    expect(result).toContain('18')
    expect(result).not.toContain('04')  // no time
  })

  it('handles ISO string without Z suffix', () => {
    const result = formatDateOnly('2026-07-17T20:00:00')
    expect(result).toContain('18')  // UTC 20:00 → CST next day 04:00
  })

  it('returns empty for null', () => {
    expect(formatDateOnly(null)).toBe('')
  })
})
