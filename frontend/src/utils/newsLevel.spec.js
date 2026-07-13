import { describe, it, expect } from 'vitest'
import { mapNewsLevel, isImportant } from './newsLevel'

describe('mapNewsLevel (level -> {color, stars})', () => {
  it('maps level >= 4 to red + 4 stars (重要)', () => {
    expect(mapNewsLevel(4)).toEqual({ color: 'red', stars: '★★★★', label: '重要' })
    expect(mapNewsLevel(5)).toEqual({ color: 'red', stars: '★★★★', label: '重要' })
  })

  it('maps level 3 to orange + 3 stars (关注)', () => {
    expect(mapNewsLevel(3)).toEqual({ color: 'orange', stars: '★★★', label: '关注' })
  })

  it('maps level 2 to blue + 2 stars (一般)', () => {
    expect(mapNewsLevel(2)).toEqual({ color: 'blue', stars: '★★', label: '一般' })
  })

  it('maps level 1 (and 0/garbage) to gray + 1 star (普通)', () => {
    expect(mapNewsLevel(1)).toEqual({ color: 'gray', stars: '★', label: '普通' })
    expect(mapNewsLevel(0)).toEqual({ color: 'gray', stars: '★', label: '普通' })
    expect(mapNewsLevel('oops')).toEqual({ color: 'gray', stars: '★', label: '普通' })
  })
})

describe('isImportant', () => {
  it('is true for level >= 4', () => {
    expect(isImportant(4)).toBe(true)
    expect(isImportant(5)).toBe(true)
  })
  it('is false for level <= 3', () => {
    expect(isImportant(3)).toBe(false)
    expect(isImportant(1)).toBe(false)
    expect(isImportant(0)).toBe(false)
  })
})
