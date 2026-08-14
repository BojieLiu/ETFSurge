/**
 * F22/F23 (round23 P0-A): 资讯分级双维度——category(极性, 着色) + level(重要性, 推送/筛选)。
 */
import { describe, it, expect } from 'vitest'
import { mapNewsCategory, categoryColor, categoryColorClass, isImportant } from '../utils/newsLevel'

describe('newsLevel — F22 category/level 双维度', () => {
  it('利空/风险/利好 均可 importance>=4 进重要推送（不再只推利好）', () => {
    expect(isImportant(4)).toBe(true) // 利空/风险 重要
    expect(isImportant(3)).toBe(false) // 普通利空不推送
  })

  it('category 着色遵循红涨绿跌：利好红、利空绿、风险橙(非利好红)', () => {
    expect(categoryColor('positive', 4)).toBe('#e64545')
    expect(categoryColor('negative', 4)).toBe('#1aa260')
    expect(categoryColor('risk', 4)).toBe('#f59e0b')
    expect(categoryColorClass('risk', 4)).toBe('orange') // 风险≠利好红
    expect(categoryColorClass('positive', 4)).toBe('red')
  })

  it('category 缺失时回退 level 语义', () => {
    expect(mapNewsCategory(null, 5).label).toBeTruthy()
  })
})
