import { describe, it, expect } from 'vitest'
import { changeClass } from './changeClass'

// --- Issue 1: P&L color convention (红涨绿跌) ---
// Positive / zero values must map to the UP (red) class.
// Negative values must map to the DOWN (green) class.
describe('changeClass (红涨绿跌)', () => {
  it('maps a positive value to text-up (red)', () => {
    expect(changeClass(1.23)).toBe('text-up')
  })

  it('maps zero to text-up (red)', () => {
    expect(changeClass(0)).toBe('text-up')
  })

  it('maps a negative value to text-down (green)', () => {
    expect(changeClass(-0.5)).toBe('text-down')
  })

  it('maps a large negative value to text-down (green)', () => {
    expect(changeClass(-99.99)).toBe('text-down')
  })
})
