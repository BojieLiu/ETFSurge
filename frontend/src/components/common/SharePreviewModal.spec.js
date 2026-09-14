import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SharePreviewModal from './SharePreviewModal.vue'

describe('SharePreviewModal', () => {
  it('renders image and Jinshi-style actions when visible', () => {
    const w = mount(SharePreviewModal, { props: { visible: true, title: 'T', imageUrl: 'blob:x' } })
    expect(w.find('.share-preview-img').exists()).toBe(true)
    expect(w.text()).toContain('复制到剪贴板')
    expect(w.text()).toContain('下载图片')
  })
  it('hidden when not visible', () => {
    const w = mount(SharePreviewModal, { props: { visible: false } })
    expect(w.find('.share-preview-modal').exists()).toBe(false)
  })
  it('shows clipboard success tip', () => {
    const w = mount(SharePreviewModal, { props: { visible: true, imageUrl: 'blob:x', copyState: 'ok' } })
    expect(w.text()).toContain('已复制到剪贴板')
  })
})
