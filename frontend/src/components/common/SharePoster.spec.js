import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SharePoster from './SharePoster.vue'

describe('SharePoster', () => {
  it('renders modelLine and disclaimer', () => {
    const w = mount(SharePoster, { props: { title: 'T', modelLine: '模型 · deepseek', body: 'B', disclaimer: '仅供参考' } })
    expect(w.text()).toContain('模型 · deepseek')
    expect(w.text()).toContain('仅供参考')
    expect(w.text()).toContain('ETFSurge')
  })
  it('falls back to 模型未知', () => {
    const w = mount(SharePoster, { props: { title: 'T', body: 'B' } })
    expect(w.text()).toContain('模型未知')
  })
})
