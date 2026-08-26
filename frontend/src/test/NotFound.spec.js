import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

// round34-B7 批复⑤：catch-all 404 兜底视图
import NotFound from '../views/NotFound.vue'

describe('NotFound.vue (B7 批复⑤)', () => {
  it('渲染 404 标识与引导文案', () => {
    const w = mount(NotFound)
    expect(w.text()).toContain('404')
    expect(w.text()).toContain('页面不存在')
  })

  it('提供返回市场概览的链接', () => {
    const w = mount(NotFound, {
      global: {
        stubs: {
          'router-link': { template: '<a class="home-link" :data-to="to"><slot /></a>', props: ['to'] },
        },
      },
    })
    const link = w.find('.home-link')
    expect(link.exists()).toBe(true)
    expect(link.attributes('data-to')).toBe('/')
    expect(link.text()).toContain('返回市场概览')
  })
})
