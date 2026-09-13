import { describe, it, expect } from 'vitest'
import { buildLLMCopyText, buildNewsCopyText } from './useCopy'

describe('useCopy builders', () => {
  it('appends modelLine to LLM content', () => {
    expect(buildLLMCopyText('hello', '模型 · deepseek')).toContain('模型 · deepseek')
  })
  it('handles missing model', () => {
    expect(buildLLMCopyText('hello', '')).toBe('hello')
  })
  it('builds news copy with attribution', () => {
    const s = buildNewsCopyText({ title: 'T', content: 'C', source: 'S', time: '2026-01-01', url: 'http://x' })
    expect(s).toContain('T')
    expect(s).toContain('来源：S')
    expect(s).toContain('http://x')
  })
})
